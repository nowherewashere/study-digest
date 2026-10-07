import json
import unittest
from unittest import mock

from study import local
from study.config import StudyError
from study.hosting import HOSTS, GitVerse, SourceCraft
from tests.fakes import FakeNet, config, patch, tmpdir

SHA = "0123456789abcdef0123456789abcdef01234567"
REMOTES = {("remote", "get-url", "origin"): "ssh://git@gitverse.ru:2222/me/course.git",
           ("remote", "get-url", "src"): "ssh://ssh.sourcecraft.dev/org/course.git",
           ("rev-parse", "v1.1.0^{commit}"): SHA}


class HostingCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tmpdir(self)
        self.net = FakeNet().install(self)
        self.cfg = config(self.tmp, "GV_REPO=cfg/gv\nSC_REPO=cfg/sc\n")
        self.gits = []
        patch(self, local, "git", self.git)
        self.notes = self.tmp / "notes.md"
        self.notes.write_text("см. https://gitverse.ru/me/course/commit/abc\n", encoding="utf-8")

    def git(self, path, *args, check=False, timeout=None):
        self.gits.append(args)
        self.assertEqual((path, timeout), (self.tmp, None))
        out = REMOTES.get(args, "")
        if check and not out:
            raise StudyError("git", "ошибка", where=" ".join(args))
        return out


class RepoChoiceTest(HostingCase):
    def test_explicit_then_remote_then_config(self):
        self.assertEqual(GitVerse(self.cfg, path=self.tmp, repo="x/y").repo, "x/y")
        self.assertEqual(GitVerse(self.cfg, path=self.tmp).repo, "me/course")
        self.assertEqual(SourceCraft(self.cfg, path=self.tmp).repo, "org/course")
        self.assertEqual(GitVerse(self.cfg).repo, "cfg/gv")
        self.assertEqual(SourceCraft(self.cfg).repo, "cfg/sc")

    def test_foreign_remote_ignored(self):
        with mock.patch.dict(REMOTES, {("remote", "get-url", "origin"):
                                       "git@github.com:me/course.git"}):
            self.assertEqual(GitVerse(self.cfg, path=self.tmp).repo, "cfg/gv")
        with self.assertRaises(StudyError) as e:
            GitVerse(config(self.tmp))
        self.assertIn("GV_REPO", e.exception.message)
        self.assertEqual(HOSTS["gv"], GitVerse)
        self.assertEqual(HOSTS["sc"], SourceCraft)


class GitVerseTest(HostingCase):
    def setUp(self):
        super().setUp()
        self.gv = GitVerse(self.cfg, path=self.tmp)

    def test_headers_and_releases(self):
        self.net.reply("GET", "/repos/me/course/releases",
                       [{"id": 7, "tag_name": "v1.1.0", "name": "ЛР 1", "assets": [{"id": 1}]},
                        {"id": 3, "tag_name": "v1.0.0", "name": None, "assets": None}])
        rows = self.gv.releases()
        req = self.net.sent[0]
        self.assertEqual(req["url"], "https://api.gitverse.ru/repos/me/course/releases")
        self.assertEqual(req["headers"],
                         {"Authorization": "Bearer gv-token",
                          "Accept": "application/vnd.gitverse.object+json;version=1"})
        self.assertEqual(rows, [{"tag": "v1.1.0", "id": 7, "name": "ЛР 1", "assets": 1,
                                 "url": "https://gitverse.ru/me/course/releases/tag/v1.1.0"},
                                {"tag": "v1.0.0", "id": 3, "name": None, "assets": 0,
                                 "url": "https://gitverse.ru/me/course/releases/tag/v1.0.0"}])
        self.net.reply("GET", "/releases", None)
        self.assertEqual(self.gv.releases(), [])

    def test_release_sha_from_tag(self):
        self.net.reply("POST", "/repos/me/course/releases", {"id": 9, "tag_name": "v1.1.0"})
        out = self.gv.release("v1.1.0", "ЛР 1", self.notes.read_text(encoding="utf-8"))
        self.assertEqual(out, {"id": 9, "tag": "v1.1.0",
                               "url": "https://gitverse.ru/me/course/releases/tag/v1.1.0"})
        self.assertIn(("rev-parse", "v1.1.0^{commit}"), self.gits)
        req = self.net.sent[0]
        self.assertEqual(req["headers"]["Content-Type"], "application/json")
        self.assertEqual(req["json_body"], {"tag_name": "v1.1.0", "target_commitish": SHA,
                                            "name": "ЛР 1",
                                            "body": "см. https://gitverse.ru/me/course/commit/abc\n",
                                            "draft": False, "prerelease": False})
        self.assertFalse(req["data"].endswith(b"\n"))
        self.assertEqual(req["data"], json.dumps(req["json_body"], ensure_ascii=False).encode())

    def test_release_explicit_sha_or_no_path(self):
        self.net.reply("POST", "/releases", {"id": 1, "tag_name": "v2"})
        self.gv.release("v2", "t", "n", sha="f" * 40)
        self.assertEqual(self.net.sent[0]["json_body"]["target_commitish"], "f" * 40)
        self.assertNotIn(("rev-parse", "v2^{commit}"), self.gits)
        with self.assertRaises(StudyError) as e:
            GitVerse(self.cfg, repo="a/b").release("v2", "t", "n")
        self.assertIn("--sha", e.exception.message)

    def test_update_by_id(self):
        self.net.reply("GET", "/releases", [{"id": 7, "tag_name": "v1.1.0", "assets": []}])
        self.net.reply("PATCH", "/repos/me/course/releases/7", {"id": 7})
        out = self.gv.update("v1.1.0", notes="новое описание")
        self.assertEqual(out["id"], 7)
        self.assertEqual(self.net.sent[1]["json_body"], {"body": "новое описание"})
        self.net.reply("GET", "/releases", [])
        with self.assertRaises(StudyError) as e:
            self.gv.update("v9", title="x")
        self.assertEqual(e.exception.message, "релиза v9 нет")

    def test_asset(self):
        f = self.tmp / "report.pdf"
        f.write_bytes(b"%PDF-1.4")
        self.net.reply("POST", "/repos/me/course/releases/7/assets?name=lab01-report.pdf",
                       {"id": 1})
        self.assertEqual(self.gv.asset(7, f, name="lab01-report.pdf"),
                         {"name": "lab01-report.pdf", "ok": True})
        req = self.net.sent[0]
        self.assertEqual(req["files"],
                         {"attachment": ("report.pdf", b"%PDF-1.4", "application/pdf")})
        self.assertEqual((req["fields"], req["timeout"]), ({}, 900))
        for bad in ("slides.html", "report.qmd"):
            with self.assertRaises(StudyError) as e:
                self.gv.asset(7, f, name=bad)
            self.assertIn("не принимает .qmd и .html", e.exception.message)
        self.assertEqual(len(self.net.sent), 1)

    def test_api_error(self):
        self.net.reply("GET", "/x", StudyError("gitverse", "HTTP 400 (пустой ответ)", where="/x"))
        with self.assertRaises(StudyError):
            self.gv.api("/x")


class SourceCraftTest(HostingCase):
    def setUp(self):
        super().setUp()
        self.sc = SourceCraft(self.cfg, path=self.tmp)

    def test_headers_and_releases(self):
        self.net.reply("GET", "/repos/org/course/releases",
                       {"releases": [{"id": "r1", "tag": "v1.1.0", "title": "ЛР 1",
                                      "status": "PUBLISHED",
                                      "assets": [{"name": "a"}, {"name": "b"}]}]})
        rows = self.sc.releases()
        req = self.net.sent[0]
        self.assertEqual(req["url"], "https://api.sourcecraft.tech/repos/org/course/releases")
        self.assertEqual(req["headers"], {"Authorization": "Bearer sc-token"})
        self.assertEqual(rows, [{"tag": "v1.1.0", "id": "r1", "name": "ЛР 1",
                                 "status": "PUBLISHED", "assets": 2,
                                 "url": "https://sourcecraft.dev/org/course/releases/v1.1.0"}])
        self.net.reply("GET", "/releases", {})
        self.assertEqual(self.sc.releases(), [])

    def test_localize(self):
        self.assertEqual(self.sc.localize("a https://gitverse.ru/me/course/commit/abc b"),
                         "a https://sourcecraft.dev/org/course/commit/abc b")
        other = "https://gitverse.ru/other/repo/commit/abc"
        self.assertEqual(self.sc.localize(other), other)

    def test_release_localized_no_branch(self):
        self.net.reply("POST", "/repos/org/course/releases",
                       {"tag": "v1.1.0", "status": "PUBLISHED"})
        out = self.sc.release("v1.1.0", "ЛР 1", self.notes.read_text(encoding="utf-8"), sha=SHA)
        self.assertEqual(out, {"tag": "v1.1.0", "status": "PUBLISHED",
                               "url": "https://sourcecraft.dev/org/course/releases/v1.1.0"})
        self.assertEqual(self.net.sent[0]["json_body"],
                         {"tag": "v1.1.0", "title": "ЛР 1", "publish": True,
                          "release_notes": "см. https://sourcecraft.dev/org/course/commit/abc\n"})
        self.assertNotIn(("rev-parse", "v1.1.0^{commit}"), self.gits)
        self.net.reply("POST", "/releases", None)
        out = self.sc.release("v1.2.0", "t", "n", branch="master")
        self.assertEqual((out["tag"], out["status"]), ("v1.2.0", None))
        self.assertEqual(self.net.sent[1]["json_body"]["target_branch"], "master")

    def test_update_by_tag(self):
        self.net.reply("PATCH", "/repos/org/course/releases/tag/v1.1.0", {})
        out = self.sc.update("v1.1.0", title="T", notes="x https://gitverse.ru/me/course")
        self.assertEqual(out, {"tag": "v1.1.0",
                               "url": "https://sourcecraft.dev/org/course/releases/v1.1.0"})
        self.assertEqual(self.net.sent[0]["json_body"],
                         {"title": "T", "release_notes": "x https://sourcecraft.dev/org/course"})

    def test_asset_any_extension(self):
        f = self.tmp / "slides.html"
        f.write_text("<html>", encoding="utf-8")
        self.net.reply("POST", "/repos/org/course/releases/tag/v1.1.0/attachments", {})
        self.assertEqual(self.sc.asset("v1.1.0", f), {"name": "slides.html", "ok": True})
        self.assertEqual(self.net.sent[0]["files"],
                         {"file": ("slides.html", b"<html>", "text/html")})
        self.assertNotIn("?name=", self.net.sent[0]["url"])
