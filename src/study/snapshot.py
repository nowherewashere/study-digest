import datetime
import json
import re
import time

from .config import StudyError, write_atomic

KEEP_DAYS = 60
DAY = 86400


def history_dir(cfg):
    return cfg.state_file().with_name("state")


def history(cfg, day=None):
    return sorted(p for p in history_dir(cfg).glob("????-??-??.json")
                  if day is None or p.stem <= day)


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def latest(paths):
    for p in reversed(paths):
        state = read(p)
        if state is not None:
            return state, p
    return None, None


def load_state(cfg, since=None, errors=None):
    current = cfg.state_file()
    if since is None:
        state = read(current) if current.exists() else {}
        if state is not None:
            return state
        state, path = latest(history(cfg))
        if errors is not None:
            errors.append({"source": "local", "where": "снимок", "code": None,
                           "message": f"{current.name} повреждён, "
                                      + (f"взят снимок за {path.stem}" if path
                                         else "считаю первым запуском")})
        return state or {}
    if since == "never":
        return {}
    if since == "all":
        return {"last_run": 1, "grades": {}}
    if re.fullmatch(r"\d+", since):
        since = int(time.time()) - int(since) * DAY
    else:
        try:
            since = int(datetime.datetime.strptime(since, "%Y-%m-%d").timestamp())
        except ValueError:
            raise StudyError("config", "--since: ожидается ГГГГ-ММ-ДД, число дней, never или all, "
                                       f"а не «{since}»") from None
    state, _ = latest(history(cfg, time.strftime("%Y-%m-%d", time.localtime(since))))
    if state is not None:
        return state
    state = (read(current) if current.exists() else None) or {}
    return {**state, "last_run": since}


def save_state(cfg, state):
    current = cfg.state_file()
    current.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, ensure_ascii=False, indent=1)
    write_atomic(current, text)
    hist = history_dir(cfg)
    hist.mkdir(exist_ok=True)
    write_atomic(hist / time.strftime("%Y-%m-%d.json", time.localtime(state["last_run"])), text)
    cutoff = time.strftime("%Y-%m-%d", time.localtime(state["last_run"] - KEEP_DAYS * DAY))
    for p in hist.glob("????-??-??.json"):
        if p.stem < cutoff:
            p.unlink()


def merge_known(old, fresh, keys):
    return {k: fresh[k] if k in fresh else (old or {}).get(k, []) for k in keys}


def build(now, old, titles, due, grades, fresh_files, seen, feedback, comments=None):
    announced = old.get("announcements") or {}
    fresh_seen = {str(cid): sorted(set(announced.get(str(cid), [])) | set(ids))[-50:]
                  for cid, ids in seen.items()}
    return {"last_run": now, "assignments": due, "courses": titles, "grades": grades,
            "files": merge_known(old.get("files"), fresh_files, titles),
            "announcements": merge_known(announced, fresh_seen, titles),
            "feedback": {**(old.get("feedback") or {}), **feedback},
            "comments": {**(old.get("comments") or {}), **(comments or {})}}
