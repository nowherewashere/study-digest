"""Разбор команд и вывод. Каждая команда возвращает (данные, текст[, код возврата]).

`--json` печатает данные, без него — текст. Ошибка StudyError печатается в stderr
с подсказкой, если она известна, и даёт код возврата 2.
"""
import argparse
import json
import pathlib
import sys
import time

from . import agent, answer, courses, digest, files, hosting, local, setup, update
from .config import Config, Course, StudyError
from .fmt import moment, plain, table
from .moodle import Moodle, accepts, accepts_line, check_submission, mb
from .rutube import DEFAULT_CATEGORY, Rutube


def course_of(cfg, value):
    """Курс по id или имени папки (строка CODE в config.env)."""
    codes = cfg.codes()
    if str(value).isdigit():
        return Course(int(value), codes.get(int(value)))
    cid = next((i for i, c in codes.items() if c == value), None)
    if cid is None:
        raise StudyError("config", f"нет курса «{value}» (config.env: CODE <id> {value})")
    return Course(cid, value)


def read_text(path):
    return pathlib.Path(path).read_text(encoding="utf-8") if path else None


def kv(pairs):
    """k=v из командной строки; повтор ключа собирается в список для массивов Moodle."""
    out = {}
    for item in pairs:
        key, _, value = item.partition("=")
        if key in out:
            out[key] = (out[key] if isinstance(out[key], list) else [out[key]]) + [value]
        else:
            out[key] = value
    return out


# --- ТУИС

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


def cmd_assigns(cfg, args):
    only = course_of(cfg, args.course).id if args.course else None
    course_list, warnings = Moodle(cfg).assignments([only] if only else None)
    rows, lines = [], []
    for c in course_list:
        if not c["assignments"]:
            continue
        lines.append("\n[{}] {}".format(c["id"], c["fullname"]))
        for a in c["assignments"]:
            due = moment(a.get("duedate"))
            rows.append({"course": {"id": c["id"], "title": c["fullname"]},
                         "assign_id": a["id"], "cmid": a["cmid"], "name": a["name"], "due": due,
                         "intro": plain(a.get("intro"), 2000)})   # текст задания — только в JSON
            lines.append("  id={} cmid={} до {}  {}".format(
                a["id"], a["cmid"], due["text"] if due else "—", a["name"]))
    if warnings:
        lines.append(f"\nСкрыто ограничением доступа: {len(warnings)} "
                     "(сроки видны в `study digest`)")
    return {"assignments": rows, "warnings": warnings}, "\n".join(lines).lstrip()


def cmd_calendar(cfg, args):
    now = int(time.time())
    events = Moodle(cfg).calendar(now, now + args.days * 86400)
    rows = [{"at": moment(e["timesort"], now), "name": e.get("name"),
             "course": (e.get("course") or {}).get("shortname"),
             "course_id": (e.get("course") or {}).get("id")} for e in events]
    return rows, table([[r["at"]["text"], (r["name"] or "")[:60], r["course"] or ""]
                        for r in rows]) or "нет событий"


def named(cfg, m, value):
    """Курс по id или папке — с названием из ТУИС, если он там есть."""
    c = course_of(cfg, value)
    return next((t for t in cfg.track(m.courses()) if t.id == c.id), c)


def cmd_grades(cfg, args):
    m = Moodle(cfg)
    tracked = [named(cfg, m, args.course)] if args.course else cfg.track(m.courses())
    rows, lines = [], []
    for c in tracked:
        try:
            grades = m.grades(c.id)
        except StudyError as e:
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
    """Один курс — подробный список; без курса — все папки из config.env, по строке на курс."""
    m = Moodle(cfg)
    progress = files.Progress()
    if args.course:
        course = named(cfg, m, args.course)
        # в пустую stash/ забираем всё: сравнивать «новое с прошлого запуска» не с чем
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


def cmd_submit(cfg, args):
    """План сверяется с настройками задания (что принимает) и с файлами на диске; при
    несовпадении — отказ даже с --confirm. Вложения из --attach грузятся только при отправке."""
    m = Moodle(cfg)
    text = read_text(args.text)
    attach = [pathlib.Path(p) for p in args.attach or []]
    course_list, _ = m.assignments()
    found = next((a for c in course_list for a in c["assignments"]
                  if a["id"] == args.assign_id), None)
    acc = accepts(found) if found else None
    problems = check_submission(acc, text, attach, args.files)
    plan = {"assign_id": args.assign_id, "name": found["name"] if found else None,
            "due": moment(found.get("duedate")) if found else None, "accepts": acc,
            "text_file": args.text, "text_chars": len(text or ""),
            "attach": [{"name": p.name, "bytes": p.stat().st_size if p.is_file() else None}
                       for p in attach],
            "files_itemid": args.files, "problems": problems, "confirmed": bool(args.confirm)}
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
             "  текст: " + (f"{args.text} ({len(text)} символов), формат Markdown"
                            if text is not None else "нет"),
             "  вложения: " + vl]
    if problems:
        lines += ["", "Нельзя отправить:"] + [f"  – {x}" for x in problems]
        return plan, "\n".join(lines), 1
    if not args.confirm:
        lines += ["", ("Отправка необратима: у заданий курса submissiondrafts=0, черновика "
                       "не будет. Повтори с --confirm.")]
        return plan, "\n".join(lines), 1
    itemid = m.upload(attach, args.files or 0) if attach else args.files
    plan["files_itemid"] = itemid
    plan["result"] = m.save_submission(args.assign_id, text, itemid)
    return plan, "Отправлено: {} (id {})".format(plan["name"] or "?", args.assign_id)


# --- хостинги

def client(cfg, args):
    return hosting.HOSTS[args.host](cfg, path=local.find_repo())


def cmd_host_releases(cfg, args):
    rows = client(cfg, args).releases()
    return rows, table([[r["tag"] or "—", r.get("name") or "", str(r["assets"]),
                         r.get("status") or ""] for r in rows],
                       ["тег", "название", "файлов", "статус"]) or "релизов нет"


def cmd_host_release(cfg, args):
    out = client(cfg, args).release(args.tag, args.title, read_text(args.notes), sha=args.sha)
    return out, "Релиз {} создан: {}".format(out["tag"], out["url"])


def cmd_host_update(cfg, args):
    out = client(cfg, args).update(args.tag, title=args.title, notes=read_text(args.notes))
    return out, "Релиз {} обновлён: {}".format(out["tag"], out["url"])


def cmd_host_asset(cfg, args):
    out = client(cfg, args).asset(args.release, args.file, args.name)
    return out, "Загружено: " + out["name"]


def cmd_host_api(cfg, args):
    out = client(cfg, args).api(args.path)
    return out, json.dumps(out, ensure_ascii=False, indent=1)


# --- Rutube

def rt(cfg, args):
    return Rutube(cfg, mode=args.mode)


def videos_table(rows):
    return table([[str(v["id"]), v["title"] or "", "скрыто" if v["hidden"] else "", v["url"] or ""]
                  for v in rows], ["id", "название", "", "ссылка"])


def cmd_rt_login(cfg, args):
    out = Rutube(cfg).login(args.email)
    return out, "Rutube: сохранён token (режим token): " + out["token_file"]


def cmd_rt_jwt(cfg, args):
    out = Rutube(cfg).save_refresh(args.refresh)
    return out, "Rutube: сохранён refresh_token (режим jwt): " + out["refresh_file"]


def cmd_rt_me(cfg, args):
    rows = rt(cfg, args).me()
    return rows, videos_table(rows) or "вход работает, видео пока нет"


def cmd_rt_api(cfg, args):
    out = rt(cfg, args).api(args.path)
    return out, json.dumps(out, ensure_ascii=False, indent=1)


def cmd_rt_categories(cfg, args):
    rows = Rutube(cfg).categories()
    return rows, table([[str(c["id"]), c["short"] or "", c["name"] or ""] for c in rows],
                       ["id", "код", "название"])


def cmd_rt_video(cfg, args):
    v = rt(cfg, args).video(args.video_id)
    keys = [("id", "id"), ("title", "название"), ("is_hidden", "скрыто"),
            ("video_url", "ссылка"), ("duration", "длительность")]
    cat = (v.get("category") or {}).get("name")
    return v, "\n".join([f"{label}: {v.get(k)}" for k, label in keys] + [f"категория: {cat}"])


def cmd_rt_edit(cfg, args):
    fields = {"title": args.title, "category": args.category, "age": args.age,
              "description": read_text(args.desc)}
    if args.hidden or args.visible:
        fields["is_hidden"] = not args.visible
    v = rt(cfg, args).edit(args.video_id, **fields)
    return v, "готово: " + (v.get("title") or args.video_id)


def cmd_rt_pl_list(cfg, args):
    rows = rt(cfg, args).playlists()
    return rows, videos_table(rows) or "плейлистов нет"


def cmd_rt_pl_create(cfg, args):
    p = rt(cfg, args).playlist_create(args.title, args.hidden)
    text = f"плейлист создан: {p['id']} {p['url'] or ''}".rstrip()
    return p, text + (f"\nRUTUBE_PLAYLIST={p['url']}" if p["url"] else "")


def cmd_rt_pl_add(cfg, args):
    out = rt(cfg, args).playlist_add(args.playlist_id, args.video_id)
    return out, f"видео {args.video_id} → плейлист {args.playlist_id}"


def cmd_rt_upload(cfg, args):
    if bool(args.file) == bool(args.url):
        raise StudyError("rutube", "укажи либо файл, либо --url (одно из двух)", code="usage")
    title = args.title or (pathlib.Path(args.file).stem if args.file else None)
    category = args.category or DEFAULT_CATEGORY
    age = 0 if args.age is None else args.age
    plan = {"source": args.url or args.file, "title": title, "category": category, "age": age,
            "hidden": args.hidden, "playlist": args.playlist, "confirmed": bool(args.confirm)}
    if not args.confirm:
        size = f" ({pathlib.Path(args.file).stat().st_size} байт)" if args.file else ""
        lines = ["Что будет загружено на Rutube:",
                 f"  источник: {('URL ' + args.url) if args.url else args.file + size}",
                 f"  название: {title or '?'}",
                 f"  категория: {category}   возраст: {age}+",
                 f"  видимость: {'скрыто' if args.hidden else 'публично'}",
                 f"  плейлист: {args.playlist or 'нет'}",
                 "", "Загрузка публикует видео в твой аккаунт. Повтори с --confirm."]
        return plan, "\n".join(lines), 1
    r = rt(cfg, args)
    up = r.upload_url if args.url else r.upload_file
    v = up(args.url or args.file, title=title, description=read_text(args.desc),
           category=category, hidden=args.hidden, age=age)
    if args.playlist:
        r.playlist_add(args.playlist, v["id"])
    text = "загружено: " + v["url"] + (" (скрыто)" if v["hidden"] else "")
    if args.slot:
        text += f"\nRUTUBE_{args.slot.upper()}={v['url']}"
    return v, text


# --- сводки

def cmd_digest(cfg, args):
    d = digest.collect(cfg, Moodle(cfg), days=args.days, save=not args.no_save, since=args.since)
    return d, digest.render_digest(d)


def cmd_state(cfg, args):
    d = digest.state(cfg, Moodle(cfg), days=args.days, with_tuis=not args.local,
                     save=not args.no_save, pull=args.pull, since=args.since)
    return d, digest.render(d)


def cmd_answer(cfg, args):
    d = answer.build(cfg, args.code, args.num, args.tag)
    return d, answer.render(d)


def cmd_update(cfg, args):
    d = update.check()
    if d is None:
        return d, "Это не git-клон с upstream: обновлять нечего."
    if args.check:
        lines = update.plan(d) if d["behind"] else [f"Актуально: {d['version']}."]
        return d, "\n".join(lines + update.stale(d))
    if d["behind"] and not args.yes:
        # код работает с токенами: сначала показать, что приедет; без терминала — только --yes
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


def cmd_setup(cfg, args):
    return setup.run(cfg)


def cmd_agent(cfg, args):
    rows = [agent.install(o) for o in args.operator] if args.operator \
        else [agent.status(o) for o in agent.OPERATORS]
    return rows, agent.render(rows, installed=bool(args.operator))


# --- разбор аргументов

# `--json` принимается и до, и после имени команды. SUPPRESS нужен, чтобы значение
# из подкоманды не затирало уже разобранное значение основного разбора.
JSON = argparse.ArgumentParser(add_help=False)
JSON.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                  help="машиночитаемый вывод")
MODE = argparse.ArgumentParser(add_help=False)
MODE.add_argument("--mode", choices=["auto", "jwt", "token"], default="auto",
                  help="какой вход Rutube использовать (по умолчанию auto)")
SINCE = {"help": "считать прошлым запуском: ГГГГ-ММ-ДД, N дней назад, never, all"}


def add(sub, name, doc, fn, *parents):
    s = sub.add_parser(name, help=doc, description=doc, parents=[JSON, *parents])
    s.set_defaults(fn=fn)
    return s


def tuis_parsers(sub):
    s = add(sub, "state",
            "готовая ежедневная сводка: сроки, баллы, новое в курсах, состояние работ", cmd_state)
    s.add_argument("--days", type=int, help="окно дедлайнов, дней")
    s.add_argument("--local", action="store_true", help="без обращения к ТУИС")
    s.add_argument("--no-save", action="store_true", help="не обновлять снимок состояния")
    s.add_argument("--pull", action="store_true", help="забрать новые файлы курсов в stash/")
    s.add_argument("--since", **SINCE)

    s = add(sub, "digest", "та же сводка, но только по ТУИС, без репозиториев", cmd_digest)
    s.add_argument("--days", type=int, help="окно дедлайнов, дней")
    s.add_argument("--no-save", action="store_true", help="не обновлять снимок состояния")
    s.add_argument("--since", **SINCE)

    s = add(sub, "answer", "заготовка ответа в ТУИС по лабораторной (курсы с FLOW release)",
            cmd_answer)
    s.add_argument("code", help="код предмета, каталог в ~/work/study")
    s.add_argument("num", help="номер лабораторной работы (NN)")
    s.add_argument("--tag", help="тег релиза; по умолчанию последний")

    s = add(sub, "update", "обновить study из репозитория и блоки агента", cmd_update)
    s.add_argument("--check", action="store_true", help="только проверить, ничего не менять")
    s.add_argument("--yes", "-y", action="store_true",
                   help="обновить без вопроса (без терминала — обязателен)")

    add(sub, "setup", "первоначальная настройка: токены, каталоги, команда в PATH, оператор, курсы",
        cmd_setup)

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


def submit_parser(sub):
    s = add(sub, "submit", "отправка ответа на задание (необратимо)", cmd_submit)
    s.add_argument("assign_id", type=int)
    s.add_argument("--text", help="файл с текстом ответа (у заданий «только файлы» не нужен)")
    s.add_argument("--attach", nargs="+", metavar="ФАЙЛ",
                   help="вложения: проверить, загрузить и прикрепить (вместо upload + --files)")
    s.add_argument("--files", type=int, help="itemid из study upload")
    s.add_argument("--confirm", action="store_true", help="подтвердить отправку")


def host_parsers(sub):
    for key, cls in hosting.HOSTS.items():
        h = sub.add_parser(key, help=cls.host + ": релизы и вложения")
        h.set_defaults(host=key)
        hs = h.add_subparsers(dest="hostcmd", required=True, metavar="команда")
        add(hs, "releases", "список релизов", cmd_host_releases)
        s = add(hs, "release", "создать релиз", cmd_host_release)
        s.add_argument("tag")
        s.add_argument("--title", required=True)
        s.add_argument("--notes", required=True, help="файл с описанием")
        s.add_argument("--sha", help="GitVerse: полный SHA; по умолчанию из тега")
        s = add(hs, "update", "изменить название или описание релиза", cmd_host_update)
        s.add_argument("tag")
        s.add_argument("--title")
        s.add_argument("--notes", help="файл с описанием")
        s = add(hs, "asset", "загрузить файл в релиз", cmd_host_asset)
        s.add_argument("release", help="GitVerse: id релиза, SourceCraft: тег")
        s.add_argument("file")
        s.add_argument("--name", help="имя файла в релизе")
        s = add(hs, "api", "произвольный запрос", cmd_host_api)
        s.add_argument("path", help="например /repos/owner/repo/releases")


def rt_parsers(sub):
    r = sub.add_parser("rt", help="Rutube: вход и видео")
    rs = r.add_subparsers(dest="rtcmd", required=True, metavar="команда")
    s = add(rs, "login", "режим token: вход по email и паролю (пароль не хранится); "
            "только для аккаунтов с паролем", cmd_rt_login)
    s.add_argument("--email")
    s = add(rs, "jwt", "режим jwt: сохранить refreshToken из cookie браузера (VK ID / Gazprom ID)",
            cmd_rt_jwt)
    s.add_argument("--refresh", help="сам refreshToken или строка cookie; без флага спросит скрыто")
    add(rs, "me", "проверить вход: мои видео", cmd_rt_me, MODE)
    s = add(rs, "api", "произвольный GET к rutube.ru/api", cmd_rt_api, MODE)
    s.add_argument("path", help="например /video/person/")
    add(rs, "categories", "список категорий Rutube (id для --category)", cmd_rt_categories)
    s = add(rs, "video", "метаданные и состояние своего видео", cmd_rt_video, MODE)
    s.add_argument("video_id")
    s = add(rs, "edit", "правка названия/описания/категории/видимости", cmd_rt_edit, MODE)
    s.add_argument("video_id")
    s.add_argument("--title")
    s.add_argument("--desc", help="файл с описанием")
    s.add_argument("--category", type=int, help="id категории (см. rt categories)")
    s.add_argument("--age", type=int, choices=[0, 6, 12, 14, 16, 18], help="возрастное ограничение")
    s.add_argument("--hidden", action="store_true", help="сделать скрытым")
    s.add_argument("--visible", action="store_true", help="сделать публичным")

    p = rs.add_parser("playlist", help="плейлисты: list/create/add")
    ps = p.add_subparsers(dest="plcmd", required=True, metavar="действие")
    add(ps, "list", "свои плейлисты", cmd_rt_pl_list, MODE)
    s = add(ps, "create", "создать плейлист", cmd_rt_pl_create, MODE)
    s.add_argument("--title", required=True)
    s.add_argument("--hidden", action="store_true", help="скрытый плейлист")
    s = add(ps, "add", "добавить видео в плейлист", cmd_rt_pl_add, MODE)
    s.add_argument("playlist_id")
    s.add_argument("video_id")

    s = add(rs, "upload", "загрузить видео: файл (tus) или --url", cmd_rt_upload, MODE)
    s.add_argument("file", nargs="?", help="локальный видеофайл (либо задать --url)")
    s.add_argument("--url", help="импорт по URL — Rutube скачает сам")
    s.add_argument("--title")
    s.add_argument("--desc", help="файл с описанием")
    s.add_argument("--category", type=int,
                   help=f"id категории (см. rt categories; по умолчанию {DEFAULT_CATEGORY})")
    s.add_argument("--age", type=int, choices=[0, 6, 12, 14, 16, 18],
                   help="возраст (по умолчанию 0+)")
    s.add_argument("--hidden", action="store_true", help="загрузить скрытым")
    s.add_argument("--playlist", help="id плейлиста — сразу добавить туда")
    s.add_argument("--slot", choices=["lab", "report", "presentation", "defense"],
                   help="напечатать строку RUTUBE_<SLOT>= для tuis/labNN.env")
    s.add_argument("--confirm", action="store_true", help="подтвердить загрузку (без него — план)")


class Version(argparse.Action):
    """`--version` зовёт git только когда спросили, а не при каждом запуске."""

    def __call__(self, parser, *_):
        print(f"study {update.version()}")
        parser.exit()


def build_parser():
    p = argparse.ArgumentParser(
        prog="study", description="ТУИС, репозитории курсов и хостинги одной командой.")
    p.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    p.add_argument("--version", action=Version, nargs=0, help="версия по тегам git")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="команда")
    tuis_parsers(sub)
    host_parsers(sub)
    rt_parsers(sub)
    return p


def main(argv=None):
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    try:
        data, text, *rc = args.fn(Config(), args)
        print(json.dumps(data, ensure_ascii=False, indent=1) if args.json else text)
    except StudyError as e:
        print(e.text(), file=sys.stderr)
        if e.hint():
            print(e.hint(), file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130
    return rc[0] if rc else 0
