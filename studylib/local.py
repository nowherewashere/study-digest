"""Локальное состояние: git, репозиторий курса, лабы, собранные файлы."""
import pathlib
import re
import subprocess

from .config import ROOT, StudyError

VIDEO_KEYS = [
    "RUTUBE_PLAYLIST", "RUTUBE_LAB", "RUTUBE_REPORT", "RUTUBE_PRESENTATION", "RUTUBE_DEFENSE",
    "VK_PLAYLIST", "VK_LAB", "VK_REPORT", "VK_PRESENTATION", "VK_DEFENSE",
]


def git(path, *args, check=False):
    r = subprocess.run(["git", "-C", str(path)] + list(args), capture_output=True, text=True)
    if r.returncode and check:
        raise StudyError("git", (r.stderr or r.stdout).strip() or "ошибка", where=" ".join(args))
    return r.stdout.strip() if not r.returncode else ""


def repo_slug(url):
    """ssh://[user@]host[:port]/owner/repo.git, git@host:owner/repo.git, https://… → owner/repo."""
    s = re.sub(r"^[a-z]+://([^@/]+@)?[^/]+/", "", url or "")
    s = re.sub(r"^[^/@]+@[^:]+:", "", s)
    return re.sub(r"\.git$", "", s)


def repo_from_remote(path, remote, host=None):
    """owner/repo из remote. `host` защищает от чужого репозитория: имя remote совпало,
    а адрес ведёт на другой хостинг — значит это не он."""
    url = git(path, "remote", "get-url", remote)
    if host and host not in url:
        return ""
    return repo_slug(url)


def find_repo(start=None):
    """Каталог git-репозитория, в котором мы находимся."""
    top = git(start or pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    return pathlib.Path(top) if top else None


def course_repo(code):
    """Репозиторий курса внутри ~/work/study/<код>/."""
    d = ROOT / code
    if not d.is_dir():
        return None
    found = sorted(p.parent for p in d.glob("*/.git"))
    return found[0] if found else None


def tuis_dir(code):
    """Материалы для сдачи в ТУИС — рядом с предметом, а не внутри репозитория курса:
    в репозитории курса лежит только сама работа, преподаватель смотрит именно его."""
    return ROOT / code / "tuis"


def videos(code, num):
    """Состояние <код>/tuis/labNN.env — ссылок на скринкасты."""
    f = tuis_dir(code) / f"lab{num}.env"
    if not f.exists():
        return {"path": str(f), "exists": False, "filled": 0, "total": len(VIDEO_KEYS),
                "missing": list(VIDEO_KEYS), "values": {}}
    values = {}
    for line in f.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    missing = [k for k in VIDEO_KEYS if not values.get(k)]
    return {"path": str(f), "exists": True, "filled": len(VIDEO_KEYS) - len(missing),
            "total": len(VIDEO_KEYS), "missing": missing, "values": values}


def labs(repo, code):
    """Лабы репозитория: исходники, собранные файлы, ссылки на записи, заготовка ответа."""
    out = []
    for lab in sorted((repo / "labs").glob("lab*")) if (repo / "labs").is_dir() else []:
        item = {"num": lab.name.replace("lab", ""), "path": str(lab)}
        for kind in ("report", "presentation"):
            d = lab / kind
            pdfs = sorted(d.glob("_output/*.pdf")) if d.is_dir() else []
            item[kind] = {
                "source": bool(list(d.glob("*.qmd"))) if d.is_dir() else False,
                "pdf": str(pdfs[0]) if pdfs else None,
                "built": bool(pdfs),
            }
        item["videos"] = videos(code, item["num"])
        item["answer_draft"] = (tuis_dir(code) / f"lab{item['num']}.md").exists()
        item["attachments"] = [str(p) for p in sorted(lab.glob("*/_output/*.pdf"))]
        out.append(item)
    return out


def repo_state(repo):
    """Ветка, незакоммиченное, теги, адреса на хостингах."""
    changes = [line for line in git(repo, "status", "--porcelain").splitlines() if line]
    tags = git(repo, "tag").splitlines()
    return {
        "path": str(repo),
        "branch": git(repo, "branch", "--show-current"),
        "head": git(repo, "rev-parse", "--short", "HEAD"),
        "dirty": changes,
        "tags": tags,
        "last_tag": git(repo, "describe", "--tags", "--abbrev=0") or None,
        "remotes": {"gitverse": repo_from_remote(repo, "origin", "gitverse.ru") or None,
                    "sourcecraft": repo_from_remote(repo, "src", "sourcecraft") or None},
    }


def tag_sha(repo, tag):
    """Полный SHA коммита тега — GitVerse принимает только его."""
    return git(repo, "rev-parse", f"{tag}^{{commit}}", check=True)
