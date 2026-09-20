import builtins
import contextlib
import io
import sys
import unittest
from unittest import mock

from study import agent, cli, update
from study.config import StudyError
from tests.fakes import git, patch, tmpdir


class UpdateTest(unittest.TestCase):
    """Клон `clone` с upstream в bare `origin.git`; свежие коммиты приходят из клона `other`."""

    def setUp(self):
        self.tmp = tmpdir(self)
        self.origin = self.tmp / "origin.git"
        self.origin.mkdir()
        git(self.origin, "init", "-q", "--bare")
        self.clone = self.tmp / "clone"
        self.clone.mkdir()
        git(self.clone, "init", "-q")
        git(self.clone, "remote", "add", "origin", str(self.origin))
        git(self.clone, "commit", "-q", "--allow-empty", "-m", "feat: первый")
        git(self.clone, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
        git(self.clone, "push", "-q", "-u", "origin", "master", "--tags")
        root = self.tmp / "study"
        root.mkdir()
        src = self.tmp / "AGENTS.md"
        src.write_text("# Инструкция\n\nv1\n", encoding="utf-8")
        for mod, attr, value in ((update, "HERE", self.clone), (agent, "ROOT", root),
                                 (agent, "SOURCE", src)):
            patch(self, mod, attr, value)
        self.root, self.src = root, src

    def upstream(self, *messages):
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(self.origin), str(other))
        for msg in messages:
            (other / "study.py").write_text(msg + "\n", encoding="utf-8")   # чтобы diff был не пуст
            git(other, "add", "study.py")
            git(other, "commit", "-q", "-m", msg)
        git(other, "push", "-q", "origin", "master")

    def test_up_to_date(self):
        d = update.check()
        self.assertEqual(d, {"version": "v1.0.0", "remote": "v1.0.0", "behind": 0, "ahead": 0,
                             "commits": [], "stat": "", "signed": None, "agents": []})
        self.assertEqual(update.note(d), [])
        self.assertEqual(update.apply()["updated"], False)

    def test_behind_and_apply(self):
        agent.install("claude")
        self.upstream("feat: новое", "fix: правка")
        # как если бы pull обновил docs/AGENTS.md
        self.src.write_text("# Инструкция\n\nv2\n", encoding="utf-8")
        d = update.check()
        self.assertEqual((d["behind"], d["ahead"], d["commits"]),
                         (2, 0, ["fix: правка", "feat: новое"]))   # новые первыми
        self.assertEqual(d["version"], "v1.0.0")
        self.assertTrue(d["remote"].startswith("v1.0.0-2-g"))
        self.assertEqual([(a["operator"], a["current"]) for a in d["agents"]], [("claude", False)])
        self.assertIn("Обновление study: v1.0.0 → v1.0.0-2-g", update.note(d)[0])
        self.assertIn("study.py |", d["stat"])
        self.assertIs(d["signed"], False)   # тестовые коммиты без подписи
        plan = update.plan(d)
        self.assertEqual(plan[:3], [f"Обновление study: v1.0.0 → {d['remote']}",
                                    "  fix: правка", "  feat: новое"])
        self.assertTrue(plan[-1].startswith("Подпись коммита НЕ проверена"))
        out = update.apply(d)
        self.assertEqual((out["updated"], out["now"], out["refreshed"]),
                         (True, d["remote"], ["CLAUDE.md"]))
        self.assertIn("v2", (self.root / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertEqual(update.check()["behind"], 0)

    def test_check_without_fetch_and_ahead(self):
        self.upstream("feat: новое")
        self.assertEqual(update.check(fetch=False)["behind"], 0)   # без fetch origin не виден
        git(self.clone, "commit", "-q", "--allow-empty", "-m", "wip")
        d = update.check()
        self.assertEqual((d["behind"], d["ahead"]), (1, 1))
        self.assertEqual(update.version(),
                         "v1.0.0-1-g" + git(self.clone, "rev-parse", "--short", "HEAD"))

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["update", *argv])
        return rc, out.getvalue()

    def test_cli_confirms_before_pull(self):
        """Без терминала pull только с --yes; в терминале — вопрос; --check ничего не меняет."""
        self.upstream("feat: новое")
        patch(self, sys, "stdin", mock.Mock(isatty=lambda: False))
        rc, out = self.cli()
        self.assertEqual(rc, 1)
        self.assertIn("Обновление study: v1.0.0 → v1.0.0-1-g", out)
        self.assertIn("study.py |", out)
        self.assertIn("Повтори с --yes.", out)
        rc, out = self.cli("--check")
        self.assertEqual((rc, "Повтори" in out, "НЕ проверена" in out), (0, False, True))
        self.assertEqual(update.check()["behind"], 1)   # ничего не тянули
        patch(self, sys, "stdin", mock.Mock(isatty=lambda: True))
        patch(self, builtins, "input", lambda *_: "n")
        rc, out = self.cli()
        self.assertEqual((rc, out.endswith("Отменено.\n")), (1, True))
        patch(self, builtins, "input", lambda *_: "y")
        rc, out = self.cli()
        self.assertEqual(rc, 0)
        self.assertIn("Обновлено: v1.0.0 → v1.0.0-1-g", out)
        self.assertEqual(update.check()["behind"], 0)
        self.assertEqual(self.cli("--check"), (0, "Актуально: v1.0.0-1-g"
                                               + git(self.clone, "rev-parse", "--short", "HEAD")
                                               + ".\n"))

    def test_cli_yes_without_tty(self):
        self.upstream("feat: новое")
        patch(self, sys, "stdin", mock.Mock(isatty=lambda: False))
        rc, out = self.cli("--yes")
        self.assertEqual((rc, "Обновлено" in out), (0, True))
        self.assertEqual(update.check()["behind"], 0)

    def test_stale_agent_only(self):
        agent.install("codex")
        self.src.write_text("# Инструкция\n\nv2\n", encoding="utf-8")
        out = update.apply()
        self.assertEqual((out["updated"], out["refreshed"]), (False, ["AGENTS.md"]))
        self.assertTrue(agent.status("codex")["current"])

    def test_not_a_clone_and_fetch_failure(self):
        with mock.patch.object(update, "HERE", self.tmp / "plain"):
            self.assertIsNone(update.check())
            with self.assertRaises(StudyError):
                update.apply()
        git(self.clone, "remote", "set-url", "origin", str(self.tmp / "nowhere.git"))
        with self.assertRaises(StudyError) as e:
            update.check()
        self.assertIn("fetch не удался", e.exception.message)
        # молчание сети: две попытки fetch по таймауту, потом честная строка
        real, calls = update.local.run, []

        def silent(path, *args, **kw):
            if args[0] != "fetch":
                return real(path, *args, **kw)
            calls.append(kw["timeout"])
            return None   # как при TimeoutExpired

        with mock.patch.object(update.local, "run", silent), self.assertRaises(StudyError) as e:
            update.check()
        self.assertEqual(calls, [update.FETCH_TIMEOUT] * 2)
        self.assertIn("нет ответа за 20 с, 2 попытки", e.exception.message)
        git(self.clone, "branch", "--unset-upstream")   # клон без ветки слежения — не обновляем
        self.assertIsNone(update.check())
