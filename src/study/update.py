from . import agent, local
from .config import HERE, StudyError

FETCH_TIMEOUT = 20
FETCH_TRIES = 2
VERIFY_TIMEOUT = 10


def version(ref="HEAD"):
    return local.git(HERE, "describe", "--tags", "--always", ref) or "?"


def check(fetch=True):
    if not (HERE / ".git").exists() or not local.git(HERE, "rev-parse", "--verify", "-q", "@{u}"):
        return None
    if fetch:
        for _ in range(FETCH_TRIES):
            r = local.run(HERE, "fetch", "--quiet", "--tags", timeout=FETCH_TIMEOUT)
            if r is not None:
                break
        if r is None or r.returncode:
            why = (r.stderr.strip() if r
                   else f"нет ответа за {FETCH_TIMEOUT} с, {FETCH_TRIES} попытки")
            raise StudyError("git", f"fetch не удался: {why}", where="update")
    commits = local.git(HERE, "log", "--format=%s", "HEAD..@{u}").splitlines()
    stat = local.git(HERE, "diff", "--stat", "HEAD..@{u}") if commits else ""
    verified = local.run(HERE, "verify-commit", "@{u}", timeout=VERIFY_TIMEOUT) if commits else None
    return {"version": version(), "remote": version("@{u}"), "behind": len(commits),
            "ahead": int(local.git(HERE, "rev-list", "--count", "@{u}..HEAD") or 0),
            "commits": commits, "stat": stat,
            "signed": None if verified is None else verified.returncode == 0,
            "agents": [s for s in map(agent.status, agent.OPERATORS) if s["installed"]]}


def plan(d):
    out = [f"Обновление study: {d['version']} → {d['remote']}"]
    out += [f"  {c}" for c in d["commits"]]
    out += [f" {ln}" for ln in d["stat"].splitlines()]
    out.append("Подпись коммита проверена." if d["signed"] else
               "Подпись коммита НЕ проверена: нет ключа автора в gpg или коммит не подписан.")
    return out


def apply(before=None):
    before = before or check()
    if before is None:
        raise StudyError("git", f"{HERE} — не git-клон с upstream, обновлять нечего",
                         where="update")
    if before["behind"]:
        local.git(HERE, "pull", "--ff-only", "--quiet", check=True, timeout=60)
    refreshed = [agent.install(s["operator"])["file"] for s in before["agents"]
                 if before["behind"] or not s["current"]]
    return {**before, "updated": bool(before["behind"]), "now": version(), "refreshed": refreshed}


def note(d):
    out = []
    if d and d["behind"]:
        n = d["behind"]
        word = "коммит" if n % 10 == 1 and n % 100 != 11 else "коммита" if 2 <= n % 10 <= 4 \
            and not 12 <= n % 100 <= 14 else "коммитов"
        out.append(f"Обновление study: {d['version']} → {d['remote']}, {n} {word} "
                   f"({'; '.join(d['commits'][:3])}{'; …' if n > 3 else ''}) — `study update`.")
    return out + stale(d)


def stale(d):
    return [f"Блок агента в {s['file']} устарел — `study agent {s['operator']}`."
            for s in (d or {}).get("agents", []) if not s["current"]]
