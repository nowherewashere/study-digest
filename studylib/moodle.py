"""Клиент ТУИС (Moodle). Подробности ручек — в ../tuis-api.md."""
from . import net
from .config import StudyError


class Moodle:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg.get("TUIS_URL").rstrip("/")
        self._me = None

    # --- основа

    def call(self, fn, **params):
        """Вызов ручки. Ошибка Moodle приходит с HTTP 200 в теле, поэтому проверяем тело."""
        form = {"wstoken": self.cfg.token("TUIS_TOKEN_FILE"),
                "moodlewsrestformat": "json", "wsfunction": fn}
        for key, value in params.items():
            if isinstance(value, (list, tuple)):
                # Массивы кодируются по-Moodle: courseids[0], courseids[1], …
                for i, item in enumerate(value):
                    form[f"{key}[{i}]"] = item
            elif value is not None:
                form[key] = value
        out = net.request(f"{self.base}/webservice/rest/server.php", "moodle",
                          form=form, where=fn)
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
        return self.call("core_course_get_contents", courseid=courseid)

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
        """limitnum у этой ручки максимум 50, поэтому окно листается по частям."""
        events, start = [], frm
        while start < to:
            batch = self.call("core_calendar_get_action_events_by_timesort",
                              timesortfrom=start, timesortto=to,
                              limitnum=50).get("events", [])
            events += batch
            if len(batch) < 50:
                break
            start = batch[-1]["timesort"] + 1
        return events

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
        return net.raw(fileurl + sep + "token=" + self.cfg.token("TUIS_TOKEN_FILE"),
                       "moodle", where="pluginfile")

    def functions(self):
        return sorted(f["name"] for f in self.me()["functions"])

    # --- запись

    def upload(self, paths, itemid=0):
        """Файл кладётся в черновую область строго в поле file_1. Возвращает itemid."""
        last = itemid
        for path in paths:
            data = path.read_bytes()
            out = net.request(f"{self.base}/webservice/upload.php", "moodle",
                              fields={"token": self.cfg.token("TUIS_TOKEN_FILE"),
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
        params = {"assignmentid": assignid,
                  "plugindata[onlinetext_editor][text]": text,
                  # 4 = FORMAT_MARKDOWN (1 = HTML, 2 = обычный текст)
                  "plugindata[onlinetext_editor][format]": 4,
                  "plugindata[onlinetext_editor][itemid]": 0}
        if itemid:
            params["plugindata[files_filemanager]"] = itemid
        return self.call("mod_assign_save_submission", **params)
