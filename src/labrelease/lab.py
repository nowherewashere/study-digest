import re

from kit import git
from kit.config import ToolError

SITES = {"RUTUBE": "Rutube", "VK": "VKvideo"}
SLOTS = {"LAB": "Выполнение лабораторной работы", "REPORT": "Подготовка отчёта",
         "PRESENTATION": "Подготовка презентации", "DEFENSE": "Защита лабораторной работы"}
VIDEO_KEYS = [f"{site}_{slot}" for site in SITES for slot in ["PLAYLIST", *SLOTS]]
TEMPLATE = ("# Ссылки на скринкасты для ответа в ТУИС: `rutube upload … --slot <slot> --env "
            "<этот файл>` пишет их сам. Потом `labrelease answer NN` ещё раз.\n")


def lab_id(num):
    m = re.fullmatch(r"(?:lab)?(\d{1,2})", str(num).strip().lower())
    if not m:
        raise ToolError("labrelease", f"ожидается номер лабораторной (NN), а не «{num}»")
    return m.group(1).zfill(2)


class Course:

    def __init__(self, repo):
        self.repo = repo
        marker = repo / "COURSE"
        if not marker.is_file():
            raise ToolError("labrelease", f"{repo}: нет файла COURSE — запускать из репозитория "
                                          "курса, заведённого из шаблона преподавателя")
        self.code = marker.read_text(encoding="utf-8").strip()
        self.tuis = repo.parent / "tuis"

    def lab(self, num):
        return self.repo / "labs" / f"lab{num}"

    def base(self, num):
        return f"{self.code}-lab{num}"

    def latest_tag(self):
        return git.git(self.repo, "describe", "--tags", "--abbrev=0")

    def env(self, num):
        return self.tuis / f"lab{num}.env"


def current(path=None):
    repo = git.find_repo(path)
    if not repo:
        raise ToolError("labrelease", "не git-репозиторий: запускать из репозитория курса")
    return Course(repo)


def videos(path):
    if not path.exists():
        return {"path": str(path), "exists": False, "missing": list(VIDEO_KEYS), "values": {}}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return {"path": str(path), "exists": True, "values": values,
            "missing": [k for k in VIDEO_KEYS if not values.get(k)]}
