"""Сводка по ТУИС: сбор данных в структуру и рендер.

Данные и рендер разделены: `--json` отдаёт ровно то, что видит рендер, без второго обхода API.
"""
import json
import re
import time

from . import hosting, local
from .config import StudyError
from .fmt import moment, plain, table

# Что считаем новостью в core_course_get_updates_since; остальное (submissions, grades,
# answers) — своя же активность и чужие голоса, то есть шум.
USEFUL = {"contentfiles", "introfiles", "configuration", "contents", "files"}
FILES = {"contentfiles", "files", "contents"}
# Сроки в составе курса: машинные идентификаторы, а не подписи — подпись зависит от языка.
DATE_IDS = {"duedate", "timeclose"}
KINDS = {"assign": "задание", "choice": "выбор темы",
         "workshop": "взаимная проверка", "feedback": "опрос"}
SUBMISSION = {"submitted": "сдано", "draft": "черновик", "reopened": "переоткрыто"}


class Errors:
    """Мягкие ошибки: копятся, не роняют сводку, но и не теряются."""

    def __init__(self, strict=False):
        self.items = []
        self.strict = strict

    def soft(self, where):
        return _Soft(self, where)

    def add(self, err, where=None):
        item = err.as_dict()
        if where:
            item["where"] = where
        self.items.append(item)


class _Soft:
    def __init__(self, errors, where):
        self.errors, self.where = errors, where

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if isinstance(exc, StudyError):
            if self.errors.strict:
                return False
            self.errors.add(exc, self.where)
            return True
        return False


def lab_number(name):
    m = re.search(r"№\s*(\d+)|работе\s+(\d+)", name or "")
    if not m:
        return None
    return (m.group(1) or m.group(2)).zfill(2)


def collect(cfg, moodle, days=None, save=True, strict=False):
    """Всё, что знает ТУИС: дедлайны, тесты, обновления, уведомления, баллы."""
    now = int(time.time())
    days = days or cfg.days()
    errors = Errors(strict)
    state_file = cfg.state_file()
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    since = state.get("last_run")
    known = state.get("assignments", {})

    watch = {c.id: c for c in cfg.courses()}
    events = []
    with errors.soft("календарь"):
        events = moodle.calendar(now - 7 * 86400, now + 120 * 86400)
    active = {(e.get("course") or {}).get("id") for e in events} - {None}

    courses = [c for c in moodle.courses() if c["id"] in (watch or active)]
    cmap = {c["id"]: (watch[c["id"]].title if c["id"] in watch else c["fullname"])
            for c in courses}
    codes = {c["id"]: (watch[c["id"]].code if c["id"] in watch else None) for c in courses}

    def course_of(cid):
        return {"id": cid, "code": codes.get(cid), "title": cmap.get(cid, "")}

    # --- задания
    assigns, soon, overdue, new_assigns, moved = {}, [], [], [], []
    course_list, _ = moodle.assignments()
    for c in course_list:
        if c["id"] not in cmap:
            continue
        for a in c["assignments"]:
            item = {"kind": "assign", "source": "assign_api", "assign_id": a["id"],
                    "cmid": a["cmid"], "course": course_of(c["id"]), "name": a["name"],
                    "due": moment(a.get("duedate"), now), "submission": None,
                    "intro": plain(a.get("intro")), "lab": lab_number(a["name"])}
            assigns[str(a["id"])] = item
            due = a.get("duedate") or 0
            prev = known.get(str(a["id"]))
            if since and prev is None:
                new_assigns.append(item)
            elif prev is not None and due and prev != due:
                moved.append({**item, "was": moment(prev, now)})
            if not due:
                continue
            if now <= due <= now + days * 86400:
                soon.append(item)
            elif due < now <= due + 30 * 86400:
                overdue.append(item)

    for item in sorted(soon + overdue, key=lambda x: x["due"]["ts"]):
        with errors.soft(f"статус задания {item['assign_id']}"):
            st = moodle.submission_status(item["assign_id"])
            sub = (st.get("lastattempt") or {}).get("submission") or {}
            item["submission"] = sub.get("status") or "new"
            item["grade"] = ((st.get("feedback") or {}).get("grade") or {}).get("grade")

    # --- элементы курса со сроками: ловят задания, скрытые ограничением доступа
    contents_cache = {}

    def contents(cid):
        if cid not in contents_cache:
            contents_cache[cid] = []
            with errors.soft(f"состав курса {cid}"):
                contents_cache[cid] = moodle.contents(cid)
        return contents_cache[cid]

    seen = {a["cmid"] for a in assigns.values()}
    for c in courses:
        for sec in contents(c["id"]):
            for m in sec.get("modules", []):
                if m["id"] in seen or m["modname"] not in KINDS:
                    continue
                for d in m.get("dates") or []:
                    if d.get("dataid") not in DATE_IDS:
                        continue
                    ts = d.get("timestamp") or 0
                    if now <= ts <= now + days * 86400:
                        soon.append({"kind": "activity", "source": "course_contents",
                                     "modname": m["modname"], "cmid": m["id"],
                                     "course": course_of(c["id"]), "name": m["name"],
                                     "due": moment(ts, now), "submission": None,
                                     "intro": "", "lab": lab_number(m["name"])})

    # --- выбор темы доклада: сам срок ничего не говорит, важно, выбрана ли тема
    picks = [a for a in soon if a.get("modname") == "choice"]
    if picks:
        by_cmid = {}
        with errors.soft("темы докладов"):
            by_cmid = {c["coursemodule"]: c["id"]
                       for c in moodle.choices({a["course"]["id"] for a in picks})}
        for a in picks:
            cid = by_cmid.get(a["cmid"])
            if not cid:
                continue
            with errors.soft(f"варианты выбора {cid}"):
                opts = moodle.choice_options(cid)
                mine = [o["text"] for o in opts if o.get("checked")]
                a["choice"] = {"chosen": mine[0] if mine else None, "options": len(opts)}
                a["submission"] = "submitted" if mine else "new"

    # --- тесты
    quizzes = []
    with errors.soft("тесты"):
        for q in moodle.quizzes([c["id"] for c in courses]):
            close = q.get("timeclose") or 0
            if not close or close < now:
                continue
            used = None
            with errors.soft(f"попытки теста {q['id']}"):
                used = len(moodle.quiz_attempts(q["id"]))
            quizzes.append({"kind": "quiz", "source": "quiz", "quiz_id": q["id"],
                            "course": course_of(q["course"]), "name": q["name"],
                            "due": moment(close, now), "attempts_used": used,
                            "attempts_max": q.get("attempts") or None,
                            "timelimit_min": (q.get("timelimit") or 0) // 60 or None})
    soon += [q for q in quizzes if q["due"]["ts"] <= now + days * 86400]
    ahead = [q for q in quizzes if q["due"]["ts"] > now + days * 86400]

    # --- обновления в курсах
    updates = []
    if since:
        for c in courses:
            changed = []
            with errors.soft(f"обновления курса {c['id']}"):
                changed = [u for u in moodle.updates_since(c["id"], since) if u.get("updates")]
            if not changed:
                continue
            names = {m["id"]: (m["name"], m["modname"], sec["name"], m.get("contents") or [])
                     for sec in contents(c["id"]) for m in sec.get("modules", [])}
            for u in changed:
                kinds = {x["name"] for x in u["updates"]} & USEFUL
                if not kinds:
                    continue
                name, modname, section, items = names.get(
                    u["id"], (f"(модуль {u['id']})", "", "", []))
                # имена файлов — чтобы сводка говорила «появился 002-dns.pdf», а не «новые файлы»
                new_files = [i["filename"] for i in items
                             if i.get("type") == "file" and i.get("filesize")
                             and (i.get("timemodified") or 0) > since]
                updates.append({"course": course_of(c["id"]), "section": section,
                                "item": name, "modname": modname, "files": new_files,
                                "what": "новые файлы" if kinds & FILES else "изменены настройки"})

    # --- уведомления, баллы, курсы вне списка
    notifications = []
    with errors.soft("уведомления"):
        for m in moodle.notifications():
            subject = plain(m.get("subject"), 120)
            if "Новый вход" not in subject:
                notifications.append({"at": moment(m["timecreated"], now), "subject": subject})
    notifications.sort(key=lambda n: -n["at"]["ts"])

    grades = []
    for c in courses:
        with errors.soft(f"оценки, курс {c['id']}"):
            for t in moodle.grades(c["id"]):
                got = [i for i in t.get("gradeitems", [])
                       if i.get("graderaw") is not None and i.get("itemtype") != "course"]
                total = next((i for i in t.get("gradeitems", [])
                              if i.get("itemtype") == "course"), None)
                if got:
                    grades.append({"course": course_of(c["id"]),
                                   "items": [{"name": i["itemname"], "raw": i["graderaw"],
                                              "max": i["grademax"]} for i in got],
                                   "total": {"raw": total.get("graderaw"),
                                             "max": total.get("grademax")} if total else None})

    outside = {}
    for e in events:
        c = e.get("course") or {}
        if c.get("id") and c["id"] not in cmap and now <= e.get("timesort", 0) <= now + days * 86400:
            key = (c["id"], c.get("fullname") or c.get("shortname"))
            outside.setdefault(key, []).append(e)

    deadlines = sorted(soon, key=lambda x: x["due"]["ts"])
    data = {
        "schema": 1, "now": moment(now, now), "days": days,
        "first_run": not since, "since": moment(since, now) if since else None,
        "courses": [course_of(c["id"]) for c in courses],
        "deadlines": deadlines,
        "overdue": sorted([a for a in overdue if a["submission"] in ("new", None)],
                          key=lambda x: x["due"]["ts"]),
        "not_started": [a for a in deadlines
                        if a["source"] == "assign_api" and a["submission"] == "new"],
        "quizzes_ahead": sorted(ahead, key=lambda x: x["due"]["ts"]),
        "updates": updates, "new_assignments": new_assigns, "moved": moved,
        "notifications": notifications, "grades": grades,
        "outside": [{"course": {"id": cid, "title": name},
                     "count": len(evs),
                     "nearest": {"name": (min(evs, key=lambda x: x["timesort"])["name"] or "")[:60],
                                 "at": moment(min(e["timesort"] for e in evs), now)}}
                    for (cid, name), evs in outside.items()],
        "errors": errors.items,
    }

    if save:
        state_file.write_text(json.dumps({
            "last_run": now,
            "assignments": {i: (a["due"]["ts"] if a["due"] else 0) for i, a in assigns.items()},
            "courses": {str(c["id"]): c["fullname"] for c in courses},
        }, ensure_ascii=False, indent=1))
    return data


def render(d, with_errors=True):
    """Markdown-сводка: тот же вид, что был у tuis-digest."""
    out = ["# Сводка по ТУИС на " + time.strftime("%d.%m.%Y")]
    if d["first_run"]:
        out.append("\nПервый запуск: снимок состояния сохранён, обновления начнут "
                   "отслеживаться со следующего раза.")

    out.append("\n## Ближайшие дедлайны (%d дней)" % d["days"])
    if d["deadlines"]:
        for a in d["deadlines"]:
            due = a["due"]
            if a["kind"] == "quiz":
                out.append("- **{}** (тест) — до {} (осталось {}) — попыток использовано {} из {} · {}"
                           .format(a["name"], due["text"], due["left"],
                                   a["attempts_used"] if a["attempts_used"] is not None else "?",
                                   a["attempts_max"] or "∞", a["course"]["title"]))
            elif a["source"] == "course_contents":
                pick = a.get("choice")
                mark = ""
                if pick:
                    mark = (" — выбрано: «%s»" % pick["chosen"] if pick["chosen"]
                            else " — ТЕМА НЕ ВЫБРАНА, вариантов: %d" % pick["options"])
                out.append("- **{}** ({}) — до {} (осталось {}){} · {}".format(
                    a["name"], KINDS.get(a["modname"], a["modname"]), due["text"],
                    due["left"], mark, a["course"]["title"]))
            else:
                out.append("- **{}** — до {} (осталось {}) — {} · {}".format(
                    a["name"], due["text"], due["left"],
                    SUBMISSION.get(a["submission"], "не сдано"), a["course"]["title"]))
    else:
        out.append("- ничего в ближайшие %d дней" % d["days"])

    if d["overdue"]:
        out.append("\n## Просрочено и не сдано")
        for a in d["overdue"]:
            out.append("- **{}** — срок был {} · {}".format(
                a["name"], a["due"]["text"], a["course"]["title"]))

    out.append("\n## Обновления в курсах")
    if d["updates"]:
        for u in d["updates"]:
            files = u.get("files") or []
            out.append("- {} → {} · {} ({}): {}".format(
                u["course"]["title"], u["section"] or "—", u["item"], u["modname"],
                ", ".join(files) if files else u["what"]))
        codes = sorted({u["course"]["code"] for u in d["updates"]
                        if u.get("files") and u["course"]["code"]})
        if codes:
            out.append("  Забрать в stash: " + "; ".join("study files %s --pull" % c for c in codes))
    else:
        out.append("- нет изменений с прошлого запуска" if not d["first_run"] else "- (первый запуск)")

    if d["new_assignments"]:
        out.append("\n## Новые задания")
        for a in d["new_assignments"]:
            out.append("- **{}** — до {} · {}".format(
                a["name"], a["due"]["text"] if a["due"] else "—", a["course"]["title"]))

    if d["moved"]:
        out.append("\n## Сроки изменились")
        for a in d["moved"]:
            out.append("- **{}**: было {} → стало {} · {}".format(
                a["name"], a["was"]["text"] if a["was"] else "—",
                a["due"]["text"] if a["due"] else "—", a["course"]["title"]))

    if d["quizzes_ahead"]:
        out.append("\n## Тесты и экзамены впереди")
        for q in d["quizzes_ahead"]:
            lim = ", лимит %d мин" % q["timelimit_min"] if q["timelimit_min"] else ""
            out.append("- **{}** — {} · попыток: {}{} · {}".format(
                q["name"], q["due"]["full"], q["attempts_max"] or "без ограничений",
                lim, q["course"]["title"]))

    if d["outside"]:
        out.append("\n## Дедлайны вне списка курсов")
        out.append("Эти курсы не перечислены в `config.env` — проверь, актуальны ли они:")
        for o in d["outside"]:
            out.append("- **{}** (id {}): ближайшее — {} до {}".format(
                o["course"]["title"], o["course"]["id"], o["nearest"]["name"],
                o["nearest"]["at"]["text"]))

    if d["grades"]:
        out.append("\n## Баллы")
        for g in d["grades"]:
            total = (" · итого %s из %s" % (g["total"]["raw"], g["total"]["max"])
                     if g["total"] and g["total"]["raw"] is not None else "")
            out.append("- {}: {}{}".format(
                g["course"]["title"],
                ", ".join("%s — %s из %s" % (i["name"], i["raw"], i["max"]) for i in g["items"]),
                total))

    if d["notifications"]:
        out.append("\n## Непрочитанные уведомления ТУИС")
        for n in d["notifications"][:5]:
            out.append("- {} · {}".format(n["at"]["text"], n["subject"]))

    if d["not_started"]:
        out.append("\n## Ещё не начато")
        for a in d["not_started"]:
            out.append("\n**{}** · {} · до {} (осталось {})".format(
                a["name"], a["course"]["title"], a["due"]["text"], a["due"]["left"]))
            if a["intro"]:
                out.append("  " + a["intro"])
            code = ", каталог: " + a["course"]["code"] if a["course"]["code"] else ""
            out.append("  id задания: {}, cmid: {}{}".format(a["assign_id"], a["cmid"], code))

    if with_errors and d["errors"]:
        out.append("\n## Не удалось получить")
        for e in d["errors"]:
            out.append("- {}: {}".format(e.get("where") or e["source"], e["message"]))

    return "\n".join(out)


def state(cfg, moodle, days=None, with_tuis=True, save=True, strict=False):
    """Сводка ТУИС плюс состояние локальных репозиториев — всё одним объектом."""
    errors = Errors(strict)
    tuis = None
    if with_tuis:
        tuis = collect(cfg, moodle, days=days, save=save, strict=strict)

    by_lab = {}
    for a in (tuis or {}).get("deadlines", []):
        if a.get("lab") and a["course"].get("code"):
            by_lab[(a["course"]["code"], a["lab"])] = a

    courses = []
    for course in cfg.courses():
        if not course.code:
            continue
        repo = local.course_repo(course.code)
        item = {**course.as_dict(), "dir": str(course.dir), "repo": None,
                "releases": {}, "unreleased_tags": [], "labs": []}
        if repo:
            item["repo"] = local.repo_state(repo)
            published = {}
            for name, client in hosting.both(cfg, path=repo).items():
                if isinstance(client, StudyError):
                    errors.add(client, f"{name}, курс {course.code}")
                    item["releases"][name] = {"ok": False, "latest": None}
                    continue
                with errors.soft(f"{name}, курс {course.code}"):
                    rels = client.releases()
                    published[name] = {r["tag"] for r in rels}
                    item["releases"][name] = {"ok": True, "latest": rels[0] if rels else None,
                                              "tags": [r["tag"] for r in rels]}
            for name, tags in published.items():
                missing = [t for t in item["repo"]["tags"] if t not in tags]
                if missing:
                    item["unreleased_tags"].append({"hosting": name, "tags": missing})
            for lab in local.labs(repo, course.code):
                found = by_lab.get((course.code, lab["num"]))
                lab["tuis"] = ({"assign_id": found["assign_id"], "name": found["name"],
                                "due": found["due"], "submission": found["submission"],
                                "matched_by": "number"} if found else None)
                lab["ready"] = {
                    "report": lab["report"]["built"],
                    "presentation": lab["presentation"]["built"],
                    "videos": lab["videos"]["filled"] == lab["videos"]["total"],
                    "submitted": bool(found and found["submission"] == "submitted"),
                }
                item["labs"].append(lab)
        courses.append(item)

    return {"schema": 1, "now": moment(int(time.time())), "days": days or cfg.days(),
            "tuis": tuis, "courses": courses,
            "errors": errors.items + ((tuis or {}).get("errors") or [])}


def render_state(d):
    """Состояние репозиториев таблицей; сводка ТУИС — как обычно."""
    out = []
    if d.get("tuis"):
        out.append(render(d["tuis"], with_errors=False))
    out.append("\n# Состояние работ")
    for c in d["courses"]:
        out.append("\n**{}** · {}".format(c["title"], c["code"]))
        if not c["repo"]:
            out.append("  репозитория ещё нет")
            continue
        repo = c["repo"]
        line = "  ветка {}".format(repo["branch"])
        if repo["dirty"]:
            line += ", незакоммичено: %d" % len(repo["dirty"])
        # Релиз — тег всего репозитория, а не лабы, поэтому он строкой курса, а не в таблице.
        line += ", последний тег: " + (repo["last_tag"] or "нет")
        out.append(line)
        for u in c["unreleased_tags"]:
            out.append("  нет релиза на {}: {}".format(u["hosting"], ", ".join(u["tags"])))
        rows = []
        for lab in c["labs"]:
            if not (lab["report"]["built"] or lab["presentation"]["built"] or lab["tuis"]):
                continue
            rows.append([lab["num"],
                         lab["tuis"]["due"]["text"] if lab["tuis"] else "—",
                         "собран" if lab["report"]["built"] else "нет",
                         "собрана" if lab["presentation"]["built"] else "нет",
                         "%d из %d" % (lab["videos"]["filled"], lab["videos"]["total"]),
                         (SUBMISSION.get(lab["tuis"]["submission"], "не сдано")
                          if lab["tuis"] else "—")])
        if rows:
            out.append("\n".join("  " + line for line in table(
                rows, ["лаба", "срок", "отчёт", "презентация", "видео", "ТУИС"]
            ).splitlines()))
    if d["errors"]:
        out.append("\n# Не удалось получить")
        for e in d["errors"]:
            out.append("- {}: {}".format(e.get("where") or e["source"], e["message"]))
    return "\n".join(out)
