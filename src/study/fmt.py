import datetime
import html as htmllib
import re
import time

from kit.config import ToolError

HOUR = 3600
DAY = 24 * HOUR
MSK = datetime.timezone(datetime.timedelta(hours=3), "MSK")


def msk(ts):
    return datetime.datetime.fromtimestamp(int(ts), MSK)


def left(sec):
    if sec < 0:
        return "срок прошёл"
    if sec < HOUR:
        return "меньше часа"
    if sec < DAY:
        return f"{sec // HOUR} ч"
    return f"{sec // DAY} дн"


WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def weekday(ts):
    return WEEKDAYS[msk(ts).weekday()]


def moment(ts, now=None):
    if not ts:
        return None
    ts = int(ts)
    now = int(now if now is not None else time.time())
    delta = ts - now
    return {
        "ts": ts,
        "iso": msk(ts).isoformat(timespec="seconds"),
        "text": msk(ts).strftime("%d.%m %H:%M"),
        "full": msk(ts).strftime("%d.%m.%Y %H:%M"),
        "left": left(delta),
        "left_sec": delta,
        "overdue": delta < 0,
    }


def plain(s, limit=280):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+([.,;:!?»)])", r"\1", htmllib.unescape(re.sub(r"\s+", " ", s)).strip())
    return s[:limit] + ("…" if len(s) > limit else "")


WORKS = {"lab": "ЛР", "hw": "ДЗ", "topic": "Тема доклада к лекции", "talk": "Доклад к лекции",
         "retake": "Пересдача ЛР", "task": "Задача"}
PATTERNS = [
    ("lab", r"^Сдать отч[её]т по лабораторной работе №?\s*(\d+)\.?\s*(.*)$"),
    ("lab", r"^Загрузка (\d+) лабораторной работы$"),
    ("retake", r"^Пересдача (?:лабораторной работы|ЛР) №?\s*(\d+)\.?\s*(.*)$"),
    ("hw", r"^Сдать отч[её]т по домашней работе №?\s*(\d+)\.?\s*(.*)$"),
    ("topic", r"^Выбрать тему доклада к лекции (\d+)$"),
    ("talk", r"^(?:Сдать доклад\.\s*Лекция|Доклад к лекции)\s*(\d+)$"),
    ("task", r"^Решение задачи (\d+)\s*ИДЗ$"),
]


def parse_name(name):
    name = (name or "").strip()
    for work, pat in PATTERNS:
        m = re.match(pat, name, re.I)
        if m:
            g = m.groups()
            return {"work": work, "num": g[0], "topic": (g[1] if len(g) > 1 else "").strip(' ."«»')}
    return None


def lab_id(num):
    m = re.fullmatch(r"(?:lab)?(\d{1,2})", str(num).strip().lower())
    if not m:
        raise ToolError("study", f"ожидается номер работы (NN), а не «{num}»")
    return m.group(1).zfill(2)


def lab_number(name, work="lab"):
    p = parse_name(name)
    return p["num"].zfill(2) if p and p["work"] == work else None


def short_name(name, tail=True):
    p = parse_name(name)
    if not p:
        return plain(name, 60)
    return f"{WORKS[p['work']]} {p['num']}" + (f" — {p['topic']}" if tail and p["topic"] else "")


def md_table(rows, headers):
    def line(r):
        return "| " + " | ".join(str(c) for c in r) + " |"
    return "\n".join([line(headers), line("-" * max(len(h), 3) for h in headers)] +
                     [line(r) for r in rows])


def failures(errors):
    return "Не удалось: " + "; ".join(
        f"{e['source']} · {e['where']} · {e['message'][:80]}" for e in errors)
