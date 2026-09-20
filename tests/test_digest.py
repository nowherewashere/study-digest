import json
import os
import time
import unittest

from study import config as studyconfig
from study import digest, files, local, update
from study.config import Course, StudyError
from study.moodle import Moodle
from tests.fakes import DAY, NOW, FakeNet, config, fixture, patch, repo, tmpdir

DUE = {-5: 1789160340, -3: 1789333140, -2: 1789419540, 1: 1789678740, 3: 1789851540,
       10: 1790456340}      # 23:59 через N дней, как в фикстурах
STATE = {"last_run": NOW - DAY,
         # 13 нет — новое задание; у 12 срок был на день раньше — сдвинут
         "assignments": {"11": DUE[3], "12": DUE[-3], "14": 0, "15": DUE[1], "16": 1793393940,
                         "17": 1785704340, "21": DUE[10]},
         "courses": {"1": "Сетевые технологии", "2": "Вычислительные методы"},
         "grades": {"1": {"Сдать отчет по лабораторной работе № 1. Vagrant и Packer": 8.0}}}
KEYS = {"1": ["121/002-dns.pdf", "122/big.zip", "122/lecture-01.pptx", "122/video.mp4",
              "123/index.html"], "2": ["221/lecture-01.pdf"]}   # состав курсов в фикстурах


def queue(net, since=True):
    """Все ответы ТУИС, которые обходит Collector: курсы 1 (nettech) и 2 (без папки)."""
    net.reply("POST", "core_webservice_get_site_info", fixture("site_info"))
    net.reply("POST", "core_enrol_get_users_courses", fixture("users_courses"))
    net.reply("POST", "mod_assign_get_assignments", fixture("assignments"))
    for aid, status in ((13, "new"), (12, "submitted"), (15, "new"), (11, "new"),
                        (21, "submitted")):
        net.reply("POST", ("mod_assign_get_submission_status", f"assignid={aid}"),
                  fixture(f"submission_status_{status}"))
    net.reply("POST", ("core_course_get_contents", "courseid=1"), fixture("course_contents"))
    net.reply("POST", ("core_course_get_contents", "courseid=2"),
              fixture("course_contents_small"))
    net.reply("POST", "mod_choice_get_choices_by_courses", fixture("choices"))
    net.reply("POST", ("mod_choice_get_choice_options", "choiceid=5"), fixture("choice_options"))
    net.reply("POST", "mod_quiz_get_quizzes_by_courses", fixture("quizzes"))
    net.reply("POST", ("mod_quiz_get_user_attempts", "quizid=7"),
              fixture("quiz_attempts_finished"))
    net.reply("POST", ("mod_quiz_get_user_attempts", "quizid=8"),
              fixture("quiz_attempts_inprogress"))
    if since:
        net.reply("POST", ("core_course_get_updates_since", "courseid=1", f"since={NOW - DAY}"),
                  fixture("updates_since"))
        net.reply("POST", ("core_course_get_updates_since", "courseid=2"),
                  fixture("updates_since_small"))
    net.reply("POST", "core_message_get_messages", fixture("messages"))
    net.reply("POST", ("gradereport_user_get_grade_items", "courseid=1"),
              fixture("grade_items_total"))
    net.reply("POST", ("gradereport_user_get_grade_items", "courseid=2"),
              fixture("grade_items_no_total"))
    net.reply("POST", "core_calendar_get_action_events_by_timesort", fixture("calendar_page1"))
    net.reply("POST", "core_calendar_get_action_events_by_timesort", fixture("calendar_page2"))


def names(items):
    return [a["short"] for a in items]


class DigestCase(unittest.TestCase):
    """Время и пояс зафиксированы: тексты дат в сводке зависят от обоих."""

    @classmethod
    def setUpClass(cls):
        cls._tz = os.environ.get("TZ")
        os.environ["TZ"] = "MSK-3"   # POSIX-строка: не зависит от tzdata
        if hasattr(time, "tzset"):
            time.tzset()
        elif time.strftime("%H:%M", time.localtime(NOW)) != "09:00":
            # Windows: пояс читается из TZ только при старте процесса — задать TZ=MSK-3 снаружи
            raise unittest.SkipTest("нужен TZ=MSK-3 в окружении")

    @classmethod
    def tearDownClass(cls):
        if cls._tz is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = cls._tz
        if hasattr(time, "tzset"):
            time.tzset()

    def setUp(self):
        self.tmp = tmpdir(self)
        self.net = FakeNet().install(self)
        self.cfg = config(self.tmp, "COURSE_IGNORE=4\nCODE 1 nettech\n")
        patch(self, time, "time", lambda: NOW)


class CollectorTest(DigestCase):
    def collect(self, state=STATE):
        queue(self.net, since=bool(state))
        c = digest.Collector(self.cfg, Moodle(self.cfg), 21, state)
        return c, c.run()

    def test_sections(self):
        _, d = self.collect()
        self.assertEqual([x["id"] for x in d["courses"]], [1, 2])   # скрытый 3 и игнор 4 — нет
        self.assertEqual(names(d["deadlines"]),
                         ["ЛР 3 — DHCP", "ЛР 1 — Vagrant и Packer", "Тема доклада к лекции 1",
                          "Доклад к лекции 1", "Опрос о курсе", "ЛР 1"])
        self.assertEqual(names(d["overdue"]), ["ДЗ 1 — Кодирование"])
        self.assertEqual(names(d["submitted"]), ["ЛР 2 — DNS"])
        self.assertEqual(names(d["not_started"]),
                         ["ДЗ 1 — Кодирование", "ЛР 3 — DHCP", "ЛР 1 — Vagrant и Packer"])
        self.assertEqual(names(d["new_assignments"]), ["ДЗ 1 — Кодирование"])
        self.assertEqual([(a["short"], a["was"]["ts"], a["due"]["ts"]) for a in d["moved"]],
                         [("ЛР 2 — DNS", DUE[-3], DUE[-2])])
        # состав курса: скрытое задание — «доступ закрыт»; тема не выбрана — submission "new"
        # (отмеченный вариант — в test_choice_made)
        by = {a["short"]: a for a in d["deadlines"]}
        self.assertEqual((by["Доклад к лекции 1"]["source"], by["Доклад к лекции 1"]["submission"]),
                         ("course_contents", "hidden"))
        self.assertEqual(by["Тема доклада к лекции 1"]["choice"], {"chosen": None, "options": 3})
        self.assertEqual(by["Тема доклада к лекции 1"]["submission"], "new")
        self.assertIsNone(by["Опрос о курсе"]["submission"])
        self.assertEqual(d["submitted"][0]["grade"], "9.50000")
        self.assertEqual((by["ЛР 1"]["course"]["code"], by["ЛР 1"]["lab"]), (None, "01"))
        self.assertEqual(d["errors"], [])

    def test_choice_made(self):
        queue(self.net)
        self.net.drop("mod_choice_get_choice_options")
        opts = fixture("choice_options")
        opts["options"][1]["checked"] = True
        self.net.reply("POST", "mod_choice_get_choice_options", opts)
        d = digest.Collector(self.cfg, Moodle(self.cfg), 21, STATE).run()
        pick = next(a for a in d["deadlines"] if a.get("modname") == "choice")
        self.assertEqual((pick["choice"]["chosen"], pick["submission"]), ("Тема Б", "submitted"))
        self.assertNotIn("Тема доклада", digest.render_digest(d))   # выбранная — как сданная

    def test_quizzes_updates_notifications(self):
        _, d = self.collect()
        q = {x["name"]: x for x in d["quizzes"]}
        self.assertEqual(set(q), {"Тест после лекции №1", "Итоговый тест"})   # без срока и >30 дн
        self.assertEqual((q["Тест после лекции №1"]["submission"],
                          q["Тест после лекции №1"]["open_attempt"],
                          q["Тест после лекции №1"]["attempts_used"],
                          q["Тест после лекции №1"]["timelimit_min"]), ("submitted", False, 1, 30))
        self.assertEqual((q["Итоговый тест"]["submission"], q["Итоговый тест"]["open_attempt"],
                          q["Итоговый тест"]["attempts_max"]), (None, True, None))
        self.assertEqual([(u["item"], u["what"], u["files"]) for u in d["updates"]],
                         [("Методичка 2", "новые файлы", ["002-dns.pdf"]),
                          ("Материалы", "изменены настройки", ["video.mp4", "big.zip"]),
                          ("(модуль 999)", "новые файлы", []),
                          ("Лекции", "новые файлы", ["lecture-01.pdf"])])
        self.assertEqual([n["id"] for n in d["notifications"]], [902])   # без AUTO_EVENTS и старых

    def test_updates_by_snapshot(self):
        # lecture-01.pptx старый (3 дня), но в снимке его не было — новый; ручку updates_since
        # молчащей делаем нарочно: файл, открытый студентам, она тоже не покажет
        state = {**STATE, "files": {"1": [k for k in KEYS["1"] if "pptx" not in k], "2": []}}
        queue(self.net)
        self.net.drop("core_course_get_updates_since", "courseid=1")
        self.net.reply("POST", ("core_course_get_updates_since", "courseid=1"),
                       {"instances": [], "warnings": []})
        d = digest.Collector(self.cfg, Moodle(self.cfg), 21, state).run()
        self.assertEqual([(u["item"], u["what"], u["files"]) for u in d["updates"]],
                         [("Методичка 2", "новые файлы", ["002-dns.pdf"]),
                          ("Материалы", "новые файлы", ["lecture-01.pptx", "video.mp4", "big.zip"]),
                          ("Лекции", "новые файлы", ["lecture-01.pdf"])])

    def test_three_days(self):
        """Полный цикл через снимок на диске: старый снимок без состава → состав записан →
        назавтра в курсе появился файл 2020 года → сводка и --pull его видят → потом тишина."""
        def day(contents, since):
            queue(self.net)
            self.net.drop("core_course_get_contents", "courseid=1")
            self.net.reply("POST", ("core_course_get_contents", "courseid=1"), contents)
            self.net.drop("core_course_get_updates_since")
            for cid in (1, 2):
                self.net.reply("POST", ("core_course_get_updates_since", f"courseid={cid}",
                                        f"since={since}"), {"instances": [], "warnings": []})
            return digest.collect(self.cfg, Moodle(self.cfg))

        patch(self, files, "ROOT", self.tmp)
        old = {"type": "file", "filename": "task-2.pdf", "filesize": 1000, "timemodified": 1.6e9,
               "fileurl": "https://tuis.example/webservice/pluginfile.php/10/mod_resource/"
                          "content/1/task-2.pdf?forcedownload=1"}
        v1 = fixture("course_contents")
        v2 = fixture("course_contents")
        v2[1]["modules"].append({"id": 124, "name": "Задание 2", "modname": "resource",
                                 "contents": [old]})
        self.cfg.state_file().write_text(json.dumps(STATE), encoding="utf-8")   # без files
        d = day(v1, NOW - DAY)   # снимок без состава: только по дате — свежие за сутки
        self.assertEqual([u["item"] for u in d["updates"]], ["Методичка 2", "Материалы", "Лекции"])
        self.assertEqual(json.loads(self.cfg.state_file().read_text(encoding="utf-8"))["files"],
                         KEYS)

        d = day(v2, NOW)
        self.assertEqual([(u["item"], u["files"]) for u in d["updates"]],
                         [("Задание 2", ["task-2.pdf"])])
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"), v2)
        self.net.reply("GET", "task-2.pdf?forcedownload=1&token=test-token", b"%PDF-old")
        errors = []
        digest.pull_updates(self.cfg, Moodle(self.cfg), d, errors)
        self.assertEqual((errors, d["updates"][0]["pulled"]), ([], ["task-2.pdf"]))
        self.assertEqual((self.tmp / "nettech/stash/task-2.pdf").read_bytes(), b"%PDF-old")
        self.assertIn("| nettech | Лабораторные работы | Задание 2: новые файлы | task-2.pdf |",
                      digest.render_digest(d))

        d = day(v2, NOW)
        self.assertEqual(d["updates"], [])
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"), v2)
        d = files.listing(self.cfg, Moodle(self.cfg), Course(1, "nettech", "Сетевые технологии"))
        self.assertEqual((d["tracked"], d["files"]), (True, []))

    def test_grades_and_outside(self):
        _, d = self.collect()
        g = {x["course"]["id"]: x for x in d["grades"]}
        self.assertEqual(g[1]["total"], {"raw": 17.5, "max": 100.0, "computed": False})
        self.assertEqual([(i["short"], i["raw"], i["new"]) for i in g[1]["items"]],
                         [("ЛР 1", 8.0, False), ("ЛР 2", 9.5, True)])   # тест без балла выпал
        self.assertEqual(g[2]["total"], {"raw": 10.0, "max": 100.0, "computed": True})
        self.assertTrue(g[2]["items"][0]["new"])
        self.assertEqual([(o["course"]["id"], o["count"], o["nearest"]["name"])
                          for o in d["outside"]],
                         [(3, 1, "Курсовая")])   # курс 4 в COURSE_IGNORE — не показывается

    def test_snapshot(self):
        c, d = self.collect()
        s = c.snapshot(d)
        self.assertEqual(s["last_run"], NOW)
        self.assertEqual(s["assignments"], {"11": DUE[3], "12": DUE[-2], "13": DUE[-5], "14": 0,
                                            "15": DUE[1], "16": 1793393940, "17": 1785704340,
                                            "21": DUE[10]})
        self.assertEqual(s["courses"], {"1": "Сетевые технологии", "2": "Вычислительные методы"})
        self.assertEqual(s["grades"], {"1": {"Сдать отчет по лабораторной работе № 1. Vagrant и "
                                             "Packer": 8.0,
                                             "Сдать отчет по лабораторной работе № 2. DNS": 9.5},
                                       "2": {"Загрузка 1 лабораторной работы": 10.0}})
        self.assertEqual(s["files"], KEYS)

    def test_snapshot_keeps_files_of_unread_course(self):
        queue(self.net)
        self.net.drop("core_course_get_contents", "courseid=2")
        self.net.reply("POST", ("core_course_get_contents", "courseid=2"),
                       {"exception": "x", "errorcode": "invalidrecord", "message": "no"})
        c = digest.Collector(self.cfg, Moodle(self.cfg), 21, {**STATE, "files": KEYS})
        s = c.snapshot(c.run())
        self.assertEqual(s["files"], KEYS)   # состав курса 2 не прочитался — прошлый список
        self.assertIn("состав курса 2", [e["where"] for e in c.errors])

    def test_first_run(self):
        _, d = self.collect(state={})
        self.assertTrue(d["first_run"])
        self.assertEqual((d["updates"], d["new_assignments"], d["moved"]), ([], [], []))
        self.assertFalse(any(i["new"] for g in d["grades"] for i in g["items"]))
        self.assertEqual([n["id"] for n in d["notifications"]], [902, 903])
        text = digest.render_digest(d)
        self.assertIn("Первый запуск", text)
        self.assertNotIn("Новое в курсах", text)

    def test_soft_errors(self):
        queue(self.net)
        self.net.drop("gradereport_user_get_grade_items")
        self.net.reply("POST", ("gradereport_user_get_grade_items", "courseid=1"),
                       {"exception": "x", "errorcode": "invalidrecord", "message": "no"})
        # выключенный показ оценок — настройка курса, не сбой: молча без строки в «Баллах»
        self.net.reply("POST", ("gradereport_user_get_grade_items", "courseid=2"),
                       {"exception": "x", "errorcode": "nopermissiontoviewgrades", "message": "no"})
        d = digest.Collector(self.cfg, Moodle(self.cfg), 21, STATE).run()
        self.assertEqual(d["grades"], [])
        self.assertEqual([(e["code"], e["where"]) for e in d["errors"]],
                         [("invalidrecord", "оценки, курс 1")])
        self.assertTrue(digest.render_digest(d).endswith(
            "\nНе удалось: moodle · оценки, курс 1 · no."))

    def test_render_golden(self):
        _, d = self.collect()
        self.assertEqual(digest.render_digest(d), fixture("digest.md").rstrip("\n"))

    def test_collect_saves_snapshot(self):
        queue(self.net, since=False)
        d = digest.collect(self.cfg, Moodle(self.cfg))
        self.assertTrue(d["first_run"])
        saved = json.loads(self.cfg.state_file().read_text(encoding="utf-8"))
        self.assertEqual(saved["last_run"], NOW)
        self.assertTrue((self.tmp / "state" / "2026-09-16.json").exists())
        queue(self.net, since=True)
        d = digest.collect(self.cfg, Moodle(self.cfg), save=False, since="1")
        self.assertEqual(d["since"]["ts"], NOW - DAY)
        self.assertEqual(json.loads(self.cfg.state_file().read_text(encoding="utf-8")), saved)

    def test_collect_with_broken_snapshot(self):
        queue(self.net, since=False)
        self.cfg.state_file().write_text("{\"last_run\": 17", encoding="utf-8")
        d = digest.collect(self.cfg, Moodle(self.cfg))
        self.assertTrue(d["first_run"])
        self.assertEqual([e["message"] for e in d["errors"]],
                         [".state.json повреждён, считаю первым запуском"])
        self.assertEqual(json.loads(self.cfg.state_file().read_text(encoding="utf-8"))["last_run"],
                         NOW)   # сохранение вылечило файл


class StateTest(DigestCase):
    """`study state`: репозиторий курса на диске, релизы на хостингах, пара лаба ↔ задание."""

    def setUp(self):
        super().setUp()
        for mod in (local, files, studyconfig):
            patch(self, mod, "ROOT", self.tmp)
        patch(self, update, "check", lambda: None)
        self.repo = repo(self.tmp / "nettech" / "course",
                         {"origin": "ssh://git@gitverse.ru:2222/me/nettech.git",
                          "src": "ssh://ssh.sourcecraft.dev/me/nettech.git"}, tag="v1.1.0")
        (self.repo / "labs/lab01/report/_output").mkdir(parents=True)
        (self.repo / "labs/lab01/report/_output/r.pdf").write_bytes(b"%PDF")
        (self.repo / "labs/lab01/report/r.qmd").write_text("", encoding="utf-8")
        (self.repo / "labs/lab03").mkdir()
        (self.repo / "labs/lab03/todo.txt").write_text("", encoding="utf-8")

    def hosts(self):
        self.net.reply("GET", "api.gitverse.ru/repos/me/nettech/releases",
                       [{"id": 1, "tag_name": "v1.0.0", "name": "lab00",
                         "assets": [{"id": 9, "name": "r.pdf"}]}])
        self.net.reply("GET", "api.sourcecraft.tech/repos/me/nettech/releases",
                       {"releases": [{"id": "b", "tag": "v1.1.0", "title": "lab01",
                                      "status": "PUBLISHED", "assets": []},
                                     {"id": "a", "tag": "v1.0.0", "title": "lab00",
                                      "status": "PUBLISHED", "assets": [{"name": "r.pdf"}]}]})

    def test_local_only(self):
        self.hosts()
        d = digest.state(self.cfg, None, with_tuis=False)
        self.assertIsNone(d["tuis"])
        c = d["courses"][0]
        self.assertEqual(c["dir"], str(self.tmp / "nettech"))
        self.assertEqual((c["code"], c["repo"]["branch"], c["repo"]["last_tag"],
                          c["repo"]["dirty"]), ("nettech", "master", "v1.1.0", ["?? labs/"]))
        self.assertEqual(c["repo"]["remotes"],
                         {"gitverse": "me/nettech", "sourcecraft": "me/nettech"})
        self.assertEqual(c["unreleased_tags"], [{"hosting": "gitverse", "tags": ["v1.1.0"]}])
        self.assertEqual((c["releases"]["sourcecraft"]["latest"]["tag"],
                          c["releases"]["gitverse"]["latest"]["assets"]), ("v1.1.0", 1))
        self.assertEqual([(lab["num"], lab["tuis"], lab["report"]["built"], lab["ready"]["videos"])
                          for lab in c["labs"]],
                         [("01", None, True, False), ("03", None, False, False)])
        text = digest.render(d)
        self.assertIn("ТУИС не опрашивался", text)
        self.assertIn("nettech: незакоммичено 1, нет релиза на gitverse (v1.1.0), "
                      "релиз v1.1.0 на sourcecraft без файлов.", text)

    def test_with_tuis_and_pull(self):
        self.cfg.state_file().write_text(json.dumps(STATE), encoding="utf-8")
        queue(self.net)
        self.hosts()
        self.net.reply("GET", "002-dns.pdf?forcedownload=1&token=test-token", b"%PDF-2")
        d = digest.state(self.cfg, Moodle(self.cfg), save=False, pull=True)
        labs = {lab["num"]: lab for lab in d["courses"][0]["labs"]}
        self.assertEqual((labs["01"]["tuis"]["assign_id"], labs["01"]["tuis"]["matched_by"]),
                         (11, "number"))
        self.assertEqual(labs["03"]["tuis"]["submission"], "new")
        self.assertEqual(labs["01"]["ready"], {"report": True, "presentation": False,
                                                "videos": False, "submitted": False})
        self.assertEqual((self.tmp / "nettech/stash/002-dns.pdf").read_bytes(), b"%PDF-2")
        pulled = {u["item"]: u.get("pulled") for u in d["tuis"]["updates"]}
        # у «(модуль 999)» файлов нет, у курса 2 нет папки — их не трогали
        self.assertEqual(pulled, {"Методичка 2": ["002-dns.pdf"], "Материалы": [],
                                  "(модуль 999)": None, "Лекции": None})
        self.assertEqual(d["errors"], [])
        text = digest.render(d)
        self.assertIn("| nettech | Лабораторные работы | Методичка 2: новые файлы | 002-dns.pdf |",
                      text)
        self.assertIn("video.mp4, big.zip — не скачаны", text)
        self.assertIn("lecture-01.pdf — у курса нет папки", text)

    def test_hosting_error_is_soft(self):
        self.net.reply("GET", "api.gitverse.ru", StudyError("gitverse", "HTTP 401: bad token"))
        self.net.reply("GET", "api.sourcecraft.tech", {"releases": []})
        d = digest.state(self.cfg, None, with_tuis=False)
        self.assertEqual(d["courses"][0]["releases"]["gitverse"], {"ok": False, "latest": None})
        self.assertEqual([e["where"] for e in d["errors"]], ["gitverse, курс nettech"])
