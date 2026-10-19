import re

from hosting.client import HOSTS
from kit import git
from kit.config import ToolError
from rutube.client import Rutube

from .lab import SITES, SLOTS, TEMPLATE, VIDEO_KEYS, lab_id, videos

RUTUBE_VIDEO = re.compile(r"rutube\.ru/video/([0-9a-f]{32})")


def build(cfg, course, num, tag=None):
    num = lab_id(num)
    lab = course.lab(num)
    if not lab.is_dir():
        raise ToolError("labrelease", f"нет каталога {lab}")
    env = course.env(num)
    v = videos(env)
    if not v["exists"]:
        env.parent.mkdir(parents=True, exist_ok=True)
        env.write_text(TEMPLATE + "".join(f"{k}=\n" for k in VIDEO_KEYS), encoding="utf-8")
        return {"created": str(env), "path": None, "text": None, "blocked": [],
                "missing": v["missing"]}

    tag = tag or course.latest_tag()
    val = v["values"]
    body = []
    for site, name in SITES.items():
        links = [f"  - [{t}]({val[f'{site}_{slot}']})" for slot, t in SLOTS.items()
                 if val.get(f"{site}_{slot}")]
        playlist = val.get(f"{site}_PLAYLIST")
        if links or playlist:
            body.append(f"- Скринкасты, {name}:" + (f" [плейлист]({playlist})" if playlist else ""))
            body += links
    body.append("- Репозиторий и релиз:")
    for cls in HOSTS.values():
        slug = git.repo_from_remote(course.repo, cls.remote, cls.host)
        if slug:
            h = cls(cfg, repo=slug)
            body.append(f"  - [{cls.source}]({h.repo_url()}), [релиз {tag}]({h.web_url(tag)})")
    text = "\n".join(body) + "\n"

    checked = check_videos(cfg, course.repo, num, tag, val)
    blocked = [f"{r['key']}: {w}" for r in checked["rows"] for w in r["warnings"]]
    if checked["error"]:
        blocked.append("видео не проверены: " + checked["error"])
    out = course.tuis / f"lab{num}.md"
    if not blocked:
        out.write_text(text, encoding="utf-8")
    base = course.base(num)
    return {"created": None, "path": None if blocked else str(out), "text": text, "tag": tag,
            "code": course.code, "num": num, "blocked": blocked, "missing": v["missing"],
            "videos": checked,
            "attachments": [str(lab / "report" / "_output" / f"{base}-report.pdf"),
                            str(lab / "presentation" / "_output" / f"{base}-presentation.pdf")]}


def previous_release_date(repo, tag):
    prev = git.git(repo, "describe", "--tags", "--abbrev=0", f"{tag}^") if tag else ""
    return git.git(repo, "log", "-1", "--format=%cs", prev) if prev else ""


def video_warnings(card, number, since):
    out = []
    if not number.search(card.get("title") or ""):
        out.append(f"в названии «{card.get('title')}» нет номера работы")
    if since and (card.get("created") or "")[:10] < since:
        out.append(f"загружено раньше прошлого релиза ({since})")
    return out


def check_videos(cfg, repo, num, tag, values):
    links = [(k, m.group(1)) for k, val in sorted(values.items())
             if k.startswith("RUTUBE_") for m in [RUTUBE_VIDEO.search(val or "")] if m]
    if not links:
        return {"rows": [], "error": None}
    number = re.compile(rf"(?i)(lab0*{int(num)}|№\s*{int(num)})(?!\d)")
    since = previous_release_date(repo, tag)
    r = Rutube(cfg)
    rows = []
    try:
        for key, vid in links:
            card = r.video_card(vid)
            rows.append({**card, "key": key, "warnings": video_warnings(card, number, since)})
    except ToolError as e:
        return {"rows": rows, "error": e.message}
    return {"rows": rows, "error": None}


def video_lines(checked):
    out = ["Видео в ответе (сверь с записью):"] if checked["rows"] else []
    for v in checked["rows"]:
        d = v.get("duration") or 0
        out.append(f"  {v['key']}: {v['title']} · {(v.get('created') or '?')[:10]} · "
                   f"{d // 60}:{d % 60:02d}")
    return out


def render(d):
    if d["created"]:
        return (f"Создан {d['created']}: ссылки туда пишет `rutube upload … --slot <slot> "
                f"--env {d['created']}`, потом запусти снова.")
    out = [d["text"], "---", *video_lines(d["videos"])]
    if d["blocked"]:
        out += ["", "Ответ не записан — видео не сходятся с работой:"]
        out += [f"  – {b}" for b in d["blocked"]]
        out.append("Лишнее видео — `rutube playlist remove`, верная ссылка — "
                   "`rutube upload … --slot … --env …`.")
        return "\n".join(out)
    out.append("Сохранено: " + d["path"])
    out.append(f"Отправка: study task {d['code']} {d['num']} → id задания → study submit <id> "
               f"--text {d['path']} --attach " + " ".join(d["attachments"]))
    if d["missing"]:
        out.append("Пусто в .env (в ответ не попадёт): " + ", ".join(d["missing"]))
    return "\n".join(out)
