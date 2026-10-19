import json
import pathlib
import sys
import time

from kit.cli import add, confirm_gate, main as run, parser, read_text, table
from kit.config import ToolError, soft

from . import agent, assigns, courses, digest, files, setup, task, update
from .config import Config, Course
from .fmt import failures, moment, plain
from .moodle import (SUBMISSION, Moodle, accepts, accepts_line, check_state, check_submission,
                     mb, submission_state)


def course_of(cfg, value):
    codes = cfg.codes()
    if str(value).isdigit():
        return Course(int(value), codes.get(int(value)))
    cid = next((i for i, c in codes.items() if c == value), None)
    if cid is None:
        raise ToolError("config", f"нет курса «{value}» (config.env: CODE <id> {value})")
    return Course(cid, value)


def kv(pairs):
    out = {}
    for item in pairs:
        key, _, value = item.partition("=")
        if key in out:
            out[key] = (out[key] if isinstance(out[key], list) else [out[key]]) + [value]
        else:
            out[key] = value
    return out


def cmd_me(cfg, args):
    d = Moodle(cfg).me()
    return d, "{} | userid {} | {} {} | функций: {}".format(
        d["fullname"], d["userid"], d["sitename"], d["release"], len(d["functions"]))


def cmd_courses(cfg, args):
    rows = courses.rows(cfg, Moodle(cfg), include_hidden=args.all)
    if not args.setup:
        return rows, courses.render(rows)
    out = courses.setup(cfg, rows)
    return out, "config.env обновлён: COURSE_IGNORE ({}), CODE ({})".format(
        len(out["ignore"]), len(out["code"])) + (
        "; заготовки NOTES.md: " + ", ".join(out["notes"]) if out["notes"] else "")


def cmd_functions(cfg, args):
    names = Moodle(cfg).functions()
    if args.filter:
        names = [n for n in names if args.filter in n]
        return names, "\n".join(names)
    return names, f"всего функций: {len(names)}"


def cmd_call(cfg, args):
    out = Moodle(cfg).call(args.function, **kv(args.params))
    return out, json.dumps(out, ensure_ascii=False, indent=1)


def assign_line(w, due):
    head = f"  id={w.assign_id} cmid={w.cmid}" if w.available else f"  cmid={w.cmid}"
    line = "{} до {}  {}".format(head, due["text"] if due else "—", w.name)
    if w.available:
        return line
    return line + ("  — доступ закрыт: " + plain(w.reason, 60) if w.reason
                   else "  — доступ закрыт")


def cmd_assigns(cfg, args):
    course = course_of(cfg, args.course) if args.course else None
    errors = []
    reg = assigns.Registry(Moodle(cfg), [course.id] if course else None,
                           soft=lambda where: soft(errors, where))
    rows, lines = [], []
    for c in [course] if course else reg.courses(cfg.codes()):
        works = reg.works(c, contents=bool(course))
        title = reg.title(c.id) or c.title or c.code or str(c.id)
        if not works:
            continue
        lines.append(f"\n[{c.id}] {title}")
        for w in works:
            due = moment(w.due)
            rows.append({"course": {"id": c.id, "title": title},
                         "assign_id": w.assign_id, "cmid": w.cmid, "name": w.name, "due": due,
                         "source": w.source, "available": w.available, "reason": w.reason,
                         "intro": plain(w.intro, 2000)})
            lines.append(assign_line(w, due))
    if course and not rows:
        lines.append(f"в курсе {course.code or course.id} заданий нет: "
                     "ТУИС по этому курсу ничего не принимает")
    if reg.warnings and not course:
        lines.append(f"\nСкрыто ограничением доступа: {len(reg.warnings)} "
                     "(видно в `study assigns --course <код>` и в сводке)")
    if errors:
        lines.append("\n" + failures(errors))
    return ({"assignments": rows, "warnings": reg.warnings, "errors": errors},
            "\n".join(lines).lstrip())


def cmd_calendar(cfg, args):
    now = int(time.time())
    events = Moodle(cfg).calendar(now, now + args.days * 86400)
    rows = [{"at": moment(e["timesort"], now), "name": e.get("name"),
             "course": (e.get("course") or {}).get("shortname"),
             "course_id": (e.get("course") or {}).get("id")} for e in events]
    return rows, table([[r["at"]["text"], (r["name"] or "")[:60], r["course"] or ""]
                        for r in rows]) or "нет событий"


def named(cfg, m, value):
    c = course_of(cfg, value)
    return next((t for t in cfg.track(m.courses()) if t.id == c.id), c)


def cmd_grades(cfg, args):
    m = Moodle(cfg)
    tracked = [named(cfg, m, args.course)] if args.course else cfg.track(m.courses())
    rows, lines = [], []
    for c in tracked:
        try:
            grades = m.grades(c.id)
        except ToolError as e:
            lines.append(f"\n{c.title or c.id}: {e.message}")
            continue
        for t in grades:
            items = [{"name": i.get("itemname"), "raw": i.get("graderaw"),
                      "max": i.get("grademax"), "type": i.get("itemtype")}
                     for i in t.get("gradeitems", []) if i.get("graderaw") is not None]
            title = c.title or t.get("courseshortname") or str(c.id)
            rows.append({"course": {"id": c.id, "title": title}, "items": items})
            lines.append("\n" + title)
            body = [["  " + (i["name"] or "")[:50], f"{i['raw']} из {i['max']}"]
                    for i in items if i["type"] != "course"]
            total = next((i for i in items if i["type"] == "course"), None)
            if total:
                body.append(["  ИТОГО", f"{total['raw']} из {total['max']}"])
            lines.append(table(body) if body else "  оценок пока нет")
    return rows, "\n".join(lines).lstrip()


def cmd_files(cfg, args):
    m = Moodle(cfg)
    progress = files.Progress()
    if args.course:
        course = named(cfg, m, args.course)
        d = files.listing(cfg, m, course, everything=args.all or files.empty(course))
        if args.pull:
            d = files.pull(m, d, force=args.force, progress=progress)
            progress.clear()
        return d, files.render(d, pulled=args.pull)
    out = list(files.walk(cfg, m, do_pull=args.pull, everything=args.all, force=args.force,
                          progress=progress))
    progress.clear()
    lines = [files.summary(d, pulled=args.pull) for d in out]
    return out, "\n".join(lines) or "в config.env нет папок курсов (строк CODE)"


def cmd_status(cfg, args):
    d = Moodle(cfg).submission_status(args.assign_id)
    s = (d.get("lastattempt") or {}).get("submission") or {}
    out = {"status": s.get("status"), "attempt": s.get("attemptnumber"),
           "modified": moment(s.get("timemodified"))}
    return out, "статус: {} | попытка: {} | изменён: {}".format(
        out["status"] or "нет ответа", out["attempt"],
        out["modified"]["full"] if out["modified"] else "—")


def cmd_upload(cfg, args):
    paths = [pathlib.Path(f) for f in args.files]
    itemid = Moodle(cfg).upload(paths, args.itemid)
    out = {"itemid": itemid, "files": [p.name for p in paths]}
    return out, "itemid: {} · загружено: {}".format(itemid, ", ".join(out["files"]))


def make_plan(args, text, attach, found=None, state=None, acc=None, problems=()):
    return {"assign_id": args.assign_id, "name": found["name"] if found else None,
            "due": moment(state["due"]) if state else None, "accepts": acc, "state": state,
            "drafts": bool(found and found.get("submissiondrafts") == 1),
            "statement": bool(found and found.get("requiresubmissionstatement") == 1),
            "text_file": args.text, "text_chars": len(text or ""),
            "attach": [{"name": p.name, "bytes": p.stat().st_size if p.is_file() else None}
                       for p in attach],
            "files_itemid": args.files, "problems": list(problems),
            "confirmed": bool(args.confirm)}


def cmd_submit(cfg, args):
    m = Moodle(cfg)
    text = read_text(args.text)
    attach = [pathlib.Path(p) for p in args.attach or []]
    course_list, _ = m.assignments()
    found = next((a for c in course_list for a in c["assignments"]
                  if a["id"] == args.assign_id), None)
    if found is None:
        problem = (f"задание id {args.assign_id} не найдено в mod_assign: проверь номер "
                   f"(`study task <код> {args.assign_id}`) — это может быть cmid из сводки "
                   "или задание, закрытое ограничением доступа")
        return (make_plan(args, text, attach, problems=[problem]),
                "Нельзя отправить:\n  – " + problem, 1)
    acc = accepts(found)
    state = submission_state(found, m.submission_status(args.assign_id), int(time.time()))
    problems = check_submission(acc, text, attach, args.files) + check_state(
        state, lambda ts: moment(ts)["full"])
    plan = make_plan(args, text, attach, found, state, acc, problems)
    drafts, statement = plan["drafts"], plan["statement"]
    if attach:
        vl = ", ".join("{} ({})".format(a["name"], mb(a["bytes"]) if a["bytes"] is not None
                                        else "нет") for a in plan["attach"])
        vl += f" + itemid {args.files}" if args.files else ""
    else:
        vl = (f"itemid {args.files} (состав по itemid не виден, не проверяется)" if args.files
              else "нет")
    lines = ["Что будет отправлено:",
             "  задание: {} (id {})".format(plan["name"] or "?", args.assign_id),
             "  срок: {}".format(plan["due"]["full"] if plan["due"] else "—"),
             "  принимает: " + accepts_line(acc),
             "  состояние: " + SUBMISSION.get(state["status"], state["status"])
             + (" — отправка заменит прежний ответ" if state["status"] == "submitted" else ""),
             "  текст: " + (f"{args.text} ({len(text)} символов), формат Markdown"
                            if text is not None else "нет"),
             "  вложения: " + vl,
             "  после сохранения: " + (("отправка на проверку (submissiondrafts=1)"
                                        + (", с подтверждением авторства" if statement else ""))
                                       if drafts else "сразу сдача (submissiondrafts=0)")]
    if problems:
        lines += ["", "Нельзя отправить:"] + [f"  – {x}" for x in problems]
        return plan, "\n".join(lines), 1
    gate = confirm_gate(plan, lines, args,
                        "Отправка необратима: черновика не останется. Повтори с --confirm.")
    if gate:
        return gate
    itemid = m.upload(attach, args.files or 0) if attach else args.files
    plan["files_itemid"] = itemid
    plan["result"] = m.save_submission(args.assign_id, text, itemid)
    if drafts:
        plan["submitted"] = m.submit_for_grading(args.assign_id, statement)
    return plan, "Отправлено: {} (id {})".format(plan["name"] or "?", args.assign_id)


def cmd_state(cfg, args):
    d = digest.state(cfg, Moodle(cfg), days=args.days, save=not args.no_save, pull=args.pull,
                     since=args.since)
    return d, digest.render(d)


def cmd_task(cfg, args):
    d = task.build(cfg, Moodle(cfg), course_of(cfg, args.course), args.what)
    return d, task.render(d)


def cmd_update(cfg, args):
    d = update.check()
    if d is None:
        return d, "Это не git-клон с upstream: обновлять нечего."
    if args.check:
        lines = update.plan(d) if d["behind"] else [f"Актуально: {d['version']}."]
        return d, "\n".join(lines + update.stale(d))
    if d["behind"] and not args.yes:
        lines = update.plan(d)
        if not sys.stdin.isatty():
            return d, "\n".join([*lines, "", "Повтори с --yes."]), 1
        print("\n".join(lines))
        if not setup.yes(input("Обновить? [y/N] "), "n"):
            return d, "Отменено.", 1
    d = update.apply(d)
    lines = ([f"Обновлено: {d['version']} → {d['now']}"] + [f"  {c}" for c in d["commits"]]
             if d["updated"] else [f"Уже актуально: {d['now']}."])
    lines += [f"Блок агента обновлён: {f}" for f in d["refreshed"]]
    return d, "\n".join(lines)


def cmd_agent(cfg, args):
    rows = [agent.install(o) for o in args.operator] if args.operator \
        else [agent.status(o) for o in agent.OPERATORS]
    return rows, agent.render(rows, installed=bool(args.operator))


SINCE = {"help": "считать прошлым запуском: ГГГГ-ММ-ДД, N дней назад, never, all"}


def tuis_parsers(sub):
    s = add(sub, "state",
            "готовая ежедневная сводка: сроки, баллы, новое в курсах, состояние работ", cmd_state)
    s.add_argument("--days", type=int, help="окно дедлайнов, дней")
    s.add_argument("--no-save", action="store_true", help="не обновлять снимок состояния")
    s.add_argument("--pull", action="store_true", help="забрать новые файлы курсов в stash/")
    s.add_argument("--since", **SINCE)

    s = add(sub, "update", "обновить study из репозитория и блоки агента", cmd_update)
    s.add_argument("--check", action="store_true", help="только проверить, ничего не менять")
    s.add_argument("--yes", "-y", action="store_true",
                   help="обновить без вопроса (без терминала — обязателен)")

    add(sub, "setup", "первоначальная настройка: токены, каталоги, команда в PATH, оператор, курсы",
        lambda cfg, _: setup.run(cfg))

    s = add(sub, "agent", "файл инструкций для ИИ-оператора в корне учебной директории", cmd_agent)
    s.add_argument("operator", nargs="*", choices=list(agent.OPERATORS), metavar="оператор",
                   help="claude | codex | gemini | copilot; без аргумента — состояние")

    add(sub, "me", "кто я и сколько функций доступно токену", cmd_me)

    s = add(sub, "courses", "мои курсы: список + строка COURSE_IGNORE для config.env", cmd_courses)
    s.add_argument("--all", action="store_true", help="включая скрытые")
    s.add_argument("--setup", action="store_true",
                   help="интерактивно записать COURSE_IGNORE/CODE в config.env")

    s = add(sub, "functions", "функции, доступные токену", cmd_functions)
    s.add_argument("filter", nargs="?", help="подстрока имени")

    s = add(sub, "call", "произвольный вызов ручки Moodle", cmd_call)
    s.add_argument("function")
    s.add_argument("params", nargs="*", metavar="ключ=значение",
                   help="повтор ключа кодируется как массив")

    s = add(sub, "assigns", "задания и сроки", cmd_assigns)
    s.add_argument("--course", help="id или код предмета")

    s = add(sub, "calendar", "события календаря (только дедлайны, расписания пар в Moodle нет)",
            cmd_calendar)
    s.add_argument("--days", type=int, default=30)

    s = add(sub, "grades", "баллы по курсам", cmd_grades)
    s.add_argument("--course", help="id или код предмета")

    s = add(sub, "files", "файлы курса: что появилось и забрать в stash/", cmd_files)
    s.add_argument("course", nargs="?", help="код предмета или id курса; без него — все курсы")
    s.add_argument("--pull", action="store_true", help="скачать новые в <код>/stash/")
    s.add_argument("--all", action="store_true", help="показать все файлы, не только новые")
    s.add_argument("--force", action="store_true", help="перекачать даже то, что уже лежит")

    s = add(sub, "status", "состояние моего ответа по заданию", cmd_status)
    s.add_argument("assign_id", type=int)

    s = add(sub, "upload", "загрузка файлов в черновую область, печатает itemid", cmd_upload)
    s.add_argument("files", nargs="+")
    s.add_argument("--itemid", type=int, default=0, help="добавить к существующему itemid")

    submit_parser(sub)
    s = add(sub, "task", "карточка задания: текст, срок, состояние, что принимает, что на диске",
            cmd_task)
    s.add_argument("course", help="код предмета или id курса")
    s.add_argument("what", help="NN — лабораторная по номеру, иначе id задания (study assigns)")


def submit_parser(sub):
    s = add(sub, "submit", "отправка ответа на задание (необратимо)", cmd_submit)
    s.add_argument("assign_id", type=int)
    s.add_argument("--text", help="файл с текстом ответа (у заданий «только файлы» не нужен)")
    s.add_argument("--attach", nargs="+", metavar="ФАЙЛ",
                   help="вложения: проверить, загрузить и прикрепить (вместо upload + --files)")
    s.add_argument("--files", type=int, help="itemid из study upload")
    s.add_argument("--confirm", action="store_true", help="подтвердить отправку")


def build_parser():
    p = parser("study", "ТУИС одной командой: сводка, задания, файлы курсов, отправка ответа.")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="команда")
    tuis_parsers(sub)
    return p


def main(argv=None):
    return run(build_parser(), Config, argv)
