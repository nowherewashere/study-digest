import json
import os
import unittest

from kit.config import ToolError
from study import files
from study.config import Course
from tests.fakes import DAY, NOW, MoodleCase, fixture

SINCE = NOW - DAY


class FilesTest(MoodleCase):
    EXTRA = "CODE 1 nettech\n"
    ROOTS = (files,)

    def setUp(self):
        super().setUp()
        self.stash = self.tmp / "nettech" / "stash"
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"),
                       fixture("course_contents"))

    def test_listing_filters(self):
        (self.stash / "old").mkdir(parents=True)
        (self.stash / "old" / "lecture-01.pptx").write_bytes(b"x")
        d = files.listing(self.cfg, self.m, self.course, since=SINCE, everything=True)
        self.assertEqual((d["course"]["code"], d["stash"], d["since"]["ts"]),
                         ("nettech", str(self.stash), SINCE))
        rows = {f["name"]: f for f in d["files"]}
        self.assertEqual([f["name"] for f in d["files"]][:3],
                         ["002-dns.pdf", "video.mp4", "big.zip"])
        self.assertEqual({n: (f["skip"], f["have"], f["new"]) for n, f in rows.items()},
                         {"002-dns.pdf": (None, False, True),
                          "video.mp4": ("тип .mp4", False, True),
                          "big.zip": ("размер 60 МБ", False, True),
                          "Ссылка → https://example.org/": ("ссылка", False, True),
                          "lecture-01.pptx": (None, True, False),
                          "index.html": ("страница курса", False, False)})
        self.assertIsNone(rows["Ссылка → https://example.org/"]["path"])
        self.assertEqual(rows["lecture-01.pptx"]["path"],
                         str(self.stash / "old" / "lecture-01.pptx"))
        self.assertEqual(rows["002-dns.pdf"]["path"], str(self.stash / "002-dns.pdf"))
        self.assertEqual((rows["002-dns.pdf"]["section"], rows["002-dns.pdf"]["module"]),
                         ("Лабораторные работы", "Методичка 2"))
        new = files.listing(self.cfg, self.m, self.course, since=SINCE)
        self.assertEqual([f["name"] for f in new["files"]],
                         ["002-dns.pdf", "video.mp4", "big.zip", "Ссылка → https://example.org/"])
        text = files.render(new)
        self.assertIn("Забрать: study files nettech --pull", text)
        self.assertIn("пропущен: ссылка Ссылка → https://example.org/", text)

    def test_listing_by_snapshot(self):
        self.cfg.state_file().write_text(json.dumps(
            {"last_run": SINCE, "files": {"1": ["121/002-dns.pdf", "122/video.mp4"]}}),
            encoding="utf-8")
        d = files.listing(self.cfg, self.m, self.course)
        self.assertTrue(d["tracked"])
        self.assertEqual([f["name"] for f in d["files"]],
                         ["002-dns.pdf", "video.mp4", "big.zip", "Ссылка → https://example.org/",
                          "lecture-01.pptx", "index.html"])
        self.assertIn("чего не было при прошлой сводке", files.render(d))

    def test_listing_since_from_state(self):
        d = files.listing(self.cfg, self.m, self.course)
        self.assertIsNone(d["since"])
        self.assertEqual(len(d["files"]), 6)
        self.assertIn("после начала времён", files.render(d))
        with self.assertRaises(ToolError):
            files.stash(Course(2))

    def test_pull(self):
        self.stash.mkdir(parents=True)
        (self.stash / "lecture-01.pptx").write_bytes(b"old")
        os.utime(self.stash / "lecture-01.pptx", (NOW, NOW))
        d = files.listing(self.cfg, self.m, self.course, since=SINCE, everything=True)
        self.net.reply("GET", "002-dns.pdf?forcedownload=1&token=test-token", b"%PDF-2")
        out = files.pull(self.m, d)
        self.assertEqual(out["pulled"], [{"name": "002-dns.pdf", "bytes": 6, "updated": False,
                                          "path": str(self.stash / "002-dns.pdf")}])
        self.assertEqual((self.stash / "002-dns.pdf").read_bytes(), b"%PDF-2")
        self.assertEqual(int((self.stash / "002-dns.pdf").stat().st_mtime), 1789531200)
        self.assertEqual((self.stash / "lecture-01.pptx").read_bytes(), b"old")
        self.assertEqual(out["errors"], [])
        text = files.render(out, pulled=True)
        self.assertIn("скачан       002-dns.pdf", text)
        self.assertIn("уже есть     lecture-01.pptx", text)
        self.assertIn("пропущен: тип .mp4 video.mp4", text)
        self.assertIn(f"В {self.stash}: скачано 1", text)

    def test_pull_refreshes_newer(self):
        old = self.stash / "old" / "lecture-01.pptx"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old")
        os.utime(old, (1789279200 - 100, 1789279200 - 100))
        d = files.listing(self.cfg, self.m, self.course, since=SINCE, everything=True)
        row = next(f for f in d["files"] if f["name"] == "lecture-01.pptx")
        self.assertTrue(row["newer"])
        self.assertIn("есть, в ТУИС новее lecture-01.pptx", files.render(d))
        self.assertEqual(files.summary(d), "nettech: 2 к загрузке")
        self.net.reply("GET", "002-dns.pdf?forcedownload=1&token=test-token", b"%PDF-2")
        self.net.reply("GET", "lecture-01.pptx?token=test-token", b"new")
        out = files.pull(self.m, d)
        self.assertEqual([(g["name"], g["updated"]) for g in out["pulled"]],
                         [("002-dns.pdf", False), ("lecture-01.pptx", True)])
        self.assertEqual((old.read_bytes(), int(old.stat().st_mtime)), (b"new", 1789279200))
        self.assertFalse((self.stash / "lecture-01.pptx").exists())
        text = files.render(out, pulled=True)
        self.assertIn("обновлён     lecture-01.pptx", text)
        self.assertIn("скачано 2, из них обновлено 1", text)
        self.assertEqual(files.summary(out, pulled=True), "nettech: скачано 2, из них обновлено 1")

    def test_pull_force_and_error(self):
        self.stash.mkdir(parents=True)
        (self.stash / "lecture-01.pptx").write_bytes(b"old")
        d = files.listing(self.cfg, self.m, self.course, since=SINCE, everything=True)
        self.net.reply("GET", "002-dns.pdf", ToolError("moodle", "HTTP 404", where="pluginfile"))
        self.net.reply("GET", "lecture-01.pptx?token=test-token", b"new")
        out = files.pull(self.m, d, force=True)
        self.assertEqual([g["name"] for g in out["pulled"]], ["lecture-01.pptx"])
        self.assertEqual((self.stash / "lecture-01.pptx").read_bytes(), b"new")
        self.assertEqual([(e["where"], e["message"]) for e in out["errors"]],
                         [("002-dns.pdf", "HTTP 404")])
        self.assertIn("не удалось: 002-dns.pdf — HTTP 404", files.render(out, pulled=True))


class SafeNameTest(unittest.TestCase):
    def test_safe(self):
        self.assertEqual(files.safe("../a/b\\c.pdf"), ".._a_b_c.pdf")
        self.assertEqual(files.safe('Лекция 1: "введение" <v2>?.pdf'),
                         "Лекция 1_ _введение_ _v2__.pdf")
        self.assertEqual(files.safe(None), "file")
        self.assertEqual(len(files.safe("x" * 300)), 200)
