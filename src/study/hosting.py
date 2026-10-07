import mimetypes
import pathlib

from . import local, net
from .config import StudyError


def compact(pairs):
    return {k: v for k, v in pairs if v}


class Hosting:

    key = ""
    source = ""
    token_key = ""
    repo_key = ""
    remote = ""
    host = ""
    web = ""
    base = ""
    extra_headers = ()
    asset_field = "file"
    bad_ext = ()
    part_named = True

    def __init__(self, cfg, path=None, repo=None):
        self.cfg = cfg
        self.path = pathlib.Path(path) if path else None
        from_remote = self.path and local.repo_from_remote(self.path, self.remote, self.host)
        self.repo = repo or from_remote or cfg.get(self.repo_key)
        if not self.repo:
            raise StudyError(self.source,
                             f"репозиторий не задан: запуск из каталога репозитория "
                             f"(remote {self.remote}) или {self.repo_key} в config.env")

    def headers(self):
        auth = "Bearer " + self.cfg.token(self.token_key)
        return {"Authorization": auth, **dict(self.extra_headers)}

    def api(self, path, **kw):
        kw.setdefault("headers", {}).update(self.headers())
        return net.request(self.base + path, self.source, where=path, **kw)

    def repo_url(self):
        return f"{self.web}/{self.repo}"

    def asset(self, target, path, name=None):
        p = pathlib.Path(path)
        name = name or p.name
        if name.endswith(self.bad_ext):
            raise StudyError(self.source, f"{name}: {self.source} не принимает "
                                          f"{' и '.join(self.bad_ext)} — класть .md или zip")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        part = (self.part_named and name) or p.name
        self.api(self.asset_path(target, name),
                 files=[(self.asset_field, part, p.read_bytes(), ctype)], timeout=900)
        return {"name": name, "ok": True}


class GitVerse(Hosting):
    key = "gv"
    source = "gitverse"
    token_key = "GITVERSE_TOKEN"
    repo_key = "GV_REPO"
    remote = "origin"
    host = "gitverse.ru"
    web = "https://gitverse.ru"
    base = "https://api.gitverse.ru"

    extra_headers = (("Accept", "application/vnd.gitverse.object+json;version=1"),)
    asset_field = "attachment"
    part_named = False
    bad_ext = (".qmd", ".html")

    def asset_path(self, release_id, name):
        return f"/repos/{self.repo}/releases/{release_id}/assets?name={name}"

    def releases(self):
        out = self.api(f"/repos/{self.repo}/releases", retries=net.RETRIES) or []
        return [{"tag": r["tag_name"], "id": r["id"], "name": r.get("name"),
                 "assets": len(r.get("assets") or []),
                 "url": self.web_url(r["tag_name"])} for r in out]

    def release(self, tag, title, notes, sha=None):
        if not sha:
            if not self.path:
                raise StudyError(self.source, "нужен --sha или запуск из каталога репозитория")
            sha = local.tag_sha(self.path, tag)
        out = self.api(f"/repos/{self.repo}/releases",
                       json_body={"tag_name": tag, "target_commitish": sha, "name": title,
                                  "body": notes, "draft": False, "prerelease": False})
        return {"id": out["id"], "tag": out["tag_name"], "url": self.web_url(out["tag_name"])}

    def update(self, tag, title=None, notes=None):
        ids = {r["tag"]: r["id"] for r in self.releases()}
        if tag not in ids:
            raise StudyError(self.source, f"релиза {tag} нет")
        body = compact((("name", title), ("body", notes)))
        self.api(f"/repos/{self.repo}/releases/{ids[tag]}", method="PATCH", json_body=body)
        return {"id": ids[tag], "tag": tag, "url": self.web_url(tag)}

    def web_url(self, tag):
        return f"{self.repo_url()}/releases/tag/{tag}"


class SourceCraft(Hosting):
    key = "sc"
    source = "sourcecraft"
    token_key = "SOURCECRAFT_TOKEN"
    repo_key = "SC_REPO"
    remote = "src"
    host = "sourcecraft.dev"
    web = "https://sourcecraft.dev"
    base = "https://api.sourcecraft.tech"

    def releases(self):
        out = self.api(f"/repos/{self.repo}/releases", retries=net.RETRIES) or {}
        return [{"tag": r.get("tag"), "id": r.get("id"), "name": r.get("title"),
                 "status": r.get("status"), "assets": len(r.get("assets") or []),
                 "url": self.web_url(r.get("tag"))} for r in out.get("releases", [])]

    def localize(self, notes):
        gv = self.path and local.repo_from_remote(self.path, GitVerse.remote, GitVerse.host)
        if gv:
            notes = notes.replace(f"{GitVerse.web}/{gv}", self.repo_url())
        return notes

    def release(self, tag, title, notes, sha=None, branch=None):  # noqa: ARG002
        body = {"tag": tag, "title": title, "release_notes": self.localize(notes), "publish": True}
        if branch:
            body["target_branch"] = branch
        out = self.api(f"/repos/{self.repo}/releases", json_body=body) or {}
        return {"tag": out.get("tag", tag), "status": out.get("status"),
                "url": self.web_url(tag)}

    def update(self, tag, title=None, notes=None):
        fields = (("title", title), ("release_notes", notes and self.localize(notes)))
        body = compact(fields)
        self.api(f"/repos/{self.repo}/releases/tag/{tag}", method="PATCH", json_body=body)
        return {"tag": tag, "url": self.web_url(tag)}

    def asset_path(self, tag, _name):
        return f"/repos/{self.repo}/releases/tag/{tag}/attachments"

    def web_url(self, tag):
        return f"{self.repo_url()}/releases/{tag}"


HOSTS = {cls.key: cls for cls in (GitVerse, SourceCraft)}
