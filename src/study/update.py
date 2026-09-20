"""Обновление самого инструмента: .digest/ — это git-клон, origin ведёт на GitHub.

Проверка мягкая (fetch с таймаутом, без запросов пароля) и ничего не меняет; накатывает
только `study update` по явной команде — код работает с токенами, обновлять его молча
из задачи по расписанию нельзя. После pull блок в файлах операторов переписывается:
это наш текст, личное вне блока не трогается.
"""
from . import agent, local
from .config import HERE, StudyError

# Секунд на fetch: SSH-рукопожатие с GitHub из медленной сети занимает и 10 с; при молчании —
# одна повторная попытка, чтобы разовый тормоз не давал строку «Не удалось» в сводке.
FETCH_TIMEOUT = 20
FETCH_TRIES = 2
VERIFY_TIMEOUT = 10  # gpg локально; без ключа автора в связке подпись просто «не проверена»


def version(ref="HEAD"):
    """Версия по тегам: v1.2.0, v1.2.0-3-gabc1234 (три коммита после тега) или короткий SHA."""
    return local.git(HERE, "describe", "--tags", "--always", ref) or "?"


def check(fetch=True):
    """Что нового в origin относительно HEAD; None — .digest не git-клон с upstream."""
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
    # Что именно приедет: diff и подпись верхнего коммита — код работает с токенами,
    # и перед pull человек должен видеть, что тянет.
    stat = local.git(HERE, "diff", "--stat", "HEAD..@{u}") if commits else ""
    verified = local.run(HERE, "verify-commit", "@{u}", timeout=VERIFY_TIMEOUT) if commits else None
    return {"version": version(), "remote": version("@{u}"), "behind": len(commits),
            "ahead": int(local.git(HERE, "rev-list", "--count", "@{u}..HEAD") or 0),
            "commits": commits, "stat": stat,
            "signed": None if verified is None else verified.returncode == 0,
            "agents": [s for s in map(agent.status, agent.OPERATORS) if s["installed"]]}


def plan(d):
    """Что сделает `study update`: коммиты, затронутые файлы, подпись."""
    out = [f"Обновление study: {d['version']} → {d['remote']}"]
    out += [f"  {c}" for c in d["commits"]]
    out += [f" {ln}" for ln in d["stat"].splitlines()]   # у git уже один пробел
    out.append("Подпись коммита проверена." if d["signed"] else
               "Подпись коммита НЕ проверена: нет ключа автора в gpg или коммит не подписан.")
    return out


def apply(before=None):
    """git pull --ff-only, затем обновить блоки у установленных операторов.
    `before` — уже полученный check(), чтобы не ходить за fetch дважды."""
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
    """Строки в конец сводки: есть обновление / устарел блок агента. Пусто — всё актуально."""
    out = []
    if d and d["behind"]:
        n = d["behind"]
        word = "коммит" if n % 10 == 1 and n % 100 != 11 else "коммита" if 2 <= n % 10 <= 4 \
            and not 12 <= n % 100 <= 14 else "коммитов"
        out.append(f"Обновление study: {d['version']} → {d['remote']}, {n} {word} "
                   f"({'; '.join(d['commits'][:3])}{'; …' if n > 3 else ''}) — `study update`.")
    return out + stale(d)


def stale(d):
    """Строки про устаревшие блоки агента у операторов."""
    return [f"Блок агента в {s['file']} устарел — `study agent {s['operator']}`."
            for s in (d or {}).get("agents", []) if not s["current"]]
