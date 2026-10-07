import re

from . import net
from .config import StudyError
from .fmt import plain

PAGE = 50
WRITE = {"mod_assign_save_submission", "mod_assign_submit_for_grading"}
SUBMISSION = {"new": "не сдано", "draft": "черновик", "reopened": "на доработку",
              "submitted": "сдано", "offline": "очно / без ответа в ТУИС"}
PENDING = {"new", "draft", "reopened"}


class Moodle:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg.get("TUIS_URL").rstrip("/")
        self._me = None
        self._contents = {}


    def call(self, fn, **params):
        form = {"wstoken": self.cfg.token("TUIS_TOKEN"),
                "moodlewsrestformat": "json", "wsfunction": fn}
        for key, value in params.items():
            if isinstance(value, (list, tuple)):
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


    def courses(self, include_hidden=False):
        out = self.call("core_enrol_get_users_courses", userid=self.me()["userid"])
        return [c for c in out if include_hidden or not c.get("hidden")]

    def assignments(self, courseids=None):
        out = self.call("mod_assign_get_assignments", courseids=courseids or [])
        return out.get("courses", []), out.get("warnings", [])

    def submission_status(self, assignid):
        return self.call("mod_assign_get_submission_status", assignid=assignid)

    def forums(self, courseids):
        return self.call("mod_forum_get_forums_by_courses", courseids=courseids)

    def discussions(self, forumid, perpage=10):
        try:
            out = self.call("mod_forum_get_forum_discussions", forumid=forumid, page=0,
                            perpage=perpage)
        except StudyError as e:
            if e.code != "invalidrecord":
                raise
            out = self.call("mod_forum_get_forum_discussions_paginated", forumid=forumid,
                            sortby="timemodified", sortdirection="DESC", page=0, perpage=perpage)
        return out.get("discussions", [])

    def contents(self, courseid):
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
        return self.call("mod_choice_get_choice_options",
                         choiceid=choiceid).get("options", [])

    def quizzes(self, courseids):
        return self.call("mod_quiz_get_quizzes_by_courses",
                         courseids=list(courseids)).get("quizzes", [])

    def quiz_attempts(self, quizid):
        return self.call("mod_quiz_get_user_attempts", quizid=quizid,
                         status="all").get("attempts", [])

    def calendar(self, frm, to):
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
        sep = "&" if "?" in fileurl else "?"
        return net.raw(fileurl + sep + "token=" + self.cfg.token("TUIS_TOKEN"),
                       "moodle", where="pluginfile", retries=net.RETRIES)

    def functions(self):
        return sorted(f["name"] for f in self.me()["functions"])


    def upload(self, paths, itemid=0):
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
            last = out[0]["itemid"]
        return last

    def save_submission(self, assignid, text, itemid=None):
        params = {"assignmentid": assignid}
        if text is not None:
            params.update({"plugindata[onlinetext_editor][text]": text,
                           "plugindata[onlinetext_editor][format]": 4,
                           "plugindata[onlinetext_editor][itemid]": 0})
        if itemid:
            params["plugindata[files_filemanager]"] = itemid
        return warned(self.call("mod_assign_save_submission", **params),
                      "mod_assign_save_submission")

    def submit_for_grading(self, assignid, statement=False):
        return warned(self.call("mod_assign_submit_for_grading", assignmentid=assignid,
                                acceptsubmissionstatement=1 if statement else 0),
                      "mod_assign_submit_for_grading")


def warned(out, fn):
    if isinstance(out, list) and out:
        raise StudyError("moodle", "; ".join(plain(w.get("item")) or w.get("message", "")
                                             for w in out),
                         code=out[0].get("warningcode"), where=fn)
    return out



def grade_of(status):
    grade = ((status.get("feedback") or {}).get("grade") or {}).get("grade")
    try:
        return grade if grade is not None and float(grade) >= 0 else None
    except ValueError:
        return None


def feedback_text(status):
    for plugin in (status.get("feedback") or {}).get("plugins") or []:
        for field in plugin.get("editorfields") or []:
            if field.get("name") == "comments" and field.get("text"):
                return plain(field["text"], 2000)
    return None


def submission_state(assign, st, now):
    la = st.get("lastattempt") or {}
    status = (la.get("submission") or {}).get("status") or "new"
    team = assign.get("teamsubmission") == 1
    if team and status == "new" and (la.get("teamsubmission") or {}).get("status"):
        status = la["teamsubmission"]["status"]
    grade = grade_of(st)
    graded = bool(la.get("graded")) or grade is not None
    if grade is not None and status == "new":
        status = "submitted"
    if status == "new" and (la.get("submissionsenabled") is False
                            or assign.get("nosubmissions") == 1):
        status = "offline"
    ext = la.get("extensionduedate") or 0
    due = ext or assign.get("duedate") or 0
    cutoff = assign.get("cutoffdate") or 0
    cutoff = max(cutoff, ext) if cutoff else 0
    opens = assign.get("allowsubmissionsfromdate") or 0
    opens = opens if opens > now else 0
    canedit = la.get("canedit")
    return {"status": status, "grade": grade, "feedback": feedback_text(st), "graded": graded,
            "closed": canedit is False and not opens and status in PENDING,
            "locked": bool(la.get("locked")), "opens": opens or None, "due": due or None,
            "cutoff": cutoff or None, "canedit": canedit, "team": team}



def accepts(assign):
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


def check_state(s, when):
    if s["status"] == "offline":
        return ["у задания нет ответа в ТУИС (очная сдача) — отправлять нечего"]
    if s["opens"] and s["status"] in PENDING:
        return [f"приём откроется {when(s['opens'])}"]
    if s["canedit"] is False:
        why = ("заблокировано преподавателем" if s["locked"]
               else "уже оценено" + (f" ({s['grade']})" if s["grade"] else "") if s["graded"]
               else "ответ уже отправлен на проверку, правка закрыта"
               if s["status"] == "submitted"
               else f"приём закрыт {when(s['cutoff'])}" if s["cutoff"]
               else "приём закрыт (canedit=false)")
        return [why + " — нужна «Пересдача …» или разрешение преподавателя"]
    return []


def accepts_line(acc):
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
