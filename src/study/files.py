import contextlib
import os
import pathlib
import re
import sys

from .config import ROOT, StudyError
from .fmt import moment
from .snapshot import load_state

DOCS = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".md", ".txt", ".tex", ".bib",
        ".ppt", ".pptx", ".odp", ".xls", ".xlsx", ".ods", ".csv",
        ".zip", ".7z", ".rar", ".tar", ".gz"}
MAX_SIZE = 50 * 1024 * 1024


def present(into, name):
    return next(into.rglob(name), None) if into.is_dir() else None


def stash(course):
    if not course.code:
        raise StudyError("config", f"у курса {course.id} нет папки (строки CODE в config.env), "
                                   "забирать файлы некуда")
    return ROOT / course.code / "stash"


def empty(course):
    into = stash(course)
    return not into.is_dir() or not any(into.iterdir())


def safe(name):
    name = re.sub(r'[/\\\x00<>:"|?*]', "_", name or "").strip() or "file"
    return name[:200]


def key(module, content):
    return f"{module.get('id')}/{content.get('filename')}"


def kind(content):
    return content.get("type") if content.get("fileurl") else None


def is_file(content):
    return kind(content) == "file"


def is_link(content):
    return kind(content) == "url"


def skip_reason(size, ext):
    if not size:
        return "страница курса"
    if ext not in DOCS:
        return "тип " + (ext or "без расширения")
    if size > MAX_SIZE:
        return "размер %.0f МБ" % (size / 1048576)
    return None


def label(content):
    name = safe(content.get("filename"))
    return f"{name} → {content['fileurl']}" if is_link(content) else name


def keys(contents):
    return sorted(key(m, c) for sec in contents for m in sec.get("modules", [])
                  for c in m.get("contents") or [] if kind(c) in ("file", "url"))


def fresh(module, content, since, known):
    return ((known is not None and key(module, content) not in known)
            or (content.get("timemodified") or 0) > (since or 0))


def listing(cfg, moodle, course, since=None, everything=False):
    state = load_state(cfg)
    if since is None:
        since = state.get("last_run")
    since = since or 0
    known = state.get("files", {}).get(str(course.id))
    known = set(known) if known is not None else None
    into = stash(course)
    out = []
    for sec in moodle.contents(course.id):
        for m in sec.get("modules", []):
            for c in m.get("contents") or []:
                k = kind(c)
                if k not in ("file", "url"):
                    continue
                link = k == "url"
                name = safe(c.get("filename"))
                size = 0 if link else c.get("filesize") or 0
                ext = "" if link else pathlib.Path(name).suffix.lower()
                have = None if link else present(into, name)
                item = {"name": label(c), "size": size, "ext": ext,
                        "modified": moment(c.get("timemodified")), "url": c["fileurl"],
                        "section": sec.get("name"), "module": m.get("name"),
                        "modname": m.get("modname"),
                        "path": None if link else str(have or into / name),
                        "have": bool(have),
                        "newer": bool(have) and (c.get("timemodified") or 0)
                        > int(have.stat().st_mtime),
                        "new": fresh(m, c, since, known),
                        "skip": "ссылка" if link else skip_reason(size, ext)}
                if everything or item["new"]:
                    out.append(item)
    out.sort(key=lambda x: -(x["modified"]["ts"] if x["modified"] else 0))
    return {"course": course.as_dict(), "stash": str(into), "since": moment(since),
            "tracked": known is not None, "all": everything, "files": out}


class Progress:

    def __init__(self, stream=None):
        self.out = stream or sys.stdout
        self.on = self.out.isatty()

    def __call__(self, label, text):
        if self.on:
            self.out.write(f"\r\033[K  {label}: {text}"[:120])
            self.out.flush()

    def clear(self):
        if self.on:
            self.out.write("\r\033[K")
            self.out.flush()


def wanted(f, force=False):
    return not f["skip"] and (force or not f["have"] or f["newer"])


def pull(moodle, data, force=False, progress=None):
    label = data["course"]["code"] or data["course"]["id"]
    todo = [f for f in data["files"] if wanted(f, force)]
    got, errors = [], []
    for i, f in enumerate(todo, 1):
        if progress:
            progress(label, f"{i}/{len(todo)} {f['name']}")
        dest = pathlib.Path(f["path"])
        try:
            body = moodle.download(f["url"])
        except StudyError as e:
            errors.append({**e.as_dict(), "where": f["name"]})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        if f["modified"]:
            with contextlib.suppress(OSError):
                os.utime(dest, (f["modified"]["ts"], f["modified"]["ts"]))
        f["updated"], f["have"], f["newer"] = f["have"], True, False
        f["pulled"] = len(body)
        got.append({"name": f["name"], "bytes": len(body), "path": str(dest),
                    "updated": f["updated"]})
    data["pulled"] = got
    data["errors"] = errors
    return data


def walk(cfg, moodle, do_pull=False, everything=False, force=False, progress=None):
    for course in (c for c in cfg.track(moodle.courses()) if c.code):
        if progress:
            progress(course.code, "состав курса…")
        d = listing(cfg, moodle, course, everything=everything or empty(course))
        yield pull(moodle, d, force=force, progress=progress) if do_pull else d


def pulled_line(d):
    got = d.get("pulled") or []
    upd, bad = sum(1 for g in got if g.get("updated")), len(d.get("errors") or [])
    return (f"скачано {len(got)}" + (f", из них обновлено {upd}" if upd else "")
            + (f", не удалось {bad}" if bad else ""))


def summary(d, pulled=False):
    can = [f for f in d["files"] if wanted(f)]
    label = d["course"]["code"] or d["course"]["id"]
    if pulled:
        return f"{label}: {pulled_line(d)}"
    return f"{label}: {len(can)} к загрузке" if can else f"{label}: нового нет"


def mark(f):
    if f.get("pulled"):
        return "обновлён" if f.get("updated") else "скачан"
    if f["skip"]:
        return "пропущен: " + f["skip"]
    if f["newer"]:
        return "есть, в ТУИС новее"
    return "уже есть" if f["have"] else "можно забрать"


def render(d, pulled=False):
    out = [f"Курс: {d['course']['title'] or d['course']['id']} · stash: {d['stash']}",
           "Все файлы курса" if d["all"] else
           "Новое — " + ("чего не было при прошлой сводке или " if d.get("tracked") else "")
           + f"что изменилось после {d['since']['full'] if d['since'] else 'начала времён'}"]
    if not d["files"]:
        out.append("\nНовых файлов нет.")
        return "\n".join(out)
    out.append("")
    for f in d["files"]:
        out.append("  {:<16} {:>8} КБ  {:<12} {}".format(
            f["modified"]["full"] if f["modified"] else "—", f["size"] // 1024, mark(f), f["name"]))
        out.append("             {} · {}".format(f["section"] or "—", f["module"] or "—"))
    if pulled:
        out.append("\nВ {}: {}".format(d["stash"], pulled_line(d)))
        for e in d.get("errors") or []:
            out.append("  не удалось: {} — {}".format(e.get("where"), e["message"]))
    else:
        can = [f for f in d["files"] if wanted(f)]
        if can:
            out.append("\nЗабрать: study files {} --pull".format(
                d["course"]["code"] or d["course"]["id"]))
    return "\n".join(out)
