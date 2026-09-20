"""Файлы курсов из ТУИС: что появилось и как забрать в `<код предмета>/stash/`.

Сводка сообщает, что в курсе появились файлы; забирает их эта команда. Берётся
не всё подряд: только документы и только до потолка по размеру, иначе в stash
натечёт то, что там не нужно.
"""
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
    """Файл уже в stash, где бы он там ни лежал: часть материалов разложена по подкаталогам."""
    return next(into.rglob(name), None) if into.is_dir() else None


def stash(course):
    """Каталог материалов курса; у курса без папки его нет — это ошибка конфигурации."""
    if not course.code:
        raise StudyError("config", f"у курса {course.id} нет папки (строки CODE в config.env), "
                                   "забирать файлы некуда")
    return ROOT / course.code / "stash"


def empty(course):
    """В stash/ курса ещё ничего нет (или его самого нет)."""
    into = stash(course)
    return not into.is_dir() or not any(into.iterdir())


def safe(name):
    """Имя файла из ТУИС — в имя на диске: без разделителей пути, символов, запрещённых
    на Windows (иначе `--pull` там падает), и без пустого имени."""
    name = re.sub(r'[/\\\x00<>:"|?*]', "_", name or "").strip() or "file"
    return name[:200]


def key(module, content):
    """Файл в снимке — модуль и имя. Не дата: файл, скопированный из прошлогоднего курса,
    приходит с датой того года и по `timemodified` новым не выглядит."""
    return f"{module.get('id')}/{content.get('filename')}"


def is_file(content):
    return content.get("type") == "file" and bool(content.get("fileurl"))


def keys(contents):
    """Все файлы состава курса — что запомнить в снимке."""
    return sorted(key(m, c) for sec in contents for m in sec.get("modules", [])
                  for c in m.get("contents") or [] if is_file(c))


def fresh(module, content, since, known):
    """Новый: не было в снимке (`known`; None — снимок без состава) или изменён после `since`."""
    return ((known is not None and key(module, content) not in known)
            or (content.get("timemodified") or 0) > (since or 0))


def listing(cfg, moodle, course, since=None, everything=False):
    """Файлы курса; `new` — не было при прошлой сводке или изменился после `since`."""
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
                if not is_file(c):
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
                        "new": fresh(m, c, since, known), "skip": skip}
                if everything or item["new"]:
                    out.append(item)
    out.sort(key=lambda x: -(x["modified"]["ts"] if x["modified"] else 0))
    return {"course": course.as_dict(), "stash": str(into), "since": moment(since),
            "tracked": known is not None, "all": everything, "files": out}


class Progress:
    """Ход загрузки одной строкой на месте — «nettech: 3/12 002-dns.pdf»; вне терминала молчит.
    Большой курс качается десятки секунд, и без этого кажется, что всё зависло."""

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


def pull(moodle, data, force=False, progress=None):
    """Скачивает то, что прошло фильтр и ещё не лежит в stash; `progress(курс, текст)` — ход."""
    into = pathlib.Path(data["stash"])
    label = data["course"]["code"] or data["course"]["id"]
    todo = [f for f in data["files"] if not f["skip"] and (force or not f["have"])]
    got, errors = [], []
    for i, f in enumerate(todo, 1):
        if progress:
            progress(label, f"{i}/{len(todo)} {f['name']}")
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


def walk(cfg, moodle, do_pull=False, everything=False, force=False, progress=None):
    """По всем курсам с папкой (строки CODE): список файлов каждого, с --pull — и скачивание."""
    for course in (c for c in cfg.track(moodle.courses()) if c.code):
        if progress:
            progress(course.code, "состав курса…")
        d = listing(cfg, moodle, course, everything=everything or empty(course))
        yield pull(moodle, d, force=force, progress=progress) if do_pull else d


def summary(d, pulled=False):
    """Одна строка на курс для прохода по всем: сколько новых, скачано, пропущено."""
    can = [f for f in d["files"] if not f["skip"] and not f["have"]]
    label = d["course"]["code"] or d["course"]["id"]
    if pulled:
        got, bad = len(d.get("pulled") or []), len(d.get("errors") or [])
        return f"{label}: скачано {got}" + (f", не удалось {bad}" if bad else "")
    return f"{label}: {len(can)} к загрузке" if can else f"{label}: нового нет"


def render(d, pulled=False):
    """Список файлов с отметкой: скачан / уже есть / пропущен и почему / можно забрать."""
    out = [f"Курс: {d['course']['title'] or d['course']['id']} · stash: {d['stash']}",
           "Все файлы курса" if d["all"] else
           "Новое — " + ("чего не было при прошлой сводке или " if d.get("tracked") else "")
           + f"что изменилось после {d['since']['full'] if d['since'] else 'начала времён'}"]
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
