"""Форматирование: единственный источник дат и текста для всего инструмента."""
import datetime
import html as htmllib
import re
import time


def left(sec):
    """Сколько осталось, словами."""
    if sec < 0:
        return "срок прошёл"
    if sec < 3600:
        return "меньше часа"
    if sec < 86400:
        return "%d ч" % (sec // 3600)
    return "%d дн %d ч" % (sec // 86400, (sec % 86400) // 3600)


def moment(ts, now=None):
    """Единый объект времени во всём JSON. Нет срока — None, а не пустая строка."""
    if not ts:
        return None
    ts = int(ts)
    now = int(now if now is not None else time.time())
    delta = ts - now
    return {
        "ts": ts,
        "iso": datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds"),
        "text": time.strftime("%d.%m %H:%M", time.localtime(ts)),
        "full": time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)),
        "left": left(delta),
        "left_sec": delta,
        "overdue": delta < 0,
    }


def plain(s, limit=280):
    """HTML из описаний Moodle → однострочный текст."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = htmllib.unescape(re.sub(r"\s+", " ", s)).strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def table(rows, headers=None):
    """Простая таблица с выравниванием по колонкам."""
    rows = [[str(c) for c in r] for r in rows]
    if not rows:
        return ""
    data = ([list(headers)] if headers else []) + rows
    widths = [max(len(r[i]) for r in data) for i in range(len(data[0]))]
    out = []
    for i, r in enumerate(data):
        out.append("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
        if headers and i == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)
