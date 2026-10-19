import re
import time

from kit.config import ROOT, soft

from .assigns import SUBMISSION, Registry
from .config import SKILLS
from .fmt import failures, moment, plain
from .moodle import PENDING, accepts, accepts_line, comment_rows, submission_state

DELIVERABLES = (".docx", ".pdf", ".odt", ".xlsx", ".zip")


def on_disk(code, num, flow):
    if not code or not num or flow != "direct":
        return None
    d = ROOT / code / f"lab{num}"
    found = sorted(p for p in d.rglob("*") if p.suffix in DELIVERABLES and p.is_file()) \
        if d.is_dir() else []
    return {"path": str(d), "exists": d.is_dir(),
            "files": [str(p.relative_to(d)) for p in found]}


def in_stash(code, num):
    if not code or not num:
        return []
    stash = ROOT / code / "stash"
    pat = re.compile(rf"(?<![\d.])0*{int(num)}(?![\d.])")
    return sorted(p.name for p in stash.rglob("*") if p.is_file() and pat.search(p.stem)) \
        if stash.is_dir() else []


def build(cfg, moodle, course, what):
    errors = []
    reg = Registry(moodle, [course.id], soft=lambda where: soft(errors, where))
    w = reg.find(course, what)
    flow = cfg.flows().get(course.id)
    d = {"course": {"id": course.id, "code": course.code,
                    "title": reg.title(course.id) or course.title},
         "assign_id": w.assign_id, "cmid": w.cmid, "name": w.name, "short": w.short,
         "num": w.lab, "source": w.source, "available": w.available, "reason": w.reason,
         "section": w.section, "flow": flow, "skill": SKILLS.get(flow),
         "local": on_disk(course.code, w.lab, flow), "stash": in_stash(course.code, w.lab),
         "warnings": errors}
    if not w.available:
        return dict(d, due=moment(w.due), opens=moment(w.opens), closed=True, locked=False,
                    canedit=False, team=False, graded=False, accepts=None, accepts_line="—",
                    intro=w.intro, attachments=[], grade=None, grade_text=None, feedback=None,
                    comments=[],
                    submission={"status": "hidden", "attempt": None, "modified": None})
    a = w.raw
    st = moodle.submission_status(w.assign_id)
    sub = (st.get("lastattempt") or {}).get("submission") or {}
    fb = st.get("feedback") or {}
    now = int(time.time())
    s = submission_state(a, st, now)
    comments = []
    if s["submission_id"]:
        with soft(errors, f"комментарии к ответу {w.assign_id}"):
            comments = comment_rows(moodle.comments(w.cmid, s["submission_id"]),
                                    moodle.me()["userid"])
    acc = accepts(a)
    return dict(d, due=moment(s["due"]), opens=moment(s["opens"]), closed=s["closed"],
                locked=s["locked"], canedit=s["canedit"], team=s["team"], graded=s["graded"],
                accepts=acc, accepts_line=accepts_line(acc),
                intro=plain(a.get("intro"), 20000),
                attachments=[{"name": f.get("filename"), "url": f.get("fileurl")}
                             for f in a.get("introattachments") or []],
                submission={"status": s["status"], "attempt": sub.get("attemptnumber"),
                            "modified": moment(sub.get("timemodified"))},
                grade=s["grade"],
                grade_text=fb.get("gradefordisplay") if s["grade"] is not None else None,
                feedback=s["feedback"],
                comments=[{"author": c["author"], "time": moment(c["time"], now),
                           "text": c["text"]} for c in comments])


def flow_line(d):
    if not d["flow"]:
        return "Сдача: не задана (FLOW в config.env, `study courses --setup`)"
    line = f"Сдача: {d['flow']} → скилл {d['skill']}"
    x = d["local"]
    if x is None:
        return line
    if not x["exists"]:
        return f"{line}; {x['path']} — нет"
    return f"{line}; {x['path']} — " + (", ".join(x["files"]) if x["files"] else "файлов сдачи нет")


def state_line(d):
    s = d["submission"]
    state = SUBMISSION.get(s["status"], s["status"])
    if not d.get("available", True):
        return state + (f" · {d['reason']}" if d.get("reason") else "")
    if s["attempt"]:
        state += f" · попытка {s['attempt']}"
    if d["grade"] is not None:
        state += f" · балл {d['grade']}" + (f" ({d['grade_text']})" if d["grade_text"] else "")
    if s["modified"] and s["status"] != "new":
        state += f" · изменён {s['modified']['full']}"
    if d["opens"] and s["status"] in PENDING:
        state += f" · откроется {d['opens']['full']}"
    elif d["closed"]:
        state += " · заблокировано" if d["locked"] else " · приём закрыт"
    return state


def render(d):
    due, state = d["due"], state_line(d)
    head = " · ".join(x for x in [d["short"], d["course"]["code"] or d["course"]["title"],
                                  f"id {d['assign_id']}" if d["assign_id"] else None,
                                  f"cmid {d['cmid']}"] if x)
    out = [head, f"Срок: {due['full']} ({due['left']})" if due else "Срок: —",
           "Принимает: " + d["accepts_line"], "Состояние: " + state]
    if d["feedback"]:
        out.append("Отзыв: " + d["feedback"])
    for c in d["comments"]:
        out.append("Комментарий · {} · {}: {}".format(c["author"], c["time"]["full"], c["text"]))
    out.append(flow_line(d))
    if d["stash"]:
        out.append("В stash (возможно по теме): " + ", ".join(d["stash"]))
    for f in d["attachments"]:
        out.append(f"Вложение задания: {f['name']} — {f['url']}")
    if d["warnings"]:
        out.append(failures(d["warnings"]))
    return "\n".join(out) + "\n\n" + (d["intro"] or "(текста задания нет)")
