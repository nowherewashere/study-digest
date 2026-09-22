"""Карточка задания: текст, срок, состояние ответа, что принимает, что есть на диске.

Ничего не пишет и не запоминает: ТУИС — единственный источник, карточка собирается
по запросу. С неё агент разбирает задание и отвечает на вопросы о нём.
"""
import re
import time

from . import local
from .assigns import SUBMISSION, Registry
from .config import ROOT, soft
from .fmt import moment, plain
from .moodle import PENDING, accepts, accepts_line, submission_state


def on_disk(cfg, code, num, flow):
    """Что есть по лабе на диске: у release — лаба репозитория со всей готовностью,
    у file — каталог <код>/labNN и собранные PDF."""
    if not code or not num:
        return None
    if flow == "release":
        repo = local.course_repo(code)
        lab = next((x for x in local.labs(repo, code) if x["num"] == num), None) if repo else None
        return {"kind": "release", **lab} if lab else None
    d = ROOT / code / f"lab{num}"
    return {"kind": "file", "path": str(d), "exists": d.is_dir(),
            "pdfs": [str(p) for p in sorted(d.glob("**/_output/*.pdf"))] if d.is_dir() else []}


def in_stash(code, num):
    """Файлы stash/, в имени которых есть номер лабы — эвристика, подписана как «возможно».
    Номер ищется в имени без расширения и не внутри кодов вроде 02.03.02."""
    if not code or not num:
        return []
    stash = ROOT / code / "stash"
    pat = re.compile(rf"(?<![\d.])0*{int(num)}(?![\d.])")   # 001-dns.pdf тоже про лабу 1
    return sorted(p.name for p in stash.rglob("*") if p.is_file() and pat.search(p.stem)) \
        if stash.is_dir() else []


def build(cfg, moodle, course, what):
    """Карточка задания. Задание, которого mod_assign не отдал (ограничение доступа), знает
    только то, что видно в составе курса: статус ответа по нему не спросить."""
    errors = []
    reg = Registry(moodle, [course.id], soft=lambda where: soft(errors, where))
    w = reg.find(course, what)
    flow = local.flow_of(cfg, course.code) if course.code else None
    d = {"course": {"id": course.id, "code": course.code,
                    "title": reg.title(course.id) or course.title},
         "assign_id": w.assign_id, "cmid": w.cmid, "name": w.name, "short": w.short,
         "num": w.lab, "source": w.source, "available": w.available, "reason": w.reason,
         "section": w.section, "flow": flow,
         "local": on_disk(cfg, course.code, w.lab, flow), "stash": in_stash(course.code, w.lab),
         "warnings": errors}
    if not w.available:
        return dict(d, due=moment(w.due), opens=moment(w.opens), closed=True, locked=False,
                    canedit=False, team=False, graded=False, accepts=None, accepts_line="—",
                    intro=w.intro, attachments=[], grade=None, grade_text=None, feedback=None,
                    submission={"status": "hidden", "attempt": None, "modified": None})
    a = w.raw
    st = moodle.submission_status(w.assign_id)
    sub = (st.get("lastattempt") or {}).get("submission") or {}
    fb = st.get("feedback") or {}
    s = submission_state(a, st, int(time.time()))
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
                feedback=s["feedback"])


def disk_line(d):
    x = d["local"]
    if x is None:
        return None
    if x["kind"] == "file":
        return "Локально (file): {} — {}".format(
            x["path"], ("есть, PDF: " + ", ".join(x["pdfs"]) if x["pdfs"] else "есть, PDF нет")
            if x["exists"] else "нет")
    yes = {True: "есть", False: "нет"}
    return ("Локально (release): {} — отчёт pdf {}, презентация {}, видео {}/{}, "
            "заготовка ответа {}".format(x["path"], yes[x["report"]["built"]],
                                         yes[x["presentation"]["built"]], x["videos"]["filled"],
                                         x["videos"]["total"], yes[x["answer_draft"]])
            + ("; вложения: " + ", ".join(x["attachments"]) if x["attachments"] else ""))


def state_line(d):
    s = d["submission"]
    state = SUBMISSION.get(s["status"], s["status"])
    if not d.get("available", True):
        # причина из ТУИС («Вы принадлежите к группе …») — единственное, что тут известно
        return state + (f" · {d['reason']}" if d.get("reason") else "")
    if s["attempt"]:
        state += f" · попытка {s['attempt']}"
    if d["grade"] is not None:
        state += f" · балл {d['grade']}" + (f" ({d['grade_text']})" if d["grade_text"] else "")
    if s["modified"] and s["status"] != "new":   # у несданного Moodle подставляет срок
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
    if disk_line(d):
        out.append(disk_line(d))
    if d["stash"]:
        out.append("В stash (возможно по теме): " + ", ".join(d["stash"]))
    for f in d["attachments"]:
        out.append(f"Вложение задания: {f['name']} — {f['url']}")
    return "\n".join(out) + "\n\n" + (d["intro"] or "(текста задания нет)")
