"""Локальное состояние: git, репозиторий курса, лабы, собранные файлы."""
import os
import pathlib
import re
import subprocess
import sys

from .config import ROOT, StudyError

# Ссылки на скринкасты в <код>/tuis/labNN.env: плейлист и четыре записи на двух площадках.
SITES = {"RUTUBE": "Rutube", "VK": "VKvideo"}
SLOTS = {"LAB": "Выполнение лабораторной работы", "REPORT": "Подготовка отчёта",
         "PRESENTATION": "Подготовка презентации", "DEFENSE": "Защита лабораторной работы"}
VIDEO_KEYS = [f"{site}_{slot}" for site in SITES for slot in ["PLAYLIST", *SLOTS]]
# Каталоги работ в репозитории курса: labs/labNN и homework/hwNN.
WORK_DIRS = {"lab": "labs", "hw": "homework"}


def run(path, *args, timeout=None):
    """CompletedProcess команды git в каталоге path; None — не дождались за timeout.
    Без терминала (задача по расписанию) сеть идёт без запросов пароля, чтобы не зависнуть."""
    env = dict(os.environ)
    if not sys.stdin.isatty():
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    try:
        return subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                              encoding="utf-8", errors="replace", check=False,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return None


def git(path, *args, check=False, timeout=None):
    """stdout команды git; при ошибке или таймауте — "" (StudyError, если check)."""
    r = run(path, *args, timeout=timeout)
    if r is None:
        if check:
            raise StudyError("git", f"нет ответа за {timeout} с", where=" ".join(args))
        return ""
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


def flow_of(cfg, code):
    """Профиль сдачи курса: строка FLOW в config.env, а без неё — release, если в папке курса
    есть репозиторий, иначе file."""
    cid = next((i for i, c in cfg.codes().items() if c == code), None)
    return cfg.flows().get(cid) or ("release" if course_repo(code) else "file")


def tuis_dir(code):
    """Материалы для сдачи в ТУИС — рядом с предметом, а не внутри репозитория курса:
    в репозитории курса лежит только сама работа, преподаватель смотрит именно его."""
    return ROOT / code / "tuis"


def work_id(num):
    """'01' → ('lab', '01'); 'hw1' → ('hw', '01')."""
    num = str(num).strip().lower()
    kind = "hw" if num.startswith("hw") else "lab"
    return kind, re.sub(r"^(hw|lab)", "", num).zfill(2)


def videos(code, num, kind="lab"):
    """Состояние <код>/tuis/<kind>NN.env — ссылок на скринкасты."""
    f = tuis_dir(code) / f"{kind}{num}.env"
    if not f.exists():
        return {"path": str(f), "exists": False, "filled": 0, "total": len(VIDEO_KEYS),
                "missing": list(VIDEO_KEYS), "values": {}}
    values = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    missing = [k for k in VIDEO_KEYS if not values.get(k)]
    return {"path": str(f), "exists": True, "filled": len(VIDEO_KEYS) - len(missing),
            "total": len(VIDEO_KEYS), "missing": missing, "values": values}


def labs(repo, code):
    """Лабы репозитория: исходники, собранные файлы, ссылки на записи, заготовка ответа."""
    out = []
    for lab in sorted((repo / WORK_DIRS["lab"]).glob("lab*")):
        item = {"num": lab.name[3:], "path": str(lab)}
        for kind in ("report", "presentation"):
            pdfs = sorted((lab / kind).glob("_output/*.pdf"))
            item[kind] = {"source": any((lab / kind).glob("*.qmd")),
                          "pdf": str(pdfs[0]) if pdfs else None, "built": bool(pdfs)}
        item["videos"] = videos(code, item["num"])
        item["answer_draft"] = (tuis_dir(code) / f"lab{item['num']}.md").exists()
        item["attachments"] = [str(p) for p in sorted(lab.glob("*/_output/*.pdf"))]
        out.append(item)
    return out


def repo_state(repo):
    """Ветка, незакоммиченное, теги. Адреса на хостингах знает hosting.py, он их и дописывает."""
    return {
        "path": str(repo),
        "branch": git(repo, "branch", "--show-current"),
        "head": git(repo, "rev-parse", "--short", "HEAD"),
        "dirty": [line for line in git(repo, "status", "--porcelain").splitlines() if line],
        "tags": git(repo, "tag").splitlines(),
        "last_tag": git(repo, "describe", "--tags", "--abbrev=0") or None,
    }


def tag_sha(repo, tag):
    """Полный SHA коммита тега — GitVerse принимает только его."""
    return git(repo, "rev-parse", f"{tag}^{{commit}}", check=True)
