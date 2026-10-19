import argparse
import io
import re
import unittest
import zipfile

from kit.config import ToolError
from labrelease import answer, cli, lab, publish
from tests.fakes import FakeNet, config, git, patch, repo, tmpdir

GV = "api.gitverse.ru/repos/me/nettech"
SC = "api.sourcecraft.tech/repos/org/nettech"
CHANGELOG = ("# 1.1.0 (2026-10-10)\n\n### Features\n\n* **lab01:** стенд\n\n"
             "# 1.0.0 (2026-09-01)\n\n* init\n")


class CourseCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tmpdir(self)
        self.cfg = config(self.tmp, "GV_REPO=cfg/gv\nSC_REPO=cfg/sc\n")
        self.repo = self.tmp / "nettech" / "2026-study-nettech"
        self.repo.mkdir(parents=True)
        (self.repo / "COURSE").write_text("nettech\n", encoding="utf-8")
        (self.repo / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        repo(self.repo, {"origin": "ssh://git@gitverse.ru:2222/me/nettech.git",
                         "src": "ssh://ssh.sourcecraft.dev/org/nettech.git"}, tag="v1.1.0")
        self.lab = self.repo / "labs" / "lab01"
        for part, files in (("report", ("report.pdf", "report.docx")),
                            ("presentation", ("presentation.pdf", "presentation.html"))):
            out = self.lab / part / "_output"
            (out / "image").mkdir(parents=True)
            (out / "image" / "fig.png").write_bytes(b"PNG")
            for f in files:
                (out / f"nettech-lab01-{f}").write_bytes(f.encode())
            (self.lab / part / f"nettech-lab01-{part}.qmd").write_text(f"# {part}\n",
                                                                       encoding="utf-8")
            (self.lab / part / "image").mkdir()
            (self.lab / part / "image" / "src.png").write_bytes(b"SRC")
        self.course = lab.Course(self.repo)
        self.env = self.tmp / "nettech" / "tuis" / "lab01.env"


class CourseTest(CourseCase):
    def test_course_from_marker(self):
        self.assertEqual((self.course.code, self.course.tuis, self.course.latest_tag()),
                         ("nettech", self.tmp / "nettech" / "tuis", "v1.1.0"))
        self.assertEqual(self.course.lab("01"), self.lab)
        self.assertEqual(lab.current(self.lab).repo, self.repo)
        (self.repo / "COURSE").unlink()
        with self.assertRaises(ToolError) as e:
            lab.current(self.lab)
        self.assertIn("нет файла COURSE", e.exception.message)
        with self.assertRaises(ToolError) as e:
            lab.current(self.tmp)
        self.assertIn("не git-репозиторий", e.exception.message)


class AnswerTest(CourseCase):

    def test_first_run_creates_env(self):
        d = answer.build(self.cfg, self.course, "1")
        self.assertEqual(d, {"created": str(self.env), "path": None, "text": None, "blocked": [],
                             "missing": lab.VIDEO_KEYS})
        self.assertTrue(self.env.read_text(encoding="utf-8").startswith(lab.TEMPLATE))
        self.assertEqual(self.env.read_text(encoding="utf-8").count("=\n"), 10)
        self.assertIn(f"--env {self.env}", answer.render(d))
        self.assertFalse(self.env.with_suffix(".md").exists())

    def test_text_and_attachments(self):
        self.env.parent.mkdir(parents=True)
        self.env.write_text("RUTUBE_PLAYLIST=https://rutube.ru/plst/1/\n"
                            "RUTUBE_LAB=https://rutube.ru/video/a/\n"
                            "VK_DEFENSE=https://vk.com/video-1_4\n", encoding="utf-8")
        d = answer.build(self.cfg, self.course, "lab01")
        self.assertEqual(d["text"],
                         "- Скринкасты, Rutube: [плейлист](https://rutube.ru/plst/1/)\n"
                         "  - [Выполнение лабораторной работы](https://rutube.ru/video/a/)\n"
                         "- Скринкасты, VKvideo:\n"
                         "  - [Защита лабораторной работы](https://vk.com/video-1_4)\n"
                         "- Репозиторий и релиз:\n"
                         "  - [gitverse](https://gitverse.ru/me/nettech), "
                         "[релиз v1.1.0](https://gitverse.ru/me/nettech/releases/tag/v1.1.0)\n"
                         "  - [sourcecraft](https://sourcecraft.dev/org/nettech), "
                         "[релиз v1.1.0](https://sourcecraft.dev/org/nettech/releases/v1.1.0)\n")
        self.assertEqual((d["tag"], d["created"], d["path"], d["blocked"]),
                         ("v1.1.0", None, str(self.env.with_suffix(".md")), []))
        self.assertEqual(d["attachments"],
                         [str(self.lab / "report/_output/nettech-lab01-report.pdf"),
                          str(self.lab / "presentation/_output/nettech-lab01-presentation.pdf")])
        self.assertEqual(len(d["missing"]), 7)
        self.assertEqual(self.env.with_suffix(".md").read_text(encoding="utf-8"), d["text"])
        text = answer.render(d)
        self.assertIn(f"study task nettech 01 → id задания → study submit <id> --text "
                      f"{d['path']} --attach {d['attachments'][0]} ", text)
        self.assertIn("Пусто в .env (в ответ не попадёт): RUTUBE_REPORT, ", text)

    def test_wrong_video_blocks_answer(self):
        net = FakeNet().install(self)
        good, old = "a" * 32, "b" * 32
        self.env.parent.mkdir(parents=True)
        self.env.write_text(f"RUTUBE_LAB=https://rutube.ru/video/{good}/\n"
                            f"RUTUBE_DEFENSE=https://rutube.ru/video/{old}/\n", encoding="utf-8")
        net.reply("GET", f"/v2/video/{old}/", {"title": "infosec/lab06", "duration": 1540,
                                               "created_ts": "2026-02-14T14:31:43"})
        net.reply("GET", f"/v2/video/{good}/", {"title": "nettech/lab01", "duration": 614,
                                                "created_ts": "2026-10-10T23:35:09"})
        d = answer.build(self.cfg, self.course, "1")
        self.assertEqual(d["blocked"],
                         ["RUTUBE_DEFENSE: в названии «infosec/lab06» нет номера работы"])
        self.assertIsNone(d["path"])
        self.assertFalse(self.env.with_suffix(".md").exists())
        text = answer.render(d)
        self.assertIn("  RUTUBE_LAB: nettech/lab01 · 2026-10-10 · 10:14", text)
        self.assertIn("Ответ не записан", text)
        self.assertNotIn("Сохранено", text)
        net.reply("GET", f"/v2/video/{old}/", ToolError("rutube", "HTTP 404"))
        d = answer.build(self.cfg, self.course, "1")
        self.assertEqual(d["blocked"], ["видео не проверены: HTTP 404"])
        args = argparse.Namespace(num="1", tag=None)
        patch(self, lab, "current", lambda: self.course)
        net.reply("GET", f"/v2/video/{old}/", ToolError("rutube", "HTTP 404"))
        self.assertEqual(cli.cmd_answer(self.cfg, args)[2], 1)

    def test_video_warnings(self):
        number = re.compile(r"(?i)(lab0*6|№\s*6)(?!\d)")
        card = {"title": "net-os-admin/lab06", "created": "2026-10-10T23:35:09"}
        self.assertEqual(answer.video_warnings(card, number, "2026-10-03"), [])
        self.assertEqual(answer.video_warnings({**card, "title": "Лабораторная работа № 6"},
                                               number, ""), [])
        self.assertEqual(answer.video_warnings({"title": "lab16", "created": "2026-02-14"},
                                               number, "2026-10-03"),
                         ["в названии «lab16» нет номера работы",
                          "загружено раньше прошлого релиза (2026-10-03)"])

    def test_tag_and_remote_only(self):
        self.env.parent.mkdir(parents=True)
        self.env.write_text("", encoding="utf-8")
        git(self.repo, "remote", "remove", "src")
        d = answer.build(self.cfg, self.course, "1", tag="v1.0.0")
        self.assertEqual(d["text"], "- Репозиторий и релиз:\n"
                                    "  - [gitverse](https://gitverse.ru/me/nettech), "
                                    "[релиз v1.0.0](https://gitverse.ru/me/nettech/releases/tag/v1.0.0)\n")

    def test_errors(self):
        with self.assertRaises(ToolError) as e:
            answer.build(self.cfg, self.course, "hw1")
        self.assertIn("ожидается номер лабораторной", e.exception.message)
        with self.assertRaises(ToolError) as e:
            answer.build(self.cfg, self.course, "2")
        self.assertIn(str(self.repo / "labs" / "lab02"), e.exception.message)


class PublishTest(CourseCase):

    def setUp(self):
        super().setUp()
        self.net = FakeNet().install(self)
        self.pushes = {}
        patch(self, publish, "pushed",
              lambda _path, remote, _tag: self.pushes.get(remote, True))
        patch(self, lab, "current", lambda: self.course)

    def releases(self, gv=(), sc=()):
        self.net.reply("GET", GV + "/releases", list(gv))
        self.net.reply("GET", SC + "/releases", {"releases": list(sc)})

    def test_changelog(self):
        self.assertEqual(publish.changelog(self.repo, "v1.1.0"),
                         "### Features\n\n* **lab01:** стенд")
        self.assertEqual(publish.changelog(self.repo, "v1.0.0"), "* init")
        self.assertIsNone(publish.changelog(self.repo, "v2.0.0"))
        self.assertIsNone(publish.changelog(self.tmp, "v1.0.0"))

    def test_creates_both_releases_with_all_files(self):
        self.releases()
        p = publish.plan(self.cfg, self.course, "1")
        names = ["nettech-lab01-report.pdf", "nettech-lab01-report.docx", "nettech-lab01-report.md",
                 "nettech-lab01-presentation.pdf", "nettech-lab01-presentation.md",
                 "nettech-lab01-presentation-html.zip", "nettech-lab01-sources.zip"]
        self.assertEqual((p["problems"], p["title"], p["files"]),
                         ([], "v1.1.0 — Лабораторная работа № 1", names))
        self.assertEqual([(h["source"], h["create"], h["upload"]) for h in p["hosts"]],
                         [("gitverse", True, names), ("sourcecraft", True, names)])
        self.assertIn("gitverse: создать релиз; загрузить: nettech-lab01-report.pdf",
                      publish.render(p))

        self.net.reply("POST", GV + "/releases", {"id": 9, "tag_name": "v1.1.0"})
        for n in names:
            self.net.reply("POST", f"{GV}/releases/9/assets?name={n}", {})
        self.net.reply("POST", SC + "/releases", {"tag": "v1.1.0"})
        for _ in names:
            self.net.reply("POST", SC + "/releases/tag/v1.1.0/attachments", {})
        done = publish.apply(self.course, p)
        self.assertEqual([(d["source"], d["created"]) for d in done],
                         [("gitverse", True), ("sourcecraft", True)])
        gv_rel, sc_rel = (r for r in self.net.sent
                          if r["method"] == "POST" and r["url"].endswith("/releases"))
        self.assertEqual(gv_rel["json_body"]["name"], "v1.1.0 — Лабораторная работа № 1")
        self.assertEqual(gv_rel["json_body"]["body"], "### Features\n\n* **lab01:** стенд")
        self.assertEqual(sc_rel["json_body"]["title"], "v1.1.0 — Лабораторная работа № 1")
        sent = {r["files"]["file"][0]: r["files"]["file"][1] for r in self.net.sent
                if r["files"] and "file" in r["files"]}
        self.assertEqual(sorted(sent), sorted(names))
        self.assertEqual(sent["nettech-lab01-report.md"], b"# report\n")
        with zipfile.ZipFile(io.BytesIO(sent["nettech-lab01-sources.zip"])) as z:
            self.assertEqual(sorted(z.namelist()),
                             ["presentation/image/src.png",
                              "presentation/nettech-lab01-presentation.qmd",
                              "report/image/src.png", "report/nettech-lab01-report.qmd"])
        with zipfile.ZipFile(io.BytesIO(sent["nettech-lab01-presentation-html.zip"])) as z:
            self.assertEqual(sorted(z.namelist()),
                             ["image/fig.png", "nettech-lab01-presentation.html"])

    def test_only_missing_files_uploaded(self):
        have = ["nettech-lab01-report.pdf", "nettech-lab01-report.docx", "nettech-lab01-report.md",
                "nettech-lab01-presentation.pdf", "nettech-lab01-presentation.md"]
        self.releases([{"id": 9, "tag_name": "v1.1.0", "name": "v1.1.0 — Лабораторная работа № 1",
                        "assets": [{"name": n} for n in have]}],
                      [{"tag": "v1.1.0", "title": "v1.1.0",
                        "assets": [{"name": n, "attachment": {}}
                                   for n in publish.files(self.course, "01")[0]]}])
        p = publish.plan(self.cfg, self.course, "01")
        self.assertEqual([(h["create"], h["upload"]) for h in p["hosts"]],
                         [(False, ["nettech-lab01-presentation-html.zip",
                                   "nettech-lab01-sources.zip"]), (False, [])])
        self.assertIn("sourcecraft: релиз есть; загрузить: все файлы на месте",
                      publish.render(p))
        self.net.reply("POST", GV + "/releases/9/assets?name=nettech-lab01-presentation-html.zip",
                       {})
        self.net.reply("POST", GV + "/releases/9/assets?name=nettech-lab01-sources.zip", {})
        publish.apply(self.course, p)

    def test_problems_block_release(self):
        (self.lab / "presentation/_output/nettech-lab01-presentation.pdf").unlink()
        (self.repo / "CHANGELOG.md").write_text("# 1.0.0 (2026-09-01)\n", encoding="utf-8")
        self.pushes["src"] = False
        self.releases([{"id": 3, "tag_name": "v1.1.0", "name": "v1.1.0 — Лабораторная работа № 2",
                        "assets": []}])
        args = argparse.Namespace(num="1", tag=None, confirm=True)
        plan, text, rc = cli.cmd_publish(self.cfg, args)
        self.assertEqual(rc, 1)
        self.assertEqual(len(plan["problems"]), 4)
        for part in ("не собрано: labs/lab01/presentation/_output/nettech-lab01-presentation.pdf",
                     "нет раздела 1.1.0: забыт bump version",
                     "тег v1.1.0 не отправлен в src",
                     "gitverse: релиз v1.1.0 уже занят под «v1.1.0 — Лабораторная работа № 2»"):
            self.assertIn(part, text)

    def test_cli_needs_confirm(self):
        self.releases()
        plan, text, rc = cli.cmd_publish(self.cfg, argparse.Namespace(num="1", tag=None,
                                                                      confirm=False))
        self.assertEqual(rc, 1)
        self.assertNotIn("client", str(plan))
        self.assertTrue(text.endswith("Повтори с --confirm."))


if __name__ == "__main__":
    unittest.main()
