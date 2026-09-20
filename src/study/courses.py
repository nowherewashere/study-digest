"""Курсы ТУИС: список с отметками и интерактивная настройка COURSE_IGNORE/CODE в config.env."""
import sys
import time

from .config import ROOT
from .fmt import table

# Заготовка заметок по предмету: шапку и таблицы заполняет человек или агент по программе
# и БРС из stash/. Файл ни при каких условиях не перезаписывается.
NOTES = """# {title} — заметки

Курс в ТУИС: `{cid}` «{title}». Преподаватель, формат сдачи, правила — дописать по программе
и БРС из `stash/` (`study files {code} --pull`).

## Задания и сроки

| Задание | cmid / assignid | Срок |
|---|---|---|

## Ключевые находки

-

## Лабы

| № | Тема | Статус |
|---|------|--------|
"""


def notes_stub(code, cid, title=None):
    """`<код>/NOTES.md`, если его ещё нет: путь созданного файла, иначе None."""
    p = ROOT / code / "NOTES.md"
    if p.exists():
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(NOTES.format(title=title or code, cid=cid, code=code), encoding="utf-8")
    return p


def seen(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "никогда"


def rows(cfg, moodle, include_hidden=False):
    """Курсы пользователя с признаками: в игноре, давно не заходил, имя папки."""
    win = cfg.active_days() * 86400
    now = time.time()
    ignore, codes = cfg.ignore(), cfg.codes()
    return [{"id": c["id"], "shortname": c.get("shortname"), "title": c["fullname"],
             "lastaccess": c.get("lastaccess") or 0, "code": codes.get(c["id"]),
             "ignored": c["id"] in ignore,
             "stale": not c.get("lastaccess") or now - c["lastaccess"] > win}
            for c in moodle.courses(include_hidden=include_hidden)]


def render(rows_):
    """Таблица курсов и готовая строка COURSE_IGNORE из кандидатов «старый?»."""
    stale = " ".join(str(r["id"]) for r in rows_ if r["stale"] and not r["ignored"])
    return "\n".join([
        table([[str(r["id"]), seen(r["lastaccess"]),
                "игнор" if r["ignored"] else ("старый?" if r["stale"] else ""),
                r["code"] or "-", r["title"]] for r in rows_],
              ["id", "заходил", "", "папка", "курс"]),
        "", "Строка для config.env — курсы, которые НЕ отслеживать (кандидаты «старый?»):",
        f"COURSE_IGNORE={stale}", "",
        "Папку локального репозитория курса задать: CODE <id> <имя-папки>"])


def setup(cfg, rows_):
    """Интерактивно (`study setup`): чекбоксы игнора, затем имя папки на каждый курс."""
    num = {i + 1: r for i, r in enumerate(sorted(rows_, key=lambda r: (r["stale"], r["title"])))}
    ignore_ids = {r["id"] for r in rows_ if r["ignored"]}
    stale_ids = {r["id"] for r in rows_ if r["stale"]}

    def draw(prev):
        out = ["Отметь курсы, которые НЕ отслеживать ([x] = в игнор):"]
        header = False
        for i, r in num.items():
            if r["stale"] and not header:
                out.append("   -- давно не заходил --")
                header = True
            box = "[x]" if r["id"] in ignore_ids else "[ ]"
            out.append(f"  {i:2} {box} {seen(r['lastaccess']):>10}  {r['title'][:58]}")
        out.append("   номер - переключить | s - все давно не заходил | Enter/g - готово")
        if prev and sys.stdout.isatty():
            sys.stdout.write(f"\033[{prev + 1}A\033[J")   # стереть прошлый блок и строку ввода
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()
        return len(out)

    print("")
    drawn = 0
    while True:
        drawn = draw(drawn)
        ans = input("> ").strip().lower()
        if ans in ("", "g", "готово"):
            break
        if ans == "s":
            all_stale = stale_ids <= ignore_ids
            ignore_ids = ignore_ids - stale_ids if all_stale else ignore_ids | stale_ids
            continue
        for tok in ans.replace(",", " ").split():
            if tok.isdigit() and int(tok) in num:
                ignore_ids ^= {num[int(tok)]["id"]}

    # папки: по каждому отслеживаемому курсу спрашиваем имя (Enter - взять id курса)
    print("\nИмя локальной папки для каждого курса (Enter - взять id курса из ТУИС):")
    codes = {}
    for r in rows_:
        if r["id"] in ignore_ids:
            continue
        default = r["code"] or str(r["id"])
        codes[r["id"]] = input(f"  {r['title'][:50]} [{default}]: ").strip() or default

    cfg.write_courses(ignore_ids, codes)
    titles = {r["id"]: r["title"] for r in rows_}
    notes = []
    for cid, code in codes.items():
        (ROOT / code / "stash").mkdir(parents=True, exist_ok=True)
        (ROOT / code / "tuis").mkdir(parents=True, exist_ok=True)
        if notes_stub(code, cid, titles.get(cid)):
            notes.append(code)
    return {"ignore": sorted(ignore_ids), "code": codes, "notes": notes}
