import json
import time
import unittest

from study import agent, snapshot, update
from study.config import Config, StudyError
from tests.fakes import at_root, patch, tmpdir


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        (self.dir / "config.env").write_text(f"DIGEST_STATE={self.dir / '.state.json'}\n",
                                             encoding="utf-8")
        self.cfg = Config(self.dir / "config.env")

    def test_load_variants(self):
        self.assertEqual(snapshot.load_state(self.cfg), {})
        snapshot.save_state(self.cfg, {"last_run": 1_700_000_000, "grades": {"1": {}}})
        self.assertEqual(snapshot.load_state(self.cfg)["last_run"], 1_700_000_000)
        self.assertEqual(snapshot.load_state(self.cfg, "never"), {})
        self.assertEqual(snapshot.load_state(self.cfg, "all")["last_run"], 1)
        self.assertEqual(snapshot.load_state(self.cfg, "3")["last_run"], 1_700_000_000)
        self.assertEqual(snapshot.load_state(self.cfg, "2023-11-15")["last_run"], 1_700_000_000)
        early = snapshot.load_state(self.cfg, "2020-01-01")
        self.assertEqual(time.strftime("%Y-%m-%d", time.localtime(early["last_run"])), "2020-01-01")
        self.assertEqual(early["grades"], {"1": {}})
        with self.assertRaises(StudyError):
            snapshot.load_state(self.cfg, "вчера")

    def test_broken_state_falls_back_to_history(self):
        current = self.cfg.state_file()
        errors = []
        current.write_text("{\"last_run\": 1_7", encoding="utf-8")
        self.assertEqual(snapshot.load_state(self.cfg, errors=errors), {})
        self.assertEqual([e["message"] for e in errors],
                         [".state.json повреждён, считаю первым запуском"])
        snapshot.save_state(self.cfg, {"last_run": 1_700_000_000, "grades": {"1": {}}})
        snapshot.save_state(self.cfg, {"last_run": 1_700_000_000 + snapshot.DAY, "grades": {}})
        current.write_text("", encoding="utf-8")
        day = time.strftime("%Y-%m-%d", time.localtime(1_700_000_000 + snapshot.DAY))
        (snapshot.history_dir(self.cfg) / f"{day}.json").write_text("{", encoding="utf-8")
        errors = []
        state = snapshot.load_state(self.cfg, errors=errors)
        self.assertEqual(state["last_run"], 1_700_000_000)
        self.assertEqual(errors[0]["message"], ".state.json повреждён, взят снимок за "
                         + time.strftime("%Y-%m-%d", time.localtime(1_700_000_000)))
        self.assertEqual(snapshot.load_state(self.cfg), state)
        self.assertEqual(snapshot.load_state(self.cfg, day)["last_run"], 1_700_000_000)
        snapshot.save_state(self.cfg, state)
        self.assertEqual(json.loads(current.read_text(encoding="utf-8")), state)
        self.assertFalse(current.with_name(".state.json.tmp").exists())

    def test_history_pruned(self):
        old = 1_700_000_000
        snapshot.save_state(self.cfg, {"last_run": old})
        snapshot.save_state(self.cfg, {"last_run": old + (snapshot.KEEP_DAYS + 1) * snapshot.DAY})
        days = sorted(p.stem for p in snapshot.history_dir(self.cfg).glob("*.json"))
        self.assertEqual(len(days), 1)
        kept = json.loads((snapshot.history_dir(self.cfg) / f"{days[0]}.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(kept["last_run"], old + (snapshot.KEEP_DAYS + 1) * snapshot.DAY)


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.src = self.root / "AGENTS.src.md"
        self.src.write_text("# Инструкция\n\nтекст v1\n", encoding="utf-8")
        at_root(self, self.root, agent)
        patch(self, agent, "SOURCE", self.src)

    def test_new_append_stale_idempotent(self):
        r = agent.install("copilot")
        self.assertTrue(r["current"] and (self.root / ".github/copilot-instructions.md").exists())

        (self.root / "CLAUDE.md").write_text("# Моё\n\n- правило 1\n", encoding="utf-8")
        agent.install("claude")
        text = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Моё\n\n- правило 1\n\n" + agent.BEGIN))
        self.assertTrue(text.endswith(agent.END + "\n"))

        (self.root / "CLAUDE.md").write_text(text + "\n# После\n", encoding="utf-8")
        self.src.write_text("# Инструкция\n\nтекст v2\n", encoding="utf-8")
        self.assertFalse(agent.status("claude")["current"])
        agent.install("claude")
        text = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("текст v2", text)
        self.assertNotIn("текст v1", text)
        self.assertEqual(text.count(agent.BEGIN), 1)
        self.assertTrue(text.startswith("# Моё\n\n- правило 1\n\n"))
        self.assertTrue(text.endswith("\n# После\n"))
        agent.install("claude")
        self.assertEqual((self.root / "CLAUDE.md").read_text(encoding="utf-8"), text)


class UpdateNoteTest(unittest.TestCase):
    def test_note(self):
        self.assertEqual(update.note(None), [])
        base = {"version": "v1", "remote": "v2", "commits": ["a", "b", "c", "d"], "agents": []}
        self.assertIn("1 коммит (", update.note({**base, "behind": 1})[0])
        self.assertIn("3 коммита", update.note({**base, "behind": 3})[0])
        self.assertIn("11 коммитов", update.note({**base, "behind": 11})[0])
        five = update.note({**base, "behind": 5})[0]
        self.assertIn("(a; b; c; …)", five)
        agents = [{"file": "CLAUDE.md", "operator": "claude", "current": False}]
        self.assertEqual(update.note({**base, "behind": 0, "agents": agents}),
                         ["Блок агента в CLAUDE.md устарел — `study agent claude`."])


if __name__ == "__main__":
    unittest.main()
