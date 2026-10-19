import shutil

from kit.cli import table
from kit.config import HERE, ROOT

SOURCE = HERE / "docs" / "agent.md"
SKILLS = HERE / "skills"
OWNER = "source: study-digest"
OPERATORS = {
    "claude": ("Claude Code", "CLAUDE.md", ".claude/skills"),
    "codex": ("OpenAI Codex; тот же AGENTS.md читают Cursor, Copilot coding agent, Jules, Zed",
              "AGENTS.md", ".agents/skills"),
    "gemini": ("Gemini CLI", "GEMINI.md", ".agents/skills"),
    "copilot": ("GitHub Copilot в редакторе", ".github/copilot-instructions.md", ".agents/skills"),
}
MARK = "<!-- study:begin"
BEGIN = MARK + " — блок обновляет `study agent`; править .digest/docs/agent.md -->"
END = "<!-- study:end -->"


def block():
    text = SOURCE.read_text(encoding="utf-8").strip()
    return f"{BEGIN}\n{text}\n{END}\n"


def tree(path):
    return {p.relative_to(path).as_posix(): p.read_bytes()
            for p in sorted(path.rglob("*")) if p.is_file()}


def wanted():
    return {d.name: tree(d) for d in sorted(SKILLS.iterdir()) if (d / "SKILL.md").is_file()} \
        if SKILLS.is_dir() else {}


def ours(skill_dir):
    head = skill_dir / "SKILL.md"
    return head.is_file() and OWNER in head.read_text(encoding="utf-8").split("\n---", 1)[0]


def present(base):
    return {d.name: tree(d) for d in sorted(base.iterdir()) if d.is_dir() and ours(d)} \
        if base.is_dir() else {}


def skills_diff(operator):
    base = ROOT / OPERATORS[operator][2]
    want, have = wanted(), present(base)
    return {"dir": OPERATORS[operator][2],
            "write": [n for n in want if have.get(n) != want[n]],
            "remove": [n for n in have if n not in want]}


def status(operator):
    name, rel, skills = OPERATORS[operator]
    path = ROOT / rel
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    has_block = MARK in text and END in text
    diff = skills_diff(operator)
    return {"operator": operator, "name": name, "path": str(path), "file": rel,
            "exists": path.exists(), "installed": has_block, "skills": skills,
            "skills_stale": diff["write"] + diff["remove"],
            "current": has_block and block() in text and not (diff["write"] or diff["remove"])}


def sync_skills(operator):
    base = ROOT / OPERATORS[operator][2]
    diff, want = skills_diff(operator), wanted()
    for name in diff["remove"]:
        shutil.rmtree(base / name)
    for name in diff["write"]:
        target = base / name
        if target.exists():
            shutil.rmtree(target)
        for rel, data in want[name].items():
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            (target / rel).write_bytes(data)


def install(operator):
    path = ROOT / OPERATORS[operator][1]
    new = block()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    i, j = text.find(MARK), text.find(END)
    if 0 <= i < j:
        rest = text[j + len(END):]
        text = text[:i] + new + (rest[1:] if rest.startswith("\n") else rest)
    elif text:
        text = text.rstrip("\n") + "\n\n" + new
    else:
        text = new
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    sync_skills(operator)
    return status(operator)


def render(rows, installed=False):
    state = {True: "актуален", False: "устарел", None: "нет"}
    lines = [table([[r["operator"], r["file"], r["skills"],
                     state[r["current"] if r["installed"] else None], r["name"]] for r in rows],
                   ["код", "файл", "скиллы", "блок", "кто читает"])]
    if installed:
        lines += ["", "Записано: " + ", ".join(r["path"] for r in rows),
                  ("Личные правила — в том же файле вне блока study:begin…study:end; "
                   "свои скиллы рядом не трогаются.")]
    else:
        lines += ["", ("Поставить: study agent <код> [<код>…]  (блок в корне учебной директории, "
                       "скиллы — в каталог скиллов оператора)")]
    return "\n".join(lines)
