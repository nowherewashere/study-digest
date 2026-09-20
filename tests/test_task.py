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
