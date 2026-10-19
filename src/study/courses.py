import sys
import time

from kit.cli import table
from kit.config import ROOT

from .config import FLOWS, SKILLS
from .fmt import msk

NOTES = """# {title} — заметки

Курс в ТУИС: `{cid}` «{title}». Сдача: {flow}. Преподаватель, формат сдачи, правила —
дописать по программе и БРС из `stash/` (`study files {code} --pull`).

## Задания и сроки

| Задание | cmid / assignid | Срок |
|---|---|---|

## Ключевые находки

-

## Лабы

| № | Тема | Статус |
|---|------|--------|
"""


FLOW_NOTE = {"screencast": "лаба под запись: репозиторий, релиз, скринкасты (скилл {})"
                           .format(SKILLS["screencast"]),
             "direct": "ответ прямо в ТУИС: текст и/или файлы (скилл {})".format(SKILLS["direct"])}


def scaffold(code, cid, title=None, flow=None):
    (ROOT / code / "stash").mkdir(parents=True, exist_ok=True)
    p = ROOT / code / "NOTES.md"
    if p.exists():
        return None
    p.write_text(NOTES.format(title=title or code, cid=cid, code=code,
                              flow=FLOW_NOTE.get(flow, "не задано (FLOW в config.env)")),
                 encoding="utf-8")
    return p


def seen(ts):
    return msk(ts).strftime("%Y-%m-%d") if ts else "никогда"


def rows(cfg, moodle, include_hidden=False):
    win = cfg.active_days() * 86400
    now = time.time()
    ignore, codes, flows = cfg.ignore(), cfg.codes(), cfg.flows()
    return [{"id": c["id"], "shortname": c.get("shortname"), "title": c["fullname"],
             "lastaccess": c.get("lastaccess") or 0, "code": codes.get(c["id"]),
             "flow": flows.get(c["id"]), "ignored": c["id"] in ignore,
             "stale": not c.get("lastaccess") or now - c["lastaccess"] > win}
            for c in moodle.courses(include_hidden=include_hidden)]


def render(rows_):
    stale = " ".join(str(r["id"]) for r in rows_ if r["stale"] and not r["ignored"])
    return "\n".join([
        table([[str(r["id"]), seen(r["lastaccess"]),
                "игнор" if r["ignored"] else ("старый?" if r["stale"] else ""),
                r["code"] or "-", r["flow"] or "-",
                r["title"]] for r in rows_],
              ["id", "заходил", "", "папка", "сдача", "курс"]),
        "", "Строка для config.env — курсы, которые НЕ отслеживать (кандидаты «старый?»):",
        f"COURSE_IGNORE={stale}", "",
        "Папку курса задать: CODE <id> <имя-папки>; сдачу — FLOW <id> " + "|".join(FLOWS)])


def setup(cfg, rows_):
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
            sys.stdout.write(f"\033[{prev + 1}A\033[J")
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

    print("\nИмя локальной папки и сдача (screencast - лаба под запись: репозиторий, релиз, "
          "скринкасты; direct - ответ прямо в ТУИС) для каждого курса:")
    codes, flows = {}, {}
    for r in rows_:
        if r["id"] in ignore_ids:
            continue
        default = r["code"] or str(r["id"])
        code = input(f"  {r['title'][:50]} [{default}]: ").strip() or default
        codes[r["id"]] = code
        guess = r["flow"] or "direct"
        ans = input(f"    сдача, screencast|direct [{guess}]: ").strip().lower()
        flows[r["id"]] = {"s": "screencast", "d": "direct"}.get(ans[:1], guess)

    cfg.write_courses(ignore_ids, codes, flows)
    titles = {r["id"]: r["title"] for r in rows_}
    notes = []
    for cid, code in codes.items():
        if scaffold(code, cid, titles.get(cid), flows[cid]):
            notes.append(code)
    return {"ignore": sorted(ignore_ids), "code": codes, "flow": flows, "notes": notes}
