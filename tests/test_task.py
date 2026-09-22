import unittest

from study import fmt, local, task
from study.config import Course, StudyError
from study.moodle import Moodle
from tests.fakes import FakeNet, config, fixture, patch, repo, tmpdir


class TaskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        for mod in (local, task):
            patch(self, mod, "ROOT", self.tmp)
        self.net = FakeNet().install(self)
        self.cfg = config(self.tmp, "CODE 1 nettech\n")
        self.m = Moodle(self.cfg)
        self.course = Course(1, "nettech", "Сетевые технологии")
        self.net.reply("POST", ("mod_assign_get_assignments", "courseids[0]=1"),
                       fixture("assignments"))
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"),
                       fixture("course_contents"))

    def test_lab_by_number_file_flow(self):
        # репозитория нет → профиль file: смотрим <код>/lab01, stash по номеру
        lab = self.tmp / "nettech" / "lab01" / "report" / "_output"
        lab.mkdir(parents=True)
        (lab / "r.pdf").write_bytes(b"%PDF")
        stash = self.tmp / "nettech" / "stash"
        stash.mkdir()
        for name in ("001-intro.pdf", "lab-1.pdf", "02.03.01 ФОС.doc", "lecture-10.pdf"):
            (stash / name).write_bytes(b"x")
        self.net.reply("POST", ("mod_assign_get_submission_status", "assignid=11"),
                       fixture("submission_status_new"))
        d = task.build(self.cfg, self.m, self.course, "1")
        self.assertEqual((d["assign_id"], d["num"], d["flow"], d["grade"], d["feedback"]),
                         (11, "01", "file", None, None))
        self.assertEqual(d["local"], {"kind": "file", "path": str(lab.parents[1]),
                                      "exists": True, "pdfs": [str(lab / "r.pdf")]})
        self.assertEqual(d["stash"], ["001-intro.pdf", "lab-1.pdf"])
        self.assertEqual(d["accepts_line"],
                         "текст — да, до 500 слов · файлы — до 2, типы .pdf, до 10 МБ")
        text = task.render(d)
        self.assertTrue(text.startswith("ЛР 1 — Vagrant и Packer · nettech · id 11 · cmid 111\n"))
        self.assertIn("Состояние: не сдано\n", text)
        self.assertIn("Локально (file): {} — есть, PDF: {}\n".format(lab.parents[1], lab / "r.pdf"),
                      text)
        self.assertIn("В stash (возможно по теме): 001-intro.pdf, lab-1.pdf", text)
        self.assertTrue(text.endswith("\n\nСдать отчет по лабораторной работе № 1. Vagrant и "
                                      "Packer"))
        self.assertNotIn("<p>", text)

    def test_by_id_release_flow(self):
        r = repo(self.tmp / "nettech" / "course", {"origin": "ssh://git@gitverse.ru:2222/me/n.git"})
        (r / "labs" / "lab02" / "report" / "_output").mkdir(parents=True)
        (r / "labs" / "lab02" / "report" / "_output" / "nettech-lab02-report.pdf").write_bytes(b"%")
        self.net.reply("POST", ("mod_assign_get_submission_status", "assignid=12"),
                       fixture("submission_status_submitted"))
        d = task.build(self.cfg, self.m, self.course, "12")   # лабы № 12 нет → это id
        self.assertEqual((d["assign_id"], d["num"], d["flow"], d["grade"], d["grade_text"]),
                         (12, "02", "release", "9.50000", "9,50 / 10,00"))
        self.assertEqual((d["local"]["kind"], d["local"]["report"]["built"],
                          d["local"]["presentation"]["built"], d["local"]["videos"]["filled"]),
                         ("release", True, False, 0))
        text = task.render(d)
        self.assertIn("Состояние: сдано · балл 9.50000 (9,50 / 10,00) · изменён "
                      + fmt.moment(1789333140)["full"], text)
        self.assertIn("Локально (release): {} — отчёт pdf есть, презентация нет, видео 0/10, "
                      "заготовка ответа нет; вложения: ".format(r / "labs" / "lab02"), text)

    def test_not_found(self):
        with self.assertRaises(StudyError) as e:
            task.build(self.cfg, self.m, self.course, "7")
        self.assertEqual(e.exception.message,
                         "в курсе nettech нет задания «7»: study assigns --course nettech")
        self.net.reply("POST", ("mod_assign_get_assignments", "courseids[0]=1"),
                       fixture("assignments"))
        with self.assertRaises(StudyError):
            task.build(self.cfg, self.m, self.course, "hw1")

    def test_by_cmid(self):
        """Сводка называет задание по cmid — карточка должна открываться и по нему."""
        self.net.reply("POST", ("mod_assign_get_submission_status", "assignid=11"),
                       fixture("submission_status_new"))
        d = task.build(self.cfg, self.m, self.course, "111")
        self.assertEqual((d["assign_id"], d["cmid"], d["available"]), (11, 111, True))

    def test_hidden_assign_card(self):
        """Задание с ограничением доступа: mod_assign его не отдаёт, статус не спросить —
        карточка строится из состава курса и называет причину."""
        d = task.build(self.cfg, self.m, self.course, "115")
        self.assertEqual((d["assign_id"], d["cmid"], d["available"], d["source"]),
                         (None, 115, False, "course_contents"))
        self.assertEqual(d["due"]["ts"], 1790024340)
        self.assertIn("НФИбд-01-24", d["reason"])
        self.assertEqual(d["submission"]["status"], "hidden")
        text = task.render(d)
        self.assertIn("Состояние: доступ закрыт · Недоступно, пока не выполнены "
                      "условия: Вы принадлежите к группе НФИбд-01-24", text)
        self.assertTrue(text.startswith("Доклад к лекции 1 · nettech · cmid 115\n"))
        self.assertIn("Принимает: —", text)
        self.assertIn("Доклад по теме лекции 1", text)
        self.assertEqual(self.net.calls("mod_assign_get_submission_status"), [])

    def test_contents_failure_is_reported(self):
        """Состав курса не прочитался: задание из mod_assign находится, но молчать нельзя —
        иначе «нет задания» по скрытой работе выглядит как ошибка в номере."""
        self.net.drop("core_course_get_contents")
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"),
                       StudyError("moodle", "HTTP 502"))
        self.net.reply("POST", ("mod_assign_get_submission_status", "assignid=11"),
                       fixture("submission_status_new"))
        d = task.build(self.cfg, self.m, self.course, "1")
        self.assertEqual([e["where"] for e in d["warnings"]], ["состав курса 1"])
        self.assertIn("Не удалось: moodle · состав курса 1 · HTTP 502", task.render(d))

    def test_course_without_assignments(self):
        """У курса, который в ТУИС ничего не принимает, подсказка про study assigns бесполезна."""
        self.net.drop("mod_assign_get_assignments")
        self.net.drop("core_course_get_contents")
        self.net.reply("POST", ("mod_assign_get_assignments", "courseids[0]=1"),
                       {"courses": [], "warnings": []})
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"),
                       [{"name": "Общее", "modules": []}])
        with self.assertRaises(StudyError) as e:
            task.build(self.cfg, self.m, self.course, "1")
        self.assertIn("в курсе nettech заданий нет", e.exception.message)
