"""Разбор команд и вывод. Каждая команда возвращает (данные, текст).

`--json` печатает данные, без него — текст. Ошибка StudyError печатается в stderr
с подсказкой, если она известна, и даёт код возврата 2.
"""
import argparse
import json
import pathlib
import sys

from . import answer as answer_mod
from . import digest as digest_mod
from . import files as files_mod
from . import hosting, local
from .config import Config, StudyError
from .fmt import moment, table
from .moodle import Moodle


def course_id(cfg, value):
    """id курса из числа или кода каталога."""
    if not value:
        return None
    if str(value).isdigit():
        return int(value)
    for c in cfg.courses():
        if c.code == value:
            return c.id
    raise StudyError("config", f"нет курса с кодом {value} в config.env")


def course_of(cfg, value):
    """Курс из config.env по коду каталога или по id."""
    for c in cfg.courses():
        if c.code == value or str(c.id) == str(value):
            return c
    raise StudyError("config", f"нет курса «{value}» в config.env")


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
    m = Moodle(cfg)
    known = {c.id: c for c in cfg.courses()}
    rows = [{"id": c["id"], "shortname": c["shortname"], "title": c["fullname"],
             "in_config": c["id"] in known,
             "code": known[c["id"]].code if c["id"] in known else None}
            for c in m.courses(include_hidden=args.all)]
    lines = ["Готовые строки для config.env (код каталога подставить вместо -):", ""]
    for r in rows:
        mark = "  " if r["in_config"] else "# "
        lines.append("{}COURSE {:<7}{:<14}{}".format(
            mark, r["id"], r["code"] or "-", r["title"]))
    lines.append("")
    lines.append("Отмеченные # ещё не в config.env.")
    return rows, "\n".join(lines)


def cmd_functions(cfg, args):
    names = Moodle(cfg).functions()
    if args.filter:
        names = [n for n in names if args.filter in n]
        return names, "\n".join(names)
    return names, "всего функций: %d" % len(names)


def cmd_call(cfg, args):
    out = Moodle(cfg).call(args.function, **kv(args.params))
    return out, json.dumps(out, ensure_ascii=False, indent=1)


def cmd_assigns(cfg, args):
    only = course_id(cfg, args.course)
    courses, warnings = Moodle(cfg).assignments([only] if only else None)
    rows, lines = [], []
    for c in courses:
        if not c["assignments"]:
            continue
        lines.append("\n[{}] {}".format(c["id"], c["fullname"]))
        for a in c["assignments"]:
            due = moment(a.get("duedate"))
            rows.append({"course": {"id": c["id"], "title": c["fullname"]},
                         "assign_id": a["id"], "cmid": a["cmid"], "name": a["name"],
                         "due": due})
            lines.append("  id={} cmid={} до {}  {}".format(
                a["id"], a["cmid"], due["text"] if due else "—", a["name"]))
    if warnings:
        lines.append("\nСкрыто ограничением доступа: %d (сроки видны в `study digest`)"
                     % len(warnings))
    return {"assignments": rows, "warnings": warnings}, "\n".join(lines).lstrip()


def cmd_calendar(cfg, args):
    import time
    now = int(time.time())
    events = Moodle(cfg).calendar(now, now + args.days * 86400)
    rows = [{"at": moment(e["timesort"], now), "name": e.get("name"),
             "course": (e.get("course") or {}).get("shortname"),
             "course_id": (e.get("course") or {}).get("id")} for e in events]
    return rows, table([[r["at"]["text"], (r["name"] or "")[:60], r["course"] or ""]
                        for r in rows]) or "нет событий"


def cmd_grades(cfg, args):
    m = Moodle(cfg)
    only = course_id(cfg, args.course)
    ids = [only] if only else [c.id for c in cfg.courses()]
    titles = {c.id: c.title for c in cfg.courses()}
    rows, lines = [], []
    for cid in ids:
        try:
            grades = m.grades(cid)
        except StudyError as e:
            lines.append("\n{}: {}".format(titles.get(cid, cid), e.message))
            continue
        for t in grades:
            items = [{"name": i.get("itemname"), "raw": i.get("graderaw"),
                      "max": i.get("grademax"), "type": i.get("itemtype")}
                     for i in t.get("gradeitems", []) if i.get("graderaw") is not None]
            rows.append({"course": {"id": cid, "title": titles.get(cid, t.get("courseshortname"))},
                         "items": items})
            lines.append("\n" + (titles.get(cid) or t.get("courseshortname") or str(cid)))
            body = [["  " + (i["name"] or "")[:50], "%s из %s" % (i["raw"], i["max"])]
                    for i in items if i["type"] != "course"]
            total = next((i for i in items if i["type"] == "course"), None)
            if total:
                body.append(["  ИТОГО", "%s из %s" % (total["raw"], total["max"])])
            lines.append(table(body) if body else "  оценок пока нет")
    return rows, "\n".join(lines).lstrip()


def cmd_files(cfg, args):
    m = Moodle(cfg)
    d = files_mod.listing(cfg, m, course_of(cfg, args.course), everything=args.all)
    if args.pull:
        d = files_mod.pull(m, d, force=args.force)
    return d, files_mod.render(d, pulled=args.pull)


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
    m = Moodle(cfg)
    text = pathlib.Path(args.text).read_text()
    courses, _ = m.assignments()
    found = next((a for c in courses for a in c["assignments"] if a["id"] == args.assign_id), None)
    plan = {"assign_id": args.assign_id, "name": found["name"] if found else None,
            "due": moment(found.get("duedate")) if found else None,
            "text_file": args.text, "text_chars": len(text),
            "files_itemid": args.files, "confirmed": bool(args.confirm)}
    if not args.confirm:
        lines = ["Что будет отправлено:",
                 "  задание: {} (id {})".format(plan["name"] or "?", args.assign_id),
                 "  срок: {}".format(plan["due"]["full"] if plan["due"] else "—"),
                 "  текст: {} ({} символов), формат Markdown".format(args.text, len(text)),
                 "  вложения: {}".format(args.files or "нет"),
                 "",
                 "Отправка необратима: у заданий курса submissiondrafts=0, "
                 "черновика не будет.",
                 "Повтори с --confirm."]
        print("\n".join(lines))
        sys.exit(1)
    out = m.save_submission(args.assign_id, text, args.files)
    plan["result"] = out
    return plan, "Отправлено: {} (id {})".format(plan["name"] or "?", args.assign_id)


# --- хостинги

def client(cfg, which, path=None):
    cls = hosting.GitVerse if which == "gv" else hosting.SourceCraft
    return cls(cfg, path=path or local.find_repo())


def cmd_host_releases(cfg, args):
    rows = client(cfg, args.host).releases()
    return rows, table([[r["tag"] or "—", r.get("name") or "", str(r["assets"]),
                         r.get("status") or ""] for r in rows],
                       ["тег", "название", "файлов", "статус"]) or "релизов нет"


def cmd_host_release(cfg, args):
    c = client(cfg, args.host)
    notes = pathlib.Path(args.notes).read_text()
    out = c.release(args.tag, args.title, notes, sha=args.sha) if args.host == "gv" \
        else c.release(args.tag, args.title, notes)
    return out, "Релиз {} создан: {}".format(out["tag"], out["url"])


def cmd_host_asset(cfg, args):
    c = client(cfg, args.host)
    out = c.asset(args.release, args.file, args.name)
    return out, "Загружено: " + out["name"]


def cmd_host_api(cfg, args):
    out = client(cfg, args.host).api(args.path)
    return out, json.dumps(out, ensure_ascii=False, indent=1)


# --- сводки

def cmd_digest(cfg, args):
    d = digest_mod.collect(cfg, Moodle(cfg), days=args.days, save=not args.no_save)
    return d, digest_mod.render(d)


def cmd_state(cfg, args):
    d = digest_mod.state(cfg, Moodle(cfg), days=args.days, with_tuis=not args.local,
                         save=not args.no_save)
    return d, digest_mod.render_state(d)


def cmd_answer(cfg, args):
    d = answer_mod.build(args.code, args.num, args.tag)
    return d, answer_mod.render(d)


# --- разбор аргументов

def build_parser():
    p = argparse.ArgumentParser(
        prog="study", description="ТУИС, репозитории курсов и хостинги одной командой.")
    p.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    # --json принимается и до, и после имени команды. SUPPRESS нужен, чтобы значение
    # из подкоманды не затирало уже разобранное значение основного разбора.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="машиночитаемый вывод")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="команда")

    def add(name, help, fn):
        s = sub.add_parser(name, help=help, description=help, parents=[common])
        s.set_defaults(fn=fn)
        return s

    s = add("state", "сводка ТУИС и состояние работ — для ежедневной рутины", cmd_state)
    s.add_argument("--days", type=int, help="окно дедлайнов, дней")
    s.add_argument("--local", action="store_true", help="без обращения к ТУИС")
    s.add_argument("--no-save", action="store_true", help="не обновлять снимок состояния")

    s = add("digest", "сводка по ТУИС: дедлайны, обновления, баллы", cmd_digest)
    s.add_argument("--days", type=int, help="окно дедлайнов, дней")
    s.add_argument("--no-save", action="store_true", help="не обновлять снимок состояния")

    s = add("answer", "заготовка ответа в ТУИС по лабораторной работе", cmd_answer)
    s.add_argument("code", help="код предмета, каталог в ~/work/study")
    s.add_argument("num", help="номер лабораторной работы")
    s.add_argument("--tag", help="тег релиза; по умолчанию последний")

    add("me", "кто я и сколько функций доступно токену", cmd_me)

    s = add("courses", "мои курсы готовыми строками для config.env", cmd_courses)
    s.add_argument("--all", action="store_true", help="включая скрытые")

    s = add("functions", "функции, доступные токену", cmd_functions)
    s.add_argument("filter", nargs="?", help="подстрока имени")

    s = add("call", "произвольный вызов ручки Moodle", cmd_call)
    s.add_argument("function")
    s.add_argument("params", nargs="*", metavar="ключ=значение",
                   help="повтор ключа кодируется как массив")

    s = add("assigns", "задания и сроки", cmd_assigns)
    s.add_argument("--course", help="id или код предмета")

    s = add("calendar", "события календаря (только дедлайны, расписания пар в Moodle нет)",
            cmd_calendar)
    s.add_argument("--days", type=int, default=30)

    s = add("grades", "баллы по курсам", cmd_grades)
    s.add_argument("--course", help="id или код предмета")

    s = add("files", "файлы курса: что появилось и забрать в stash/", cmd_files)
    s.add_argument("course", help="код предмета или id курса")
    s.add_argument("--pull", action="store_true", help="скачать новые в <код>/stash/")
    s.add_argument("--all", action="store_true", help="показать все файлы, не только новые")
    s.add_argument("--force", action="store_true", help="перекачать даже то, что уже лежит")

    s = add("status", "состояние моего ответа по заданию", cmd_status)
    s.add_argument("assign_id", type=int)

    s = add("upload", "загрузка файлов в черновую область, печатает itemid", cmd_upload)
    s.add_argument("files", nargs="+")
    s.add_argument("--itemid", type=int, default=0, help="добавить к существующему itemid")

    s = add("submit", "отправка ответа на задание (необратимо)", cmd_submit)
    s.add_argument("assign_id", type=int)
    s.add_argument("--text", required=True, help="файл с текстом ответа")
    s.add_argument("--files", type=int, help="itemid из study upload")
    s.add_argument("--confirm", action="store_true", help="подтвердить отправку")

    for host, name in (("gv", "GitVerse"), ("sc", "SourceCraft")):
        h = sub.add_parser(host, help=name + ": релизы и вложения")
        h.set_defaults(host=host)
        hs = h.add_subparsers(dest="hostcmd", required=True, metavar="команда")
        hs.add_parser("releases", help="список релизов",
                      parents=[common]).set_defaults(fn=cmd_host_releases)
        r = hs.add_parser("release", help="создать релиз", parents=[common])
        r.set_defaults(fn=cmd_host_release)
        r.add_argument("tag")
        r.add_argument("--title", required=True)
        r.add_argument("--notes", required=True, help="файл с описанием")
        r.add_argument("--sha", help="GitVerse: полный SHA; по умолчанию из тега")
        a = hs.add_parser("asset", help="загрузить файл в релиз", parents=[common])
        a.set_defaults(fn=cmd_host_asset)
        a.add_argument("release", help="GitVerse: id релиза, SourceCraft: тег")
        a.add_argument("file")
        a.add_argument("--name", help="имя файла в релизе")
        q = hs.add_parser("api", help="произвольный запрос", parents=[common])
        q.set_defaults(fn=cmd_host_api)
        q.add_argument("path", help="например /repos/owner/repo/releases")
    return p


def main(argv=None):
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    try:
        data, text = args.fn(Config(), args)
    except StudyError as e:
        print(e.text(), file=sys.stderr)
        if e.hint():
            print(e.hint(), file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=1) if args.json else text)
    return 0
