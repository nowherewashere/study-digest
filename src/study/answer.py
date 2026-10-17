import pathlib
import re

from . import hosting, local
from .config import ROOT, StudyError
from .rutube import Rutube

RUTUBE_VIDEO = re.compile(r"rutube\.ru/video/([0-9a-f]{32})")

TEMPLATE = ("# Ссылки на скринкасты для ответа в ТУИС. "
            "Заполнить и запустить `study answer` ещё раз.\n")


def build(cfg, code, num, tag=None):
    num = local.lab_id(num)
    if local.flow_of(cfg, code) != "release":
        raise StudyError("local", f"{code} сдаётся файлом (FLOW file): "
                                  f"study submit <id> --attach {code}/lab{num}/…/_output/*.pdf; "
                                  "study answer здесь не нужен")
    repo = local.course_repo(code)
    if not repo:
        raise StudyError("local", f"не найден репозиторий курса в {ROOT / code}")
    lab = repo / local.LABS_DIR / f"lab{num}"
    if not lab.is_dir():
        raise StudyError("local", f"нет каталога {lab}")

    v = local.videos(code, num)
    if not v["exists"]:
        env = pathlib.Path(v["path"])
        env.parent.mkdir(parents=True, exist_ok=True)
        env.write_text(TEMPLATE + "".join(f"{k}=\n" for k in local.VIDEO_KEYS), encoding="utf-8")
        return {"created": v["path"], "text": None, "attachments": [], "missing": v["missing"]}

    tag = tag or local.git(repo, "describe", "--tags", "--abbrev=0")
    val = v["values"]

    body = []
    for site, name in local.SITES.items():
        links = [f"  - [{t}]({val[f'{site}_{slot}']})" for slot, t in local.SLOTS.items()
                 if val.get(f"{site}_{slot}")]
        playlist = val.get(f"{site}_PLAYLIST")
        if links or playlist:
            body.append(f"- Скринкасты, {name}:" + (f" [плейлист]({playlist})" if playlist else ""))
            body += links
    body.append("- Репозиторий и релиз:")
    for cls in hosting.HOSTS.values():
        slug = local.repo_from_remote(repo, cls.remote, cls.host)
        if slug:
            h = cls(cfg, repo=slug)
            body.append(f"  - [{cls.source}]({h.repo_url()}), [релиз {tag}]({h.web_url(tag)})")
    text = "\n".join(body) + "\n"

    out = local.tuis_dir(code) / f"lab{num}.md"
    out.write_text(text, encoding="utf-8")
    return {"created": None, "path": str(out), "text": text, "tag": tag,
            "repo": str(repo), "lab": str(lab),
            "attachments": [str(p) for p in sorted(lab.glob("*/_output/*.pdf"))],
            "missing": v["missing"],
            "videos": check_videos(cfg, repo, num, tag, val)}


def previous_release_date(repo, tag):
    prev = local.git(repo, "describe", "--tags", "--abbrev=0", f"{tag}^") if tag else ""
    return local.git(repo, "log", "-1", "--format=%cs", prev) if prev else ""


def video_warnings(card, number, since):
    out = []
    if not number.search(card.get("title") or ""):
        out.append("в названии нет номера работы")
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
    except StudyError as e:
        return {"rows": rows, "error": e.message}
    return {"rows": rows, "error": None}


def video_lines(videos):
    out = []
    if videos["rows"]:
        out.append("Видео в ответе (сверь с записью):")
    for v in videos["rows"]:
        d = v.get("duration") or 0
        out.append(f"  {v['key']}: {v['title']} · {(v.get('created') or '?')[:10]} · "
                   f"{d // 60}:{d % 60:02d}")
        out += [f"    ! {w}" for w in v["warnings"]]
    if videos["error"]:
        out.append("Видео не проверены: " + videos["error"])
    return out


def render(d):
    if d["created"]:
        return f"Создан {d['created']} — заполни ссылки и запусти снова."
    out = [d["text"], "---", "Сохранено: " + d["path"]]
    out.append("Прикрепить к ответу:" if d["attachments"]
               else "PDF не собраны — сделай quarto render")
    out += ["  " + f for f in d["attachments"]]
    out += video_lines(d.get("videos") or {"rows": [], "error": None})
    if d["missing"]:
        out.append("Не заполнено в {}: {}".format(
            pathlib.Path(d["path"]).with_suffix(".env").name, ", ".join(d["missing"])))
    return "\n".join(out)
