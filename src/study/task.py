"""Карточка задания: текст, срок, состояние ответа, что принимает, что есть на диске.

Ничего не пишет и не запоминает: ТУИС — единственный источник, карточка собирается
по запросу. С неё агент разбирает задание и отвечает на вопросы о нём.
"""
import re

from . import local
from .config import ROOT, StudyError
from .fmt import moment, parse_name, plain, short_name
from .moodle import accepts, accepts_line, feedback_text

SUBMISSION = {"new": "не сдано", "draft": "черновик", "reopened": "на доработку",
              "submitted": "сдано"}


def find(assigns, what, label):
    """Задание по номеру лабы (NN, как в labs/labNN) или по id из `study assigns`."""
    m = re.fullmatch(r"(?:lab)?(\d{1,2})", what.strip().lower())
    if m:
        num = m.group(1).zfill(2)
        for a in assigns:
            p = parse_name(a["name"])
            if p and p["work"] == "lab" and p["num"].zfill(2) == num:
                return a
    if what.strip().isdigit():
        for a in assigns:
            if a["id"] == int(what):
                return a
    raise StudyError("moodle", f"в курсе {label} нет задания «{what}»: "
                               f"study assigns --course {label}")


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
    course_list, _ = moodle.assignments([course.id])
    c = next((x for x in course_list if x["id"] == course.id), None)
    label = course.code or str(course.id)
    a = find(c["assignments"] if c else [], what, label)
    st = moodle.submission_status(a["id"])
    sub = (st.get("lastattempt") or {}).get("submission") or {}
    fb = st.get("feedback") or {}
    p = parse_name(a["name"])
    num = p["num"].zfill(2) if p and p["work"] == "lab" else None
    flow = local.flow_of(cfg, course.code) if course.code else None
    acc = accepts(a)
    return {"course": {"id": course.id, "code": course.code,
                       "title": c["fullname"] if c else course.title},
            "assign_id": a["id"], "cmid": a["cmid"], "name": a["name"],
            "short": short_name(a["name"]), "num": num, "due": moment(a.get("duedate")),
            "accepts": acc, "accepts_line": accepts_line(acc),
            "intro": plain(a.get("intro"), 20000),
            "attachments": [{"name": f.get("filename"), "url": f.get("fileurl")}
                            for f in a.get("introattachments") or []],
            "submission": {"status": sub.get("status") or "new",
                           "attempt": sub.get("attemptnumber"),
                           "modified": moment(sub.get("timemodified"))},
            "grade": (fb.get("grade") or {}).get("grade"),
            "grade_text": fb.get("gradefordisplay"),
            "feedback": feedback_text(st), "flow": flow,
            "local": on_disk(cfg, course.code, num, flow), "stash": in_stash(course.code, num)}


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


def render(d):
    s, due = d["submission"], d["due"]
    state = SUBMISSION.get(s["status"], s["status"])
    if s["attempt"]:
        state += f" · попытка {s['attempt']}"
    if d["grade"] is not None:
        state += f" · балл {d['grade']}" + (f" ({d['grade_text']})" if d["grade_text"] else "")
    if s["modified"] and s["status"] != "new":   # у несданного Moodle подставляет срок
        state += f" · изменён {s['modified']['full']}"
    head = (f"{d['short']} · {d['course']['code'] or d['course']['title']} · id {d['assign_id']}"
            f" · cmid {d['cmid']}")
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
