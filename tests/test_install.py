import builtins
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from tests.fakes import git, home, patch, repo, tmpdir

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        home(self, self.tmp)
        self.upstream = repo(self.tmp / "upstream")
        for rel in ("study", "src/study/__init__.py", "src/study/setup.py"):
            (self.upstream / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.upstream / rel).write_text("", encoding="utf-8")
        (self.upstream / "config.env.example").write_text("TUIS_TOKEN=\n", encoding="utf-8")
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-q", "-m", "feat: файлы")
        os.environ["STUDY_REPO"] = str(self.upstream)
        self.mod = load()
        patch(self, self.mod, "HERE", self.tmp / "downloads")
        self.answers, self.calls = [], []
        patch(self, builtins, "input", lambda _="": self.answers.pop(0))
        patch(self, sys, "stdin", mock.Mock(isatty=lambda: True))
        patch(self, subprocess, "call", self.call)
        self.out = io.StringIO()

    def call(self, argv, env=None):
        self.calls.append((argv, env))
        return 0

    def run_install(self):
        with contextlib.redirect_stdout(self.out):
            rc = self.mod.main()
        return rc, self.out.getvalue()

    def test_default_path_clone_and_handoff(self):
        self.answers = [""]
        rc, out = self.run_install()
        self.assertEqual(rc, 0)
        digest = self.tmp / "study" / ".digest"
        self.assertTrue((digest / "src" / "study" / "setup.py").exists())
        self.assertEqual((digest / "config.env").read_text(encoding="utf-8"), "TUIS_TOKEN=\n")
        if os.name == "posix":
            self.assertEqual(oct((digest / "config.env").stat().st_mode)[-3:], "600")
        self.assertIn("study  установка  [1/7] Зависимости\n[>] Зависимости  [ ] Код  [ ] Токены",
                      out)
        self.assertIn("study  установка  [2/7] Код\n[x] Зависимости  [>] Код  [ ] Токены", out)
        self.assertIn(f"  + склонировано в {digest}\n", out)
        (argv, env), = self.calls
        self.assertEqual(argv, [sys.executable, str(digest / "study"), "setup"])
        passed = json.loads(env["STUDY_SETUP"])
        self.assertEqual(passed["steps"], ["Зависимости", "Код"])
        self.assertEqual([(k, step) for k, step, _ in passed["log"]],
                         [("ok", "Зависимости")] * 2 + [("ok", "Код")] * 3)
        self.assertTrue(passed["log"][0][2].startswith("git "))
        self.assertTrue(passed["log"][1][2].startswith("python3 3."))
        self.assertEqual(passed["log"][4][2], f"учебная директория: {self.tmp / 'study'}")

    def test_path_checks(self):
        busy = self.tmp / "busy"
        busy.mkdir()
        (busy / "x").write_text("", encoding="utf-8")
        self.answers = ["a=b", "x" * 101, str(busy), str(busy / "x"), "~/study/.digest"]
        rc, out = self.run_install()
        self.assertEqual(rc, 0)
        self.assertIn("  ! в пути нельзя '=' (ломает libvirt/virtiofsd)\n", out)
        self.assertIn("  ! слишком длинный путь (лимит unix-сокетов Packer ~108 байт)\n", out)
        self.assertIn(f"  ! {busy} существует и не пуст — выбери другой\n", out)
        self.assertIn(f"  ! {busy / 'x'} существует и не пуст — выбери другой\n", out)
        self.assertTrue((self.tmp / "study" / ".digest" / "study").exists())
        self.assertEqual(self.calls[0][0][1], str(self.tmp / "study" / ".digest" / "study"))

    def test_relative_path_from_cwd(self):
        patch(self, pathlib.Path, "cwd", classmethod(lambda _: self.tmp))
        self.answers = ["work/.digest"]
        rc, _ = self.run_install()
        self.assertEqual(rc, 0)
        self.assertTrue((self.tmp / "work" / ".digest" / "study").exists())

    def test_already_installed_target(self):
        digest = self.tmp / "study" / ".digest"
        shutil.copytree(self.upstream, digest)
        (digest / "config.env").write_text("TUIS_TOKEN=x\n", encoding="utf-8")
        self.answers = [""]
        rc, out = self.run_install()
        self.assertEqual(rc, 0)
        self.assertIn(f"  + уже установлено: {digest}\n", out)
        self.assertNotIn("создан config.env", out)
        self.assertEqual((digest / "config.env").read_text(encoding="utf-8"), "TUIS_TOKEN=x\n")

    def test_old_install_without_setup(self):
        digest = self.tmp / "study" / ".digest"
        shutil.copytree(self.upstream, digest)
        (digest / "src" / "study" / "setup.py").unlink()
        self.answers = [""]
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(self.out):
            self.mod.main()
        self.assertIn("старый study без команды setup: сначала study update", self.out.getvalue())
        self.assertEqual(self.calls, [])

    def test_already_here(self):
        digest = self.tmp / "study" / ".digest"
        shutil.copytree(self.upstream, digest)
        patch(self, self.mod, "HERE", digest)
        rc, out = self.run_install()
        self.assertEqual(rc, 0)
        self.assertIn(f"  + уже на месте: {digest}\n", out)
        self.assertTrue((digest / "config.env").exists())

    def test_no_terminal_uses_default(self):
        patch(self, sys, "stdin", io.StringIO())
        rc, out = self.run_install()
        self.assertEqual(rc, 0)
        self.assertIn(f"склонировано в {self.tmp / 'study' / '.digest'}", out)
        self.assertNotIn("\033[", out)

    def test_no_git_and_bad_clone(self):
        patch(self, shutil, "which", lambda _: None)
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(self.out):
            self.mod.main()
        self.assertIn("  ! git не найден\n", self.out.getvalue())
        patch(self, shutil, "which", lambda _: "/usr/bin/git")
        patch(self, self.mod, "REPO", str(self.tmp / "nowhere"))
        patch(self, subprocess, "run", lambda argv, **_: subprocess.CompletedProcess(argv, 128, ""))
        self.answers = [""]
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(self.out):
            self.mod.main()
        self.assertIn(f"  ! git clone не удался: {self.tmp / 'nowhere'}\n", self.out.getvalue())
        self.assertEqual(self.calls, [])
