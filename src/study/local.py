import os
import pathlib
import re
import subprocess
import sys

from .config import ROOT, StudyError

SITES = {"RUTUBE": "Rutube", "VK": "VKvideo"}
SLOTS = {"LAB": "Выполнение лабораторной работы", "REPORT": "Подготовка отчёта",
         "PRESENTATION": "Подготовка презентации", "DEFENSE": "Защита лабораторной работы"}
VIDEO_KEYS = [f"{site}_{slot}" for site in SITES for slot in ["PLAYLIST", *SLOTS]]
LABS_DIR = "labs"


def run(path, *args, timeout=None):
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
    r = run(path, *args, timeout=timeout)
    where = " ".join(args)
    if r is None and check:
        raise StudyError("git", f"нет ответа за {timeout} с", where=where)
    if r is None or r.returncode:
        if r and check:
            raise StudyError("git", (r.stderr or r.stdout).strip() or "ошибка", where=where)
        return ""
    return r.stdout.strip()


def repo_slug(url):
    return re.sub(r"\.git$", "", re.sub(
        r"^(?:[a-z]+://(?:[^@/]+@)?[^/]+/|[^/@]+@[^:]+:)", "", url or ""))


def repo_from_remote(path, remote, host=None):
    url = git(path, "remote", "get-url", remote)
    if host and host not in url:
        return ""
    return repo_slug(url)


def find_repo(start=None):
    top = git(start or pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    return pathlib.Path(top) if top else None


def course_repo(code):
    d = ROOT / code
    if not d.is_dir():
        return None
    found = sorted(p.parent for p in d.glob("*/.git"))
    return found[0] if found else None


def flow_of(cfg, code):
    cid = next((i for i, c in cfg.codes().items() if c == code), None)
    return cfg.flows().get(cid) or ("release" if course_repo(code) else "file")


def tuis_dir(code):
    return ROOT / code / "tuis"


def lab_id(num):
    m = re.fullmatch(r"(?:lab)?(\d{1,2})", str(num).strip().lower())
    if not m:
        raise StudyError("local", f"ожидается номер лабораторной (NN), а не «{num}»")
    return m.group(1).zfill(2)


def videos(code, num):
    f = tuis_dir(code) / f"lab{num}.env"
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
    out = []
    for lab in sorted((repo / LABS_DIR).glob("lab*")):
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
    return {
        "path": str(repo),
        "branch": git(repo, "branch", "--show-current"),
        "head": git(repo, "rev-parse", "--short", "HEAD"),
        "dirty": [line for line in git(repo, "status", "--porcelain").splitlines() if line],
        "tags": git(repo, "tag").splitlines(),
        "last_tag": git(repo, "describe", "--tags", "--abbrev=0") or None,
    }


def tag_sha(repo, tag):
    return git(repo, "rev-parse", f"{tag}^{{commit}}", check=True)
