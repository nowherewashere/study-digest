import pathlib
import re
import tempfile
import zipfile

from hosting.client import HOSTS
from kit import git
from kit.config import ToolError

from .lab import lab_id

VERSION_HEAD = re.compile(r"^#{1,3} \[?v?(\d+\.\d+\.\d+)\b")


def changelog(repo, tag):
    path = repo / "CHANGELOG.md"
    if not path.exists():
        return None
    out, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        m = VERSION_HEAD.match(line)
        if m:
            if inside:
                break
            inside = m.group(1) == tag.lstrip("v")
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip() if inside else None


def zip_tree(target, roots, skip=("_output",)):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for root, arc in roots:
            for p in sorted(root.rglob("*")):
                rel = p.relative_to(root)
                if p.is_file() and not set(rel.parts) & set(skip):
                    z.write(p, f"{arc}/{rel.as_posix()}" if arc else rel.as_posix())


def files(course, num):
    lab, base = course.lab(num), course.base(num)
    rep, pres = lab / "report", lab / "presentation"
    plain = [(f"{base}-report.pdf", rep / "_output" / f"{base}-report.pdf"),
             (f"{base}-report.docx", rep / "_output" / f"{base}-report.docx"),
             (f"{base}-report.md", rep / f"{base}-report.qmd"),
             (f"{base}-presentation.pdf", pres / "_output" / f"{base}-presentation.pdf"),
             (f"{base}-presentation.md", pres / f"{base}-presentation.qmd")]
    html = pres / "_output" / f"{base}-presentation.html"
    missing = [str(p.relative_to(course.repo)) for _, p in plain if not p.is_file()]
    if not html.is_file():
        missing.append(str(html.relative_to(course.repo)))
    names = [n for n, _ in plain] + [f"{base}-presentation-html.zip", f"{base}-sources.zip"]
    return names, plain, html, missing


def stage(course, num, plain, html, tmp):
    base = course.base(num)
    out = dict(plain)
    z = tmp / f"{base}-presentation-html.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.write(html, html.name)
        img = html.parent / "image"
        for p in sorted(img.rglob("*")) if img.is_dir() else []:
            if p.is_file():
                f.write(p, p.relative_to(html.parent).as_posix())
    out[z.name] = z
    src = tmp / f"{base}-sources.zip"
    lab = course.lab(num)
    zip_tree(src, [(lab / "report", "report"), (lab / "presentation", "presentation")])
    out[src.name] = src
    return out


def pushed(repo, remote, tag):
    return bool(git.git(repo, "ls-remote", "--tags", remote, f"refs/tags/{tag}", timeout=30))


def lab_of(title):
    m = re.search(r"№\s*(\d+)", title or "")
    return int(m.group(1)) if m else None


def plan(cfg, course, num, tag=None):
    num = lab_id(num)
    tag = tag or course.latest_tag()
    problems = []
    if not course.lab(num).is_dir():
        raise ToolError("labrelease", f"нет каталога {course.lab(num)}")
    if not tag:
        problems.append("тегов нет: релиз делается через git flow release")
    names, plain, html, missing = files(course, num)
    if missing:
        problems.append("не собрано: " + ", ".join(missing) + " — make в report/ и presentation/")
    notes = changelog(course.repo, tag) if tag else None
    if tag and notes is None:
        problems.append(f"в CHANGELOG.md нет раздела {tag.lstrip('v')}: забыт bump version "
                        "в package.json перед standard-changelog")
    title = f"{tag} — Лабораторная работа № {int(num)}"
    hosts = []
    for source, cls in HOSTS.items():
        h = cls(cfg, path=course.repo)
        if tag and not pushed(course.repo, cls.remote, tag):
            problems.append(f"тег {tag} не отправлен в {cls.remote}: "
                            f"git push {cls.remote} master develop --tags")
        found = next((r for r in h.releases() if r["tag"] == tag), None) if tag else None
        if found and lab_of(found.get("name")) not in (None, int(num)):
            problems.append(f"{source}: релиз {tag} уже занят под «{found['name']}»")
        have = set(found["assets"]) if found else set()
        hosts.append({"source": source, "client": h, "release": found,
                      "create": found is None, "upload": [n for n in names if n not in have]})
    return {"code": course.code, "num": num, "tag": tag, "title": title, "notes": notes,
            "files": names, "plain": plain, "html": html, "problems": problems, "hosts": hosts}


def apply(course, p):
    done = []
    with tempfile.TemporaryDirectory() as tmp:
        staged = None
        for h in p["hosts"]:
            c = h["client"]
            rel = h["release"] or c.release(p["tag"], p["title"], p["notes"])
            for name in h["upload"]:
                if staged is None:
                    staged = stage(course, p["num"], p["plain"], p["html"], pathlib.Path(tmp))
                c.asset(c.target(rel), staged[name], name)
            done.append({"source": h["source"], "created": h["create"], "uploaded": h["upload"],
                         "url": c.web_url(p["tag"])})
    return done


def public(p):
    return {**{k: v for k, v in p.items() if k not in ("plain", "html", "hosts")},
            "hosts": [{"source": h["source"], "create": h["create"], "upload": h["upload"]}
                      for h in p["hosts"]]}


def render(p):
    out = [f"Релиз {p['tag'] or '?'} · {p['title']}"]
    for h in p["hosts"]:
        head = "создать релиз" if h["create"] else "релиз есть"
        files_ = ", ".join(h["upload"]) if h["upload"] else "все файлы на месте"
        out.append(f"  {h['source']}: {head}; загрузить: {files_}")
    if p["problems"]:
        out += ["", "Нельзя выпускать:"] + [f"  – {x}" for x in p["problems"]]
    return "\n".join(out)
