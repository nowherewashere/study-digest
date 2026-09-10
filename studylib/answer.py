"""Заготовка ответа в ТУИС по лабораторной работе.

Собирает текст по чек-листу преподавателя: скринкасты из `<код>/tuis/labNN.env`,
репозитории и релизы — из git-remote и последнего тега. Ничего не отправляет.
Ни заготовка, ни ссылки в репозиторий курса не попадают: там только сама работа.
"""
import pathlib

from . import local
from .config import ROOT, StudyError

KEYS = [
    ("RUTUBE_LAB", "Выполнение лабораторной работы"),
    ("RUTUBE_REPORT", "Подготовка отчёта"),
    ("RUTUBE_PRESENTATION", "Подготовка презентации"),
    ("RUTUBE_DEFENSE", "Защита лабораторной работы"),
    ("VK_LAB", "Выполнение лабораторной работы"),
    ("VK_REPORT", "Подготовка отчёта"),
    ("VK_PRESENTATION", "Подготовка презентации"),
    ("VK_DEFENSE", "Защита лабораторной работы"),
]
TEMPLATE = ("# Ссылки на скринкасты для ответа в ТУИС. "
            "Заполнить и запустить `study answer` ещё раз.\n")
# Файлы лежат вне репозитория курса: там должна быть только сама работа.


def build(code, num, tag=None):
    """Текст ответа и список вложений. Нет videos.env — создаётся пустой."""
    num = str(num).zfill(2)
    repo = local.course_repo(code)
    if not repo:
        raise StudyError("local", f"не найден репозиторий курса в {ROOT / code}")
    lab = repo / "labs" / f"lab{num}"
    if not lab.is_dir():
        raise StudyError("local", f"нет каталога {lab}")

    into = local.tuis_dir(code)
    v = local.videos(code, num)
    if not v["exists"]:
        into.mkdir(parents=True, exist_ok=True)
        pathlib.Path(v["path"]).write_text(
            TEMPLATE + "".join(f"{k}=\n" for k in local.VIDEO_KEYS))
        return {"created": v["path"], "text": None, "attachments": [],
                "missing": v["missing"]}

    tag = tag or local.git(repo, "describe", "--tags", "--abbrev=0")
    gv = local.repo_from_remote(repo, "origin", "gitverse.ru")
    sc = local.repo_from_remote(repo, "src", "sourcecraft")
    val = v["values"]

    def link(key, title):
        return f"  - [{title}]({val[key]})" if val.get(key) else f"  - {title}: ССЫЛКА НЕ ЗАПОЛНЕНА"

    def playlist(key, name):
        return f"[{name}]({val[key]})" if val.get(key) else f"{name}: ПЛЕЙЛИСТ НЕ ЗАПОЛНЕН"

    body = ["## Скринкасты", "", "- " + playlist("RUTUBE_PLAYLIST", "Rutube")]
    body += [link(k, t) for k, t in KEYS[:4]]
    body += ["", "- " + playlist("VK_PLAYLIST", "VKvideo")]
    body += [link(k, t) for k, t in KEYS[4:]]
    body += ["", "## Репозитории", "",
             f"- [gitverse](https://gitverse.ru/{gv})",
             f"  - [Релиз {tag}](https://gitverse.ru/{gv}/releases/tag/{tag})",
             f"- [sourcecraft](https://sourcecraft.dev/{sc})",
             f"  - [Релиз {tag}](https://sourcecraft.dev/{sc}/releases/{tag})", ""]
    text = "\n".join(body)

    out = into / f"lab{num}.md"
    out.write_text(text)
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
