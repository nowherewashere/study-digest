"""Файлы курсов из ТУИС: что появилось и как забрать в `<код предмета>/stash/`.

Сводка сообщает, что в курсе появились файлы; забирает их эта команда. Берётся
не всё подряд: только документы и только до потолка по размеру, иначе в stash
натечёт то, что там не нужно.
"""
import json
import pathlib
import re

from .config import ROOT, StudyError
from .fmt import moment

DOCS = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".md", ".txt", ".tex", ".bib",
        ".ppt", ".pptx", ".odp", ".xls", ".xlsx", ".ods", ".csv",
        ".zip", ".7z", ".rar", ".tar", ".gz"}
MAX_SIZE = 50 * 1024 * 1024


def present(into, name):
    """Файл уже в stash, где бы он там ни лежал: часть материалов разложена по подкаталогам."""
    return next(into.rglob(name), None) if into.is_dir() else None


def stash(course):
    if not course.code:
        raise StudyError("config", f"у курса {course.id} нет каталога в config.env "
                                   "(стоит «-»), забирать файлы некуда")
    return ROOT / course.code / "stash"


def safe(name):
    """Имя файла из ТУИС — в имя на диске: без разделителей пути и без пустого имени."""
    name = re.sub(r"[/\\\x00]", "_", name or "").strip() or "file"
    return name[:200]


def listing(cfg, moodle, course, since=None, everything=False):
    """Файлы курса; `new` — появился или изменился после `since`."""
    if since is None:
        state_file = cfg.state_file()
        since = json.loads(state_file.read_text()).get("last_run") if state_file.exists() else 0
    since = since or 0
    into = stash(course)
    out = []
    for sec in moodle.contents(course.id):
        for m in sec.get("modules", []):
            for c in m.get("contents") or []:
                if c.get("type") != "file" or not c.get("fileurl"):
                    continue
                name = safe(c.get("filename"))
                size = c.get("filesize") or 0
                ext = pathlib.Path(name).suffix.lower()
                have = present(into, name)
                skip = None
                if not size:
                    # mod_page отдаёт index.html с нулевым размером — это страница, не файл
                    skip = "страница курса"
                elif ext not in DOCS:
                    skip = "тип " + (ext or "без расширения")
                elif size > MAX_SIZE:
                    skip = "размер %.0f МБ" % (size / 1048576)
                item = {"name": name, "size": size, "ext": ext,
                        "modified": moment(c.get("timemodified")),
                        "url": c["fileurl"], "section": sec.get("name"),
                        "module": m.get("name"), "modname": m.get("modname"),
                        "path": str(have or into / name), "have": bool(have),
                        "new": (c.get("timemodified") or 0) > since, "skip": skip}
                if everything or item["new"]:
                    out.append(item)
    out.sort(key=lambda x: -(x["modified"]["ts"] if x["modified"] else 0))
    return {"course": course.as_dict(), "stash": str(into), "since": moment(since),
            "files": out}


def pull(moodle, data, force=False):
    """Скачивает то, что прошло фильтр и ещё не лежит в stash."""
    into = pathlib.Path(data["stash"])
    got, errors = [], []
    for f in data["files"]:
        if f["skip"] or (f["have"] and not force):
            continue
        dest = into / f["name"]
        try:
            body = moodle.download(f["url"])
        except StudyError as e:
            errors.append({**e.as_dict(), "where": f["name"]})
            continue
        into.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        f["have"] = True
        f["pulled"] = len(body)
        got.append({"name": f["name"], "bytes": len(body), "path": str(dest)})
    data["pulled"] = got
    data["errors"] = errors
    return data


def render(d, pulled=False):
    out = ["Курс: {} · stash: {}".format(d["course"]["title"], d["stash"]),
           "Новым считается всё, что изменилось после {}".format(
               d["since"]["full"] if d["since"] else "начала времён")]
    if not d["files"]:
        out.append("\nНовых файлов нет.")
        return "\n".join(out)
    out.append("")
    for f in d["files"]:
        mark = "скачан" if f.get("pulled") else ("пропущен: " + f["skip"] if f["skip"]
                                                 else "уже есть" if f["have"] else "можно забрать")
        out.append("  {:<16} {:>8} КБ  {:<12} {}".format(
            f["modified"]["full"] if f["modified"] else "—", f["size"] // 1024, mark, f["name"]))
        out.append("             {} · {}".format(f["section"] or "—", f["module"] or "—"))
    if pulled:
        out.append("\nСкачано: {} файл(ов) в {}".format(len(d.get("pulled") or []), d["stash"]))
        for e in d.get("errors") or []:
            out.append("  не удалось: {} — {}".format(e.get("where"), e["message"]))
    else:
        can = [f for f in d["files"] if not f["skip"] and not f["have"]]
        if can:
            out.append("\nЗабрать: study files {} --pull".format(
                d["course"]["code"] or d["course"]["id"]))
    return "\n".join(out)
