"""GitVerse и SourceCraft за одним интерфейсом. Подробности — в ../hosting-api.md."""
import mimetypes
import pathlib

from . import local, net
from .config import StudyError


class Hosting:
    """Общий интерфейс: releases(), release(), asset(), web_url()."""

    name = ""
    source = ""
    token_key = ""
    repo_key = ""
    remote = ""
    host = ""

    def __init__(self, cfg, repo=None, path=None):
        self.cfg = cfg
        self.path = pathlib.Path(path) if path else None
        self.repo = repo or cfg.get(self.repo_key) or (
            local.repo_from_remote(self.path, self.remote, self.host) if self.path else "")
        if not self.repo:
            raise StudyError(self.source,
                             f"репозиторий не задан: {self.repo_key} в config.env "
                             f"или запуск из каталога репозитория (remote {self.remote})")

    def headers(self):
        return {"Authorization": "Bearer " + self.cfg.token(self.token_key)}

    def api(self, path, **kw):
        kw.setdefault("headers", {}).update(self.headers())
        return net.request(self.base + path, self.source, where=path, **kw)

    @staticmethod
    def _file(path):
        p = pathlib.Path(path)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return p.name, p.read_bytes(), ctype


class GitVerse(Hosting):
    name = "GitVerse"
    source = "gitverse"
    token_key = "GITVERSE_TOKEN_FILE"
    repo_key = "GV_REPO"
    remote = "origin"
    host = "gitverse.ru"
    base = "https://api.gitverse.ru"

    def headers(self):
        head = super().headers()
        # Без этого заголовка любой запрос отвечает 400 с пустым телом.
        head["Accept"] = "application/vnd.gitverse.object+json;version=1"
        return head

    def releases(self):
        """Ответ GitVerse — голый массив."""
        out = self.api(f"/repos/{self.repo}/releases") or []
        return [{"tag": r["tag_name"], "id": r["id"], "name": r.get("name"),
                 "assets": len(r.get("assets") or []),
                 "url": self.web_url(r["tag_name"])} for r in out]

    def release(self, tag, title, notes, sha=None):
        """target_commitish принимает только полный SHA коммита, имя ветки — 422."""
        if not sha:
            if not self.path:
                raise StudyError(self.source, "нужен --sha или запуск из каталога репозитория")
            sha = local.tag_sha(self.path, tag)
        out = self.api(f"/repos/{self.repo}/releases",
                       json_body={"tag_name": tag, "target_commitish": sha, "name": title,
                                  "body": notes, "draft": False, "prerelease": False})
        return {"id": out["id"], "tag": out["tag_name"], "url": self.web_url(out["tag_name"])}

    def asset(self, release_id, path, name=None):
        """Имя — query-параметром, файл — в поле attachment. .qmd и .html отвергаются."""
        fname, data, ctype = self._file(path)
        name = name or fname
        if name.endswith((".qmd", ".html")):
            raise StudyError(self.source, f"{name}: GitVerse не принимает .qmd и .html — "
                                          "класть .md или zip")
        self.api(f"/repos/{self.repo}/releases/{release_id}/assets?name={name}",
                 files=[("attachment", fname, data, ctype)], timeout=900)
        return {"name": name, "ok": True}

    def web_url(self, tag):
        return f"https://gitverse.ru/{self.repo}/releases/tag/{tag}"


class SourceCraft(Hosting):
    name = "SourceCraft"
    source = "sourcecraft"
    token_key = "SOURCECRAFT_TOKEN_FILE"
    repo_key = "SC_REPO"
    remote = "src"
    host = "sourcecraft"
    base = "https://api.sourcecraft.tech"

    def releases(self):
        """Ответ SourceCraft — объект {"releases": [...]} с другими именами полей."""
        out = self.api(f"/repos/{self.repo}/releases") or {}
        return [{"tag": r.get("tag"), "id": r.get("id"), "name": r.get("title"),
                 "status": r.get("status"), "assets": len(r.get("assets") or []),
                 "url": self.web_url(r.get("tag"))} for r in out.get("releases", [])]

    def release(self, tag, title, notes, sha=None, branch="master"):
        """REST вместо CLI src: те же поля, что у src release create --publish."""
        out = self.api(f"/repos/{self.repo}/releases",
                       json_body={"tag": tag, "target_branch": branch, "title": title,
                                  "release_notes": notes, "publish": True}) or {}
        return {"tag": out.get("tag", tag), "status": out.get("status"),
                "url": self.web_url(tag)}

    def asset(self, tag, path, name=None):
        """Файл грузится строго в поле file, ограничений по расширению нет."""
        fname, data, ctype = self._file(path)
        self.api(f"/repos/{self.repo}/releases/tag/{tag}/attachments",
                 files=[("file", name or fname, data, ctype)], timeout=900)
        return {"name": name or fname, "ok": True}

    def web_url(self, tag):
        return f"https://sourcecraft.dev/{self.repo}/releases/{tag}"


def both(cfg, path=None):
    """Пара хостингов для репозитория; недоступный отдаётся ошибкой, а не падением."""
    out = {}
    for cls in (GitVerse, SourceCraft):
        try:
            out[cls.source] = cls(cfg, path=path)
        except StudyError as e:
            out[cls.source] = e
    return out
