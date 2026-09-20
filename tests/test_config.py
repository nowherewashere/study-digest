import os
import unittest

from study.config import Config, StudyError
from tests.fakes import tmpdir


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.path = self.dir / "config.env"

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")
        return Config(self.path)

    def test_read(self):
        cfg = self.write("# коммент\nTUIS_URL = https://x/ \nCOURSE_IGNORE=1 2\n"
                         "  CODE 5 five\nCODEX=1\nCOURSE 7 seven Старое\nCODE 9\n")
        self.assertEqual(cfg.get("TUIS_URL"), "https://x/")
        self.assertEqual(cfg.ignore(), {1, 2})
        self.assertEqual(cfg.codes(), {5: "five"})   # CODEX — обычный ключ, CODE 9 — неполная
        self.assertEqual(cfg.get("CODEX"), "1")
        self.assertEqual(cfg.get("COURSE_IGNORE"), "")   # не переменная, а список

    def test_defaults_and_env(self):
        cfg = self.write("")
        self.assertEqual(cfg.get("DIGEST_DAYS"), "21")
        self.assertEqual(cfg.days(), 21)
        self.assertEqual(cfg.get("NOPE"), "")
        os.environ["DIGEST_DAYS"] = "7"
        try:
            self.assertEqual(cfg.days(), 7)
        finally:
            del os.environ["DIGEST_DAYS"]

    def test_token_value_file_missing(self):
        cfg = self.write("GITVERSE_TOKEN=abc\n")
        self.assertEqual(cfg.token("GITVERSE_TOKEN"), "abc")
        (self.dir / "t").write_text("fromfile\n", encoding="utf-8")
        cfg = self.write(f"RUTUBE_TOKEN_FILE={self.dir / 't'}\n")
        self.assertEqual(cfg.token("RUTUBE_TOKEN"), "fromfile")
        with self.assertRaises(StudyError) as e:
            self.write("").token("TUIS_TOKEN")
        self.assertEqual(e.exception.code, "notoken")
        self.assertTrue(e.exception.hint())

    def test_put(self):
        cfg = self.write("# пример\nTUIS_TOKEN=old\nCODE 5 five\nDIGEST_DAYS=7\n")
        cfg.put("TUIS_TOKEN", "new")
        cfg.put("GITVERSE_TOKEN", "gv")
        self.assertEqual(self.path.read_text(encoding="utf-8"),
                         "# пример\nCODE 5 five\nDIGEST_DAYS=7\n"
                         "TUIS_TOKEN=new\nGITVERSE_TOKEN=gv\n")
        self.assertEqual((cfg.token("TUIS_TOKEN"), cfg.get("GITVERSE_TOKEN")), ("new", "gv"))
        self.assertEqual(Config(self.path).codes(), {5: "five"})
        if os.name == "posix":
            self.assertEqual(oct(self.path.stat().st_mode)[-3:], "600")
        self.assertFalse(self.path.with_name("config.env.tmp").exists())

    def test_put_escapes_key(self):
        # точка в ключе — не «любой символ»: A.B не должен снести строку AXB
        cfg = self.write("AXB=1\nA.B=2\n")
        cfg.put("A.B", "3")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "AXB=1\nA.B=3\n")

    def test_write_atomic_replaces_open_permissions(self):
        # файл с прежними правами 644 подменяется целиком: 600 с момента создания
        self.path.write_text("TUIS_TOKEN=old\n", encoding="utf-8")
        if os.name == "posix":
            self.path.chmod(0o644)
        Config(self.path).put("TUIS_TOKEN", "new")
        if os.name == "posix":
            self.assertEqual(oct(self.path.stat().st_mode)[-3:], "600")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "TUIS_TOKEN=new\n")

    def test_track(self):
        cfg = self.write("COURSE_IGNORE=2\nCODE 1 one\n")
        got = cfg.track([{"id": 1, "fullname": "Один"}, {"id": 2, "fullname": "Два"}, {"id": 3}])
        self.assertEqual([(c.id, c.code, c.title) for c in got],
                         [(1, "one", "Один"), (3, None, "")])

    def test_write_courses(self):
        cfg = self.write("A=1\nCOURSE_IGNORE=1\nCODE 5 five\nCOURSE 7 x Старое\n# CODE 8 keep\n"
                         "FLOW 5 file\nFLOW 7 release\n")
        self.assertEqual(cfg.flows(), {5: "file", 7: "release"})
        cfg.write_courses({3}, {5: "five", 8: "eight"})   # без flows — прежние, но только с папкой
        self.assertEqual(self.path.read_text(encoding="utf-8"),
                         "A=1\n# CODE 8 keep\nCOURSE_IGNORE=3\nCODE 5 five\nCODE 8 eight\n"
                         "FLOW 5 file\n")
        if os.name == "posix":
            self.assertEqual(oct(self.path.stat().st_mode)[-3:], "600")
        self.assertEqual(Config(self.path).codes(), {5: "five", 8: "eight"})
        cfg.write_courses({3}, {5: "five", 8: "eight"}, {5: "release", 8: "file"})
        self.assertTrue(self.path.read_text(encoding="utf-8")
                        .endswith("CODE 8 eight\nFLOW 5 release\nFLOW 8 file\n"))
        self.assertEqual(Config(self.path).flows(), {5: "release", 8: "file"})

    def test_flow_bad_value(self):
        with self.assertRaises(StudyError) as e:
            self.write("CODE 5 five\nFLOW 5 git\n")
        self.assertIn("FLOW 5: ожидается release или file", e.exception.message)


if __name__ == "__main__":
    unittest.main()
