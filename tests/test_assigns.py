"""Реестр заданий курса: слияние mod_assign и состава курса в одну модель."""
import unittest

from study import assigns
from study.config import Course, StudyError, soft
from study.moodle import Moodle
from tests.fakes import FakeNet, config, fixture, tmpdir


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.net = FakeNet().install(self)
        self.cfg = config(self.tmp, "CODE 1 nettech\n")
        self.m = Moodle(self.cfg)
        self.course = Course(1, "nettech", "Сетевые технологии")

    def both(self):
        """Ответы обеих ручек по курсу 1; каждый отдаётся один раз — значит проверяется и кеш."""
        self.net.reply("POST", ("mod_assign_get_assignments", "courseids[0]=1"),
                       fixture("assignments"))
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"),
                       fixture("course_contents"))
        return assigns.Registry(self.m, [self.course.id])

    def test_merges_two_sources(self):
        r = self.both()
        works = r.works(self.course)
        by_cmid = {w.cmid: w for w in works}
        self.assertEqual(len(works), len(by_cmid))          # дублей по cmid нет
        self.assertIn(111, by_cmid)                          # из mod_assign
        self.assertIn(115, by_cmid)                          # только из состава курса
        self.assertEqual(r.works(self.course), works)        # второй раз — из кеша, без сети

    def test_api_wins_over_contents(self):
        w = next(x for x in self.both().works(self.course) if x.cmid == 111)
        self.assertEqual((w.source, w.assign_id, w.available), ("assign_api", 11, True))
        self.assertEqual(w.due, 1789851540)
        self.assertEqual(w.lab, "01")

    def test_hidden_work_from_contents(self):
        w = next(x for x in self.both().works(self.course) if x.cmid == 115)
        self.assertEqual((w.source, w.assign_id, w.available, w.visible),
                         ("course_contents", None, False, False))
        self.assertEqual(w.due, 1790024340)
        self.assertIn("НФИбд-01-24", w.reason)               # причина без html-тегов
        self.assertNotIn("<strong>", w.reason)
        self.assertIn("Доклад по теме лекции 1", w.intro)
        self.assertEqual(w.section, "Доклады")

    def test_find_by_number_then_id_then_cmid(self):
        r = self.both()
        self.assertEqual(r.find(self.course, "1").assign_id, 11)     # номер лабы
        self.assertEqual(r.find(self.course, "lab02").assign_id, 12)
        self.assertEqual(r.find(self.course, "13").assign_id, 13)    # id, лабы № 13 нет
        self.assertEqual(r.find(self.course, "115").cmid, 115)       # скрытое — только по cmid

    def test_find_says_what_is_wrong(self):
        r = self.both()
        with self.assertRaises(StudyError) as e:
            r.find(self.course, "77")
        self.assertIn("в курсе nettech нет задания «77»", str(e.exception))

    def test_find_in_course_without_assignments(self):
        self.net.reply("POST", ("mod_assign_get_assignments", "courseids[0]=2"),
                       {"courses": [], "warnings": []})
        self.net.reply("POST", ("core_course_get_contents", "courseid=2"),
                       [{"name": "Общее", "modules": [{"id": 221, "name": "Лекции",
                                                       "modname": "resource"}]}])
        r = assigns.Registry(self.m, [2])
        course = Course(2, "num-methods", "Вычислительные методы")
        self.assertEqual(r.works(course), [])
        with self.assertRaises(StudyError) as e:
            r.find(course, "1")
        self.assertIn("в курсе num-methods заданий нет", str(e.exception))

    def test_contents_failure_is_soft(self):
        self.net.reply("POST", ("mod_assign_get_assignments", "courseids[0]=1"),
                       fixture("assignments"))
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"),
                       StudyError("moodle", "HTTP 502"))
        errors = []
        r = assigns.Registry(self.m, [self.course.id],
                             soft=lambda where: soft(errors, where))
        works = r.works(self.course)
        self.assertEqual([w.source for w in works], ["assign_api"] * len(works))
        self.assertTrue(any(w.cmid == 111 for w in works))   # API-задания на месте
        self.assertEqual([e["where"] for e in errors], ["состав курса 1"])

    def test_modules_for_digest(self):
        """Не-assign элементы со сроком строятся тем же конструктором — их берёт сводка;
        mod_assign для них не нужен."""
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"),
                       fixture("course_contents"))
        r = assigns.Registry(self.m, [self.course.id])
        mods = r.modules(self.course, {"choice", "feedback"})
        self.assertEqual({(m.cmid, m.modname) for m in mods},
                         {(116, "choice"), (118, "feedback")})
        self.assertEqual(next(m for m in mods if m.cmid == 118).due, 1790110740)

    def test_as_item_keeps_digest_shape(self):
        r = self.both()
        api = next(x for x in r.works(self.course) if x.cmid == 111).as_item(1789538400)
        hidden = next(x for x in r.works(self.course) if x.cmid == 115).as_item(1789538400)
        self.assertEqual((api["kind"], api["source"], api["assign_id"], api["submission"]),
                         ("assign", "assign_api", 11, None))
        self.assertEqual(api["short"], "ЛР 1 — Vagrant и Packer")
        self.assertEqual(api["due"]["ts"], 1789851540)
        self.assertEqual((hidden["kind"], hidden["source"], hidden.get("assign_id"),
                          hidden["submission"]),
                         ("activity", "course_contents", None, "hidden"))
        self.assertEqual(hidden["lab"], None)


if __name__ == "__main__":
    unittest.main()
