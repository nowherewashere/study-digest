"""Заготовка ответа в ТУИС по лабораторной работе — только у курсов с профилем release.

Собирает текст по чек-листу преподавателя: скринкасты из `<код>/tuis/labNN.env`,
репозитории и релизы — из git-remote и последнего тега. Ничего не отправляет.
Ни заготовка, ни ссылки в репозиторий курса не попадают: там только сама работа.
"""
import pathlib

from . import hosting, local
from .config import ROOT, StudyError

TEMPLATE = ("# Ссылки на скринкасты для ответа в ТУИС. "
            "Заполнить и запустить `study answer` ещё раз.\n")


def build(cfg, code, num, tag=None):
    """Текст ответа и список вложений. Нет labNN.env — создаётся пустой."""
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

    # Без заголовков (в Moodle они выходят огромными), незаполненные ссылки не печатаем.
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
        # только по remote этого репозитория: GV_REPO/SC_REPO из config.env сюда не подставляем
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
            "missing": v["missing"]}


def render(d):
    if d["created"]:
        return f"Создан {d['created']} — заполни ссылки и запусти снова."
    out = [d["text"], "---", "Сохранено: " + d["path"]]
    out.append("Прикрепить к ответу:" if d["attachments"]
               else "PDF не собраны — сделай quarto render")
    out += ["  " + f for f in d["attachments"]]
    if d["missing"]:
        out.append("Не заполнено в {}: {}".format(
            pathlib.Path(d["path"]).with_suffix(".env").name, ", ".join(d["missing"])))
    return "\n".join(out)
