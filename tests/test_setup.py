"""`study setup`: ввод через input/getpass подменён очередями ответов, экраны — в StringIO."""
import builtins
import contextlib
import getpass
import io
import json
import os
import sys
import time
import unittest
from unittest import mock

from study import agent, courses, files, setup
from study.config import Config
from tests.fakes import NOW, FakeNet, fixture, patch, tmpdir

INVALID = {"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "Invalid token"}


class SetupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(self.tmp)
        self.root = self.tmp / "study"
        self.here = self.root / ".digest"
        (self.here / "docs").mkdir(parents=True)
        (self.here / "study").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        (self.here / "docs" / "AGENTS.md").write_text("# Инструкция\n", encoding="utf-8")
        (self.here / "config.env.example").write_text("# пример\nTUIS_TOKEN=\n", encoding="utf-8")
        for mod in (setup, agent, courses, files):
            patch(self, mod, "ROOT", self.root)
        patch(self, setup, "HERE", self.here)
        patch(self, agent, "SOURCE", self.here / "docs" / "AGENTS.md")
        patch(self, time, "time", lambda: NOW)
        self.net = FakeNet().install(self)
        self.answers, self.secrets, self.prompts, self.opened = [], [], [], []
        patch(self, builtins, "input", self.input)
        patch(self, getpass, "getpass", self.input)
        patch(self, sys, "stdin", mock.Mock(isatty=lambda: True))
        patch(self, setup, "open_url", lambda url: self.opened.append(url) or True)
        patch(self, setup, "in_path", lambda _: True)
        self.out = io.StringIO()

    def input(self, prompt=""):
        self.prompts.append(prompt)
        queue = self.secrets if "вставь токен" in prompt else self.answers
        self.assertTrue(queue, f"нет ответа на: {prompt}")
        return queue.pop(0)

    def config(self, extra=""):
        p = self.here / "config.env"
        p.write_text(f"TUIS_URL=https://tuis.example\nDIGEST_STATE={self.here / '.state.json'}\n"
                     + extra, encoding="utf-8")
        return Config(p)

    def run_setup(self, cfg):
        with contextlib.redirect_stdout(self.out):
            log, text = setup.run(cfg)
        self.assertEqual((self.answers, self.secrets), ([], []))
        return log, text, self.out.getvalue()

    def moodle_ok(self):
        self.net.reply("POST", "core_webservice_get_site_info", fixture("site_info"))
        self.net.reply("POST", "core_enrol_get_users_courses", fixture("users_courses"))


class SetupTest(SetupCase):
    def test_tokens_saved_and_skipped(self):
        cfg = self.config()
        self.answers = ["n", "", "", "nettech", "", "", "n"]   # браузер, оператор, курсы, pull
        self.secrets = ["a" * 32, "", ""]
        self.moodle_ok()
        log, text, out = self.run_setup(cfg)
        self.assertIn("study  установка  [1/5] Токены\n[>] Токены  [ ] Каталоги  [ ] Проверка  "
                      "[ ] Оператор  [ ] Курсы\n" + "-" * 72 + "\n\n", out)
        self.assertIn("study  установка  [6/6] Готово\n[x] Токены  [x] Каталоги  [x] Проверка  "
                      "[x] Оператор  [x] Курсы  [>] Готово\n", out)
        self.assertIn("  > открыть в браузере? [Y/n] ", self.prompts)
        self.assertEqual(self.opened, [])
        self.assertIn("TUIS_TOKEN=" + "a" * 32 + "\n", cfg.path.read_text(encoding="utf-8"))
        skipped = "пропущен, команды этого сервиса работать не будут"
        self.assertEqual([x for x in log if x[0] == "warn"],
                         [["warn", "Токены", "GitVerse: " + skipped],
                          ["warn", "Токены", "SourceCraft: " + skipped]])
        self.assertIn(["ok", "Токены", "Moodle: сохранён в config.env"], log)
        self.assertIn(["ok", "Проверка", "Moodle отвечает: Студент Тестовый"], log)
        self.assertIn(["ok", "Курсы", "записаны в config.env: 3 папок"], log)
        self.assertIn("config.env обновлён: COURSE_IGNORE (0), CODE (3)", out)
        self.assertIn("  + Токены: Moodle: сохранён в config.env\n", text)
        self.assertIn("  ! Токены: GitVerse: пропущен", text)
        self.assertIn("\n  Дальше\n  study state --pull", text)
        self.assertIn(f"рабочая папка {self.root},\n  в Instructions - текст из "
                      f"{self.here / 'docs' / 'daily-digest-prompt.md'}", text)
        self.assertTrue((self.root / "nettech" / "stash").is_dir())
        self.assertTrue((self.root / "2" / "tuis").is_dir())
        self.assertEqual(Config(cfg.path).codes(), {1: "nettech", 2: "2", 4: "4"})
        self.assertFalse((self.root / "CLAUDE.md").exists())
        self.assertIn("позже: study files --pull", out)

    def test_token_keep_replace_browser_and_moodle_down(self):
        cfg = self.config("TUIS_TOKEN=old\nGITVERSE_TOKEN=gv-old\n")
        self.answers = ["y", "n", "y", "claude bogus"]   # браузер, оставить, заменить, оператор
        self.secrets = ["gv-new", ""]                   # GitVerse новый, SourceCraft пропущен
        self.net.reply("POST", "core_webservice_get_site_info", INVALID)
        self.net.reply("POST", "core_webservice_get_site_info", INVALID)
        log, text, _ = self.run_setup(cfg)
        self.assertEqual(self.opened, ["https://tuis.example/user/managetoken.php"])
        self.assertIn(["ok", "Токены", "Moodle: оставлен прежний"], log)
        self.assertIn(["ok", "Токены", "GitVerse: сохранён в config.env"], log)
        saved = cfg.path.read_text(encoding="utf-8")
        self.assertIn("TUIS_TOKEN=old\n", saved)
        self.assertIn("GITVERSE_TOKEN=gv-new\n", saved)
        self.assertNotIn("gv-old", saved)
        self.assertIn(["warn", "Проверка",
                       "Moodle не отвечает: проверь токен и TUIS_URL в config.env"], log)
        self.assertIn(["warn", "Оператор", "не удалось, проверь коды: study agent"], log)
        self.assertIn(["warn", "Курсы",
                       "не удалось (нет токена Moodle?): позже study courses --setup"], log)
        self.assertFalse((self.root / "CLAUDE.md").exists())
        self.assertIn("  ! Проверка: Moodle не отвечает", text)

    def test_token_not_hex_warns(self):
        cfg = self.config()
        self.answers = ["n", ""]
        self.secrets = ["a" * 64, "", ""]
        self.net.reply("POST", "core_webservice_get_site_info", INVALID)
        self.net.reply("POST", "core_webservice_get_site_info", INVALID)
        log, _, _ = self.run_setup(cfg)
        self.assertIn(["ok", "Токены", "Moodle: сохранён в config.env"], log)
        warn = "Moodle: токен не похож на 32 hex-символа (64) — не вставлен ли дважды?"
        self.assertIn(["warn", "Токены", warn], log)

    def test_browser_failed(self):
        cfg = self.config()
        patch(self, setup, "open_url", lambda _: False)
        self.answers = ["", ""]
        self.secrets = ["", "", ""]   # токена нет — Moodle не спрашивается вовсе
        log, _, _ = self.run_setup(cfg)
        self.assertIn(["warn", "Токены", "не открылось: перейди по ссылке вручную"], log)
        self.assertIn(["warn", "Токены",
                       "Moodle: пропущен, команды этого сервиса работать не будут"], log)

    def test_no_terminal(self):
        cfg = self.config("TUIS_TOKEN=t\n")
        patch(self, sys, "stdin", io.StringIO())
        self.net.reply("POST", "core_webservice_get_site_info", fixture("site_info"))
        log, text, out = self.run_setup(cfg)
        self.assertEqual(self.prompts, [])
        self.assertEqual(
            [x for x in log if x[0] == "warn"],
            [["warn", "Токены", "нет терминала, ввод токенов пропущен"],
             ["warn", "Оператор", "нет терминала, шаг пропущен: позже study agent <код>"],
             ["warn", "Курсы", "нет терминала, шаг пропущен: позже study courses --setup"]])
        self.assertIn(["ok", "Проверка", "Moodle отвечает: Студент Тестовый"], log)
        self.assertTrue(any(x[2].startswith("команда study: ") for x in log))
        self.assertIn("папки курсов появятся на шаге «Курсы»", out)
        self.assertNotIn("\033[", out + text)   # без терминала — без цветов и очистки экрана

    def test_operators_dirs_and_pull(self):
        (self.root / "CLAUDE.md").write_text("# Моё\n", encoding="utf-8")
        cfg = self.config("TUIS_TOKEN=t\nCODE 1 nettech\n")
        # на шаге «Каталоги» сети нет: название курса для заготовки NOTES.md — из снимка
        (self.here / ".state.json").write_text(
            json.dumps({"last_run": 1, "courses": {"1": "Сетевые технологии"}}), encoding="utf-8")
        # операторы; курсы: старые в игнор, готово, два имени папок; скачать
        self.answers = ["claude codex", "s", "", "", "", "y"]
        self.moodle_ok()
        self.net.reply("POST", "core_enrol_get_users_courses", fixture("users_courses"))  # pull
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"),
                       fixture("course_contents"))
        self.net.reply("GET", "002-dns.pdf", b"%PDF-2")
        self.net.reply("GET", "lecture-01.pptx", b"PK")
        self.net.reply("POST", ("core_course_get_contents", "courseid=2"),
                       fixture("course_contents_small"))
        self.net.reply("GET", "lecture-01.pdf", b"%PDF")
        with mock.patch.object(setup, "tokens", lambda *_: None):   # токены не спрашиваем
            log, _, out = self.run_setup(cfg)
        self.assertIn(["ok", "Каталоги", f"{self.root / 'nettech'}{os.sep}{{stash,tuis,NOTES.md}}"],
                      log)
        self.assertIn(["ok", "Каталоги", f"снимок состояния сводки: {self.here}"], log)
        notes = (self.root / "nettech" / "NOTES.md").read_text(encoding="utf-8")
        self.assertTrue(notes.startswith("# Сетевые технологии — заметки\n"))
        self.assertIn("Курс в ТУИС: `1`", notes)
        self.assertIn(["ok", "Оператор", "поставлено: claude codex"], log)
        claude = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(claude.startswith("# Моё\n\n" + agent.BEGIN))
        self.assertIn(agent.BEGIN, (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("  код      файл", out)   # таблица операторов с отступом
        self.assertEqual(Config(cfg.path).ignore(), {4})
        self.assertIn(["ok", "Курсы", "записаны в config.env: 2 папок"], log)
        # курс 2 получил папку «2» на шаге «Курсы» — заготовка с названием из ТУИС
        self.assertTrue((self.root / "2" / "NOTES.md").read_text(encoding="utf-8")
                        .startswith("# Вычислительные методы — заметки\n"))
        self.assertTrue(notes == (self.root / "nettech" / "NOTES.md").read_text(encoding="utf-8"))
        self.assertIn("  nettech: скачано 2\n  2: скачано 1\n", out)
        self.assertIn(["ok", "Курсы", "материалы курсов в stash/"], log)
        self.assertEqual((self.root / "nettech" / "stash" / "002-dns.pdf").read_bytes(), b"%PDF-2")

    def test_resume_from_install(self):
        cfg = self.config("TUIS_TOKEN=t\n")
        patch(self, sys, "stdin", io.StringIO())
        self.net.reply("POST", "core_webservice_get_site_info", fixture("site_info"))
        os.environ["STUDY_SETUP"] = json.dumps({
            "steps": ["Зависимости", "Код"],
            "log": [["ok", "Зависимости", "git 2.43.0"], ["ok", "Код", "склонировано в /x"]]})
        log, text, out = self.run_setup(cfg)
        self.assertIn("study  установка  [3/7] Токены\n[x] Зависимости  [x] Код  [>] Токены  "
                      "[ ] Каталоги  [ ] Проверка  [ ] Оператор  [ ] Курсы\n", out)
        self.assertIn("[7/7] Курсы", out)
        self.assertIn("study  установка  [8/8] Готово\n", out)
        self.assertEqual(log[:2], [["ok", "Зависимости", "git 2.43.0"],
                                   ["ok", "Код", "склонировано в /x"]])
        self.assertIn("  + Зависимости: git 2.43.0\n  + Код: склонировано в /x\n"
                      "  ! Токены: нет терминала", text)

    def test_config_from_example(self):
        cfg = Config(self.here / "config.env")
        patch(self, sys, "stdin", io.StringIO())
        log, _, _ = self.run_setup(cfg)
        self.assertTrue(log[0][2].startswith("создан config.env из примера"))
        self.assertEqual(cfg.path.read_text(encoding="utf-8"), "# пример\nTUIS_TOKEN=\n")
        if os.name == "posix":
            self.assertEqual(oct(cfg.path.stat().st_mode)[-3:], "600")


class ProgressTest(unittest.TestCase):
    def test_tty_only(self):
        quiet = io.StringIO()
        p = files.Progress(quiet)
        p("nettech", "1/2 a.pdf")
        p.clear()
        self.assertEqual(quiet.getvalue(), "")
        tty = io.StringIO()
        tty.isatty = lambda: True
        p = files.Progress(tty)
        p("nettech", "состав курса…")
        p("nettech", "1/2 a.pdf")
        p.clear()
        self.assertEqual(tty.getvalue(),
                         "\r\033[K  nettech: состав курса…\r\033[K  nettech: 1/2 a.pdf\r\033[K")


class ScreenTest(unittest.TestCase):
    def test_colors_only_on_tty(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            s = setup.Screen(["A", "B"])
            s.step(2)
            s.ok("x")
            s.warn("y")
            s.note("z")
        self.assertEqual(out.getvalue(), "study  установка  [2/2] B\n[x] A  [>] B\n" + "-" * 72
                         + "\n\n  + x\n  ! y\n  z\n")
        self.assertEqual(s.log, [["ok", "B", "x"], ["warn", "B", "y"]])
        tty = io.StringIO()
        tty.isatty = lambda: True
        with contextlib.redirect_stdout(tty):
            s = setup.Screen(["A"])
            s.step(1)
            s.ok("x")
        self.assertTrue(tty.getvalue().startswith("\033[H\033[2J\033[1mstudy\033[0m  установка  "
                                                  "\033[1m[1/1] A\033[0m\n\033[1m[>] A\033[0m\n"))
        self.assertIn("\n  \033[32m+\033[0m x\n", tty.getvalue())

    def test_yes(self):
        self.assertEqual([setup.yes(a, "y") for a in ("", "n", "Yes", " N ")],
                         [True, False, True, False])
        self.assertEqual([setup.yes(a, "n") for a in ("", "y")], [False, True])


class LinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(self.tmp)
        self.here = self.tmp / "study" / ".digest"
        self.here.mkdir(parents=True)
        (self.here / "study").write_text("", encoding="utf-8")
        patch(self, setup, "HERE", self.here)
        self.bin = self.tmp / ".local" / "bin"

    @unittest.skipUnless(os.name == "posix", "симлинк")
    def test_symlink(self):
        self.bin.mkdir(parents=True)
        (self.bin / "study").write_text("old", encoding="utf-8")   # старый файл заменяется
        self.assertEqual(setup.link_command(), f"~/.local/bin/study -> {self.here / 'study'}")
        self.assertEqual(os.readlink(self.bin / "study"), str(self.here / "study"))
        setup.link_command()   # повтор не падает
        self.assertTrue((self.bin / "study").is_symlink())

    @unittest.skipUnless(os.name == "nt", "study.cmd")
    def test_cmd_and_sh(self):
        self.assertTrue(setup.link_command().endswith(f"study.cmd -> {self.here / 'study'}"))
        cmd = (self.bin / "study.cmd").read_bytes().decode("oem")
        self.assertTrue(cmd.startswith('@"') and cmd.endswith(' %*\r\n'))
        self.assertIn('"%USERPROFILE%\\study\\.digest\\study"', cmd)
        sh = (self.bin / "study").read_text(encoding="utf-8")
        self.assertTrue(sh.startswith("#!/bin/sh\nexec "))
        self.assertIn(f'"{(self.here / "study").as_posix()}" "$@"\n', sh)
        self.assertNotIn("\r", sh)

    def test_link_failure_is_a_warning(self):
        s = setup.Screen(["Проверка"])
        s.n = 1
        patch(self, setup, "link_command", mock.Mock(side_effect=OSError("read-only")))
        with contextlib.redirect_stdout(io.StringIO()):
            setup.check(s, mock.Mock(me=lambda: {"fullname": "Я"}))
        self.assertEqual(s.log[-1][:2], ["warn", "Проверка"])
        self.assertIn("не поставлена (read-only)", s.log[-1][2])

    def test_in_path_registry_error(self):
        os.environ["PATH"] = "/usr/bin"
        patch(self, setup, "winreg", object())
        patch(self, setup, "user_path", mock.Mock(side_effect=OSError("denied")))
        self.assertFalse(setup.in_path(self.bin))

    def test_path_hint(self):
        s = setup.Screen(["Проверка"])
        s.n = 1
        with contextlib.redirect_stdout(io.StringIO()):
            patch(self, setup, "in_path", lambda _: True)
            setup.path_hint(s)
            self.assertEqual(s.log, [])
            patch(self, setup, "in_path", lambda _: False)
            patch(self, sys, "stdin", io.StringIO())
            setup.path_hint(s)
        self.assertEqual(len(s.log), 1)
        self.assertEqual(s.log[0][0], "warn")
        self.assertIn(".zprofile" if sys.platform == "darwin" else
                      "~/.local/bin" if os.name == "posix" else "PATH пользователя", s.log[0][2])

    def test_in_path(self):
        os.environ["PATH"] = os.pathsep.join(["/usr/bin", str(self.bin) + os.sep])
        patch(self, setup, "user_path", lambda: ("", 0))
        self.assertTrue(setup.in_path(self.bin))
        os.environ["PATH"] = "/usr/bin"
        self.assertFalse(setup.in_path(self.bin))


class NotesStubTest(unittest.TestCase):
    def test_stub_once(self):
        root = tmpdir(self)
        patch(self, courses, "ROOT", root)
        p = courses.notes_stub("nettech", 1, "Сетевые технологии")
        self.assertEqual(p, root / "nettech" / "NOTES.md")
        text = p.read_text(encoding="utf-8")
        self.assertIn("# Сетевые технологии — заметки\n\nКурс в ТУИС: `1` «Сетевые технологии»",
                      text)
        self.assertIn("`study files nettech --pull`", text)
        for head in ("## Задания и сроки", "## Ключевые находки", "## Лабы"):
            self.assertIn(head, text)
        self.assertIsNone(courses.notes_stub("nettech", 1, "Другое"))
        self.assertEqual(p.read_text(encoding="utf-8"), text)   # повтор не трогает
        (root / "bpm").mkdir()
        (root / "bpm" / "NOTES.md").write_text("# Моё\n", encoding="utf-8")
        self.assertIsNone(courses.notes_stub("bpm", 5))
        self.assertEqual((root / "bpm" / "NOTES.md").read_text(encoding="utf-8"), "# Моё\n")
        self.assertTrue(courses.notes_stub("x", 9).read_text(encoding="utf-8")
                        .startswith("# x — заметки"))   # без названия — код папки
