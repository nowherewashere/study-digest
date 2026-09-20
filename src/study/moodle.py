"""Клиент ТУИС (Moodle). Подробности ручек — в ../docs/tuis-api.md."""
import re

from . import net
from .config import StudyError

PAGE = 50   # предел limitnum у календаря
WRITE = {"mod_assign_save_submission"}   # необратимые ручки: без повторов (см. net.RETRIES)


class Moodle:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg.get("TUIS_URL").rstrip("/")
        self._me = None
        self._contents = {}

    # --- основа

    def call(self, fn, **params):
        """Вызов ручки. Ошибка Moodle приходит с HTTP 200 в теле, поэтому проверяем тело."""
        form = {"wstoken": self.cfg.token("TUIS_TOKEN"),
                "moodlewsrestformat": "json", "wsfunction": fn}
        for key, value in params.items():
            if isinstance(value, (list, tuple)):
                # Массивы кодируются по-Moodle: courseids[0], courseids[1], …
                for i, item in enumerate(value):
                    form[f"{key}[{i}]"] = item
            elif value is not None:
                form[key] = value
        out = net.request(f"{self.base}/webservice/rest/server.php", "moodle", form=form,
                          where=fn, retries=0 if fn in WRITE else net.RETRIES)
        if isinstance(out, dict) and out.get("exception"):
            raise StudyError("moodle", out.get("message", "ошибка"),
                             code=out.get("errorcode"), where=fn)
        return out

    def me(self):
        if self._me is None:
            self._me = self.call("core_webservice_get_site_info")
        return self._me

    # --- чтение

    def courses(self, include_hidden=False):
        out = self.call("core_enrol_get_users_courses", userid=self.me()["userid"])
        return [c for c in out if include_hidden or not c.get("hidden")]

    def assignments(self, courseids=None):
        out = self.call("mod_assign_get_assignments", courseids=courseids or [])
        # Задания с ограничением доступа сюда НЕ попадают: приходит warning
        # "No access rights in module context", их сроки берутся из course_contents.
        return out.get("courses", []), out.get("warnings", [])

    def submission_status(self, assignid):
        return self.call("mod_assign_get_submission_status", assignid=assignid)

    def contents(self, courseid):
        # состав курса нужен и сводке, и выгрузке файлов — второй раз не ходим
        if courseid not in self._contents:
            self._contents[courseid] = self.call("core_course_get_contents", courseid=courseid)
        return self._contents[courseid]

    def updates_since(self, courseid, since):
        return self.call("core_course_get_updates_since", courseid=courseid,
                         since=since).get("instances", [])

    def choices(self, courseids):
        return self.call("mod_choice_get_choices_by_courses",
                         courseids=list(courseids)).get("choices", [])

    def choice_options(self, choiceid):
        """У выбранного варианта checked=true — так видно, выбрана ли тема доклада."""
        return self.call("mod_choice_get_choice_options",
                         choiceid=choiceid).get("options", [])

    def quizzes(self, courseids):
        return self.call("mod_quiz_get_quizzes_by_courses",
                         courseids=list(courseids)).get("quizzes", [])

    def quiz_attempts(self, quizid):
        return self.call("mod_quiz_get_user_attempts", quizid=quizid,
                         status="all").get("attempts", [])

    def calendar(self, frm, to):
        """limitnum у этой ручки максимум 50; дальше — курсором aftereventid (lastid ответа):
        сдвиг timesortfrom терял бы события с одинаковым сроком на границе страницы."""
        events, after = [], None
        while True:
            out = self.call("core_calendar_get_action_events_by_timesort",
                            timesortfrom=frm, timesortto=to, aftereventid=after, limitnum=PAGE)
            batch = out.get("events", [])
            events += batch
            if len(batch) < PAGE:
                return events
            after = out["lastid"]

    def grades(self, courseid):
        return self.call("gradereport_user_get_grade_items", courseid=courseid,
                         userid=self.me()["userid"]).get("usergrades", [])

    def notifications(self, limit=10):
        return self.call("core_message_get_messages", useridto=self.me()["userid"],
                         useridfrom=0, type="notifications", read=0, newestfirst=1,
                         limitfrom=0, limitnum=limit).get("messages", [])

    def download(self, fileurl):
        """Файлы курса качаются не через REST: GET по fileurl с токеном в query."""
        sep = "&" if "?" in fileurl else "?"
        return net.raw(fileurl + sep + "token=" + self.cfg.token("TUIS_TOKEN"),
                       "moodle", where="pluginfile", retries=net.RETRIES)

    def functions(self):
        return sorted(f["name"] for f in self.me()["functions"])

    # --- запись

    def upload(self, paths, itemid=0):
        """Файл кладётся в черновую область строго в поле file_1. Возвращает itemid."""
        last = itemid
        for path in paths:
            data = path.read_bytes()
            out = net.request(f"{self.base}/webservice/upload.php", "moodle",
                              fields={"token": self.cfg.token("TUIS_TOKEN"),
                                      "filearea": "draft", "itemid": str(last)},
                              files=[("file_1", path.name, data, "application/octet-stream")],
                              timeout=900, where="upload.php")
            if isinstance(out, dict) and out.get("error"):
                raise StudyError("moodle", out["error"], where="upload.php")
            # Несколько файлов кладутся в один itemid: он берётся из ответа и передаётся дальше.
            last = out[0]["itemid"]
        return last

    def save_submission(self, assignid, text, itemid=None):
        """Отправка ответа. Необратима: у заданий submissiondrafts=0, черновиков нет."""
        params = {"assignmentid": assignid}
        if text is not None:
            params.update({"plugindata[onlinetext_editor][text]": text,
                           # 4 = FORMAT_MARKDOWN (1 = HTML, 2 = обычный текст)
                           "plugindata[onlinetext_editor][format]": 4,
                           "plugindata[onlinetext_editor][itemid]": 0})
        if itemid:
            params["plugindata[files_filemanager]"] = itemid
        return self.call("mod_assign_save_submission", **params)


# --- правила сдачи задания

def accepts(assign):
    """Что принимает задание — по `configs` из mod_assign_get_assignments; None — настроек нет
    (тогда не проверяем, а не считаем всё выключенным)."""
    cfg = {}
    for c in assign.get("configs") or []:
        if c.get("subtype") == "assignsubmission":
            cfg.setdefault(c.get("plugin"), {})[c.get("name")] = c.get("value")
    if not cfg:
        return None
    f, t = cfg.get("file", {}), cfg.get("onlinetext", {})
    types = [x.lower() for x in re.split(r"[,;\s]+", f.get("filetypeslist") or "") if x]
    return {"files": {"enabled": f.get("enabled") == "1",
                      "max": int(f.get("maxfilesubmissions") or 0) or None,
                      "max_bytes": int(f.get("maxsubmissionsizebytes") or 0) or None,
                      "types": types},
            "text": {"enabled": t.get("enabled") == "1",
                     "words": int(t.get("wordlimit") or 0) or None
                     if t.get("wordlimitenabled") == "1" else None}}


def mb(n):
    if n >= 1073741824:
        return f"{n / 1073741824:g} ГБ"
    return f"{n / 1048576:g} МБ" if n >= 1048576 else f"{n // 1024} КБ"


def check_submission(acc, text, paths, itemid=None):
    """Что помешает отправке; пусто — можно. `paths` — вложения с диска, `itemid` — готовая
    черновая область (её состав не виден, не проверяется). Типы — только если в списке
    задания одни расширения: группы Moodle вроде `document` развернуть нельзя."""
    out = []
    if text is None and not paths and not itemid:
        out.append("нечего отправлять: ни --text, ни --attach, ни --files")
    have = []
    for p in paths:
        (have if p.is_file() else out).append(p if p.is_file() else f"нет файла {p}")
    if acc is None:
        return out
    f, t = acc["files"], acc["text"]
    if text is not None and not t["enabled"]:
        out.append("текст ответа в задании выключен — только файлы")
    elif text is not None and t["words"] and len(text.split()) > t["words"]:
        out.append(f"текст длиннее лимита: {len(text.split())} слов, можно {t['words']}")
    if (paths or itemid) and not f["enabled"]:
        out.append("файлы в задании выключены — только текст")
        return out
    if f["max"] and len(have) > f["max"]:
        out.append(f"файлов {len(have)}, задание принимает до {f['max']}")
    strict = f["types"] and all(x.startswith(".") for x in f["types"])
    for p in have:
        size = p.stat().st_size
        if f["max_bytes"] and size > f["max_bytes"]:
            out.append(f"{p.name}: {mb(size)}, предел {mb(f['max_bytes'])}")
        if strict and p.suffix.lower() not in f["types"]:
            out.append(f"{p.name}: тип {p.suffix.lower() or 'без расширения'} "
                       f"не из списка {', '.join(f['types'])}")
    return out


def accepts_line(acc):
    """«текст — да, до 500 слов · файлы — до 3, типы .pdf, до 20 МБ» для плана отправки."""
    if acc is None:
        return "неизвестно (у задания нет configs)"
    f, t = acc["files"], acc["text"]
    text = ("да" + (f", до {t['words']} слов" if t["words"] else "")) if t["enabled"] else "нет"
    files_ = "нет"
    if f["enabled"]:
        parts = [f"до {f['max']}" if f["max"] else "без ограничения числа"]
        if f["types"]:
            parts.append("типы " + ", ".join(f["types"]))
        if f["max_bytes"]:
            parts.append("до " + mb(f["max_bytes"]))
        files_ = ", ".join(parts)
    return f"текст — {text} · файлы — {files_}"
