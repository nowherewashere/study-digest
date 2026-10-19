import os
import pathlib
import re
import subprocess
import sys

from .config import ToolError


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
        raise ToolError("git", f"нет ответа за {timeout} с", where=where)
    if r is None or r.returncode:
        if r and check:
            raise ToolError("git", (r.stderr or r.stdout).strip() or "ошибка", where=where)
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


def tag_sha(repo, tag):
    return git(repo, "rev-parse", f"{tag}^{{commit}}", check=True)
