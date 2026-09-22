import argparse
import unittest

from study import cli, fmt, net
from study.config import StudyError
from study.moodle import (PAGE, Moodle, accepts, accepts_line, check_state, check_submission,
                          grade_of, submission_state)
from tests.fakes import FakeNet, config, fixture, tmpdir

SERVER = "https://tuis.example/webservice/rest/server.php"


class MoodleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.net = FakeNet().install(self)
        self.m = Moodle(config(self.tmp))

    def test_call_form(self):
        self.net.reply("POST", "mod_quiz_get_quizzes_by_courses", {"quizzes": []})
        self.assertEqual(self.m.quizzes([1, 2]), [])
        req = self.net.sent[0]
        self.assertEqual(req["url"], SERVER)
        self.assertEqual(req["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        # массивы кодируются по-Moodle, токен и формат — в каждой форме
        self.assertEqual(req["form"], {"wstoken": "test-token", "moodlewsrestformat": "json",
                                       "wsfunction": "mod_quiz_get_quizzes_by_courses",
                                       "courseids[0]": "1", "courseids[1]": "2"})
        self.assertEqual((req["where"], req["retries"]),
                         ("mod_quiz_get_quizzes_by_courses", net.RETRIES))   # чтение — с повторами

    def test_call_skips_none_and_empty_list(self):
        self.net.reply("POST", "core_calendar_get_action_events_by_timesort", {"events": []})
        self.m.calendar(1, 2)
        form = self.net.calls("core_calendar_get_action_events_by_timesort")[0]
        self.assertNotIn("aftereventid", form)
        self.net.reply("POST", "mod_assign_get_assignments", {"courses": [], "warnings": []})
        self.m.assignments()
        self.assertNotIn("courseids[0]", self.net.calls("mod_assign_get_assignments")[0])

    def test_error_in_body_with_http_200(self):
        self.net.reply("POST", "core_webservice_get_site_info",
                       {"exception": "moodle_exception", "errorcode": "invalidtoken",
                        "message": "Invalid token - token not found"})
        with self.assertRaises(StudyError) as e:
            self.m.me()
        err = e.exception
        self.assertEqual((err.source, err.code, err.where),
                         ("moodle", "invalidtoken", "core_webservice_get_site_info"))
        self.assertIn("Ключи безопасности", err.hint())

    def test_me_cached_and_functions(self):
        self.net.reply("POST", "core_webservice_get_site_info", fixture("site_info"))
        self.assertEqual(self.m.me()["userid"], 100)
        self.assertEqual(self.m.functions()[0], "core_course_get_contents")   # без сети: кэш
        self.assertEqual(len(self.net.sent), 1)

    def test_courses_hidden(self):
        self.net.reply("POST", "core_webservice_get_site_info", fixture("site_info"))
        self.net.reply("POST", "core_enrol_get_users_courses", fixture("users_courses"))
        self.assertEqual([c["id"] for c in self.m.courses()], [1, 2, 4])
        self.assertEqual(self.net.calls("core_enrol_get_users_courses")[0]["userid"], "100")
        self.net.reply("POST", "core_enrol_get_users_courses", fixture("users_courses"))
        self.assertEqual(len(self.m.courses(include_hidden=True)), 4)

    def test_assignments_warnings(self):
        self.net.reply("POST", "mod_assign_get_assignments", fixture("assignments"))
        courses, warnings = self.m.assignments([1])
        self.assertEqual(self.net.calls("mod_assign_get_assignments")[0]["courseids[0]"], "1")
        self.assertEqual([c["id"] for c in courses], [1, 2, 4])
        self.assertEqual(warnings[0]["itemid"], 115)

    def test_contents_cached(self):
        self.net.reply("POST", ("core_course_get_contents", "courseid=1"),
                       fixture("course_contents"))
        first = self.m.contents(1)
        self.assertIs(self.m.contents(1), first)
        self.assertEqual(len(self.net.sent), 1)

    def test_calendar_pages_by_cursor(self):
        self.net.reply("POST", "core_calendar_get_action_events_by_timesort",
                       fixture("calendar_page1"))
        self.net.reply("POST", "core_calendar_get_action_events_by_timesort",
                       fixture("calendar_page2"))
        events = self.m.calendar(100, 200)
        self.assertEqual(len(events), PAGE + 3)
        first, second = self.net.calls("core_calendar_get_action_events_by_timesort")
        self.assertEqual((first["timesortfrom"], first["timesortto"], first["limitnum"]),
                         ("100", "200", str(PAGE)))
        self.assertNotIn("aftereventid", first)
        # вторая страница — курсором, окно то же: события с равным timesort на границе целы
        self.assertEqual(second["aftereventid"], "1050")
        self.assertEqual((second["timesortfrom"], second["timesortto"]), ("100", "200"))
        boundary = [e["id"] for e in events if e["timesort"] == events[-3]["timesort"]]
        self.assertEqual(boundary, [1004, 1024, 1044, 1049, 1050, 1051])

    def test_quiz_attempts_and_choices(self):
        self.net.reply("POST", ("mod_quiz_get_user_attempts", "quizid=7", "status=all"),
                       fixture("quiz_attempts_finished"))
        self.assertEqual(self.m.quiz_attempts(7)[0]["state"], "finished")
        self.net.reply("POST", ("mod_choice_get_choice_options", "choiceid=5"),
                       fixture("choice_options"))
        opts = self.m.choice_options(5)
        self.assertEqual(([o["text"] for o in opts], [o for o in opts if o["checked"]]),
                         (["Тема А", "Тема Б", "Тема В"], []))
        self.net.reply("POST", ("mod_choice_get_choices_by_courses", "courseids[0]=1"),
                       fixture("choices"))
        self.assertEqual(self.m.choices({1})[0]["coursemodule"], 116)

    def test_notifications_params(self):
        self.net.reply("POST", "core_webservice_get_site_info", fixture("site_info"))
        self.net.reply("POST", "core_message_get_messages", fixture("messages"))
        self.assertEqual(len(self.m.notifications(limit=20)), 5)
        form = self.net.calls("core_message_get_messages")[0]
        self.assertEqual({k: form[k] for k in ("useridto", "useridfrom", "type", "read",
                                                "newestfirst", "limitnum")},
                         {"useridto": "100", "useridfrom": "0", "type": "notifications",
                          "read": "0", "newestfirst": "1", "limitnum": "20"})

    def test_grades_and_updates(self):
        self.net.reply("POST", "core_webservice_get_site_info", fixture("site_info"))
        self.net.reply("POST", ("gradereport_user_get_grade_items", "courseid=1", "userid=100"),
                       fixture("grade_items_total"))
        self.assertEqual(self.m.grades(1)[0]["courseid"], 1)
        self.net.reply("POST", ("core_course_get_updates_since", "courseid=1", "since=5"),
                       fixture("updates_since"))
        self.assertEqual(len(self.m.updates_since(1, 5)), 4)

    def test_download_token_in_query(self):
        self.net.reply("GET", "pluginfile.php/10/a.pdf?token=test-token", b"%PDF")
        self.assertEqual(self.m.download("https://tuis.example/pluginfile.php/10/a.pdf"), b"%PDF")
        self.net.reply("GET", "b.pdf?forcedownload=1&token=test-token", b"%PDF")
        self.m.download("https://tuis.example/pluginfile.php/10/b.pdf?forcedownload=1")
        self.assertEqual(self.net.sent[-1]["where"], "pluginfile")

    def test_upload_chain_and_error(self):
        a, b = self.tmp / "a.pdf", self.tmp / "b.zip"
        a.write_bytes(b"AAA")
        b.write_bytes(b"BB")
        self.net.reply("POST", "/webservice/upload.php", [{"itemid": 77, "filename": "a.pdf"}])
        self.net.reply("POST", "/webservice/upload.php", [{"itemid": 77, "filename": "b.zip"}])
        self.assertEqual(self.m.upload([a, b]), 77)
        first, second = self.net.sent
        self.assertTrue(first["headers"]["Content-Type"].startswith("multipart/form-data"))
        self.assertEqual(first["fields"], {"token": "test-token", "filearea": "draft",
                                           "itemid": "0"})
        self.assertEqual(first["files"], {"file_1": ("a.pdf", b"AAA", "application/octet-stream")})
        self.assertEqual(second["fields"]["itemid"], "77")   # второй файл — в тот же itemid
        self.assertEqual(second["files"]["file_1"][:2], ("b.zip", b"BB"))
        self.assertEqual(first["timeout"], 900)
        self.net.reply("POST", "/webservice/upload.php", {"error": "File is too large",
                                                          "errorcode": "maxbytes"})
        with self.assertRaises(StudyError) as e:
            self.m.upload([a], itemid=77)
        self.assertEqual(e.exception.message, "File is too large")

    def test_save_submission(self):
        self.net.reply("POST", "mod_assign_save_submission", [])
        self.m.save_submission(11, "# Ответ", itemid=77)
        self.assertEqual(self.net.sent[-1]["retries"], 0)   # необратимо — без повторов
        form = self.net.calls("mod_assign_save_submission")[0]
        self.assertEqual({k: v for k, v in form.items() if k.startswith(("assign", "plugin"))},
                         {"assignmentid": "11", "plugindata[onlinetext_editor][text]": "# Ответ",
                          "plugindata[onlinetext_editor][format]": "4",
                          "plugindata[onlinetext_editor][itemid]": "0",
                          "plugindata[files_filemanager]": "77"})
        self.net.reply("POST", "mod_assign_save_submission", [])
        self.m.save_submission(11, None)
        self.assertNotIn("plugindata[onlinetext_editor][text]",
                         self.net.calls("mod_assign_save_submission")[1])


def assignment(aid):
    return next(a for c in fixture("assignments")["courses"] for a in c["assignments"]
                if a["id"] == aid)


class AcceptsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.pdf = self.tmp / "report.pdf"
        self.pdf.write_bytes(b"%PDF" * 10)

    def test_accepts(self):
        self.assertEqual(accepts(assignment(11)),
                         {"files": {"enabled": True, "max": 2, "max_bytes": 10485760,
                                    "types": [".pdf"]},
                          "text": {"enabled": True, "words": 500}})
        self.assertEqual(accepts(assignment(12)),
                         {"files": {"enabled": True, "max": 20, "max_bytes": None, "types": []},
                          "text": {"enabled": False, "words": None}})
        self.assertIsNone(accepts(assignment(13)))   # configs нет — не проверяем
        self.assertEqual(accepts_line(accepts(assignment(11))),
                         "текст — да, до 500 слов · файлы — до 2, типы .pdf, до 10 МБ")
        self.assertEqual(accepts_line(accepts(assignment(21))),
                         "текст — нет · файлы — до 3, типы document, до 20 МБ")
        self.assertEqual(accepts_line(None), "неизвестно (у задания нет configs)")

    def test_check(self):
        acc = accepts(assignment(11))
        self.assertEqual(check_submission(acc, "# Ответ", [self.pdf]), [])
        self.assertEqual(check_submission(acc, None, [], None),
                         ["нечего отправлять: ни --text, ни --attach, ни --files"])
        zip_ = self.tmp / "src.zip"
        zip_.write_bytes(b"PK")
        big = self.tmp / "big.pdf"
        big.write_bytes(b"0" * (10485760 + 1))
        self.assertEqual(check_submission(acc, "слово " * 501, [self.pdf, zip_, big]),
                         ["текст длиннее лимита: 501 слов, можно 500",
                          "файлов 3, задание принимает до 2",
                          "src.zip: тип .zip не из списка .pdf",
                          "big.pdf: 10 МБ, предел 10 МБ"])
        self.assertEqual(check_submission(accepts(assignment(12)), "x", [self.tmp / "нет.pdf"]),
                         ["нет файла " + str(self.tmp / "нет.pdf"),
                          "текст ответа в задании выключен — только файлы"])
        # группа типов Moodle (document) не разворачивается — расширение не проверяется
        self.assertEqual(check_submission(accepts(assignment(21)), None, [zip_]), [])
        self.assertEqual(check_submission(None, None, [zip_]), [])   # настроек нет — пропускаем


class GradeOfTest(unittest.TestCase):
    def test_grade_of(self):
        self.assertEqual(grade_of(fixture("submission_status_submitted")), "9.50000")
        self.assertIsNone(grade_of(fixture("submission_status_new")))
        self.assertIsNone(grade_of({"feedback": {"grade": {"grade": "-1.00000"}}}))
        self.assertIsNone(grade_of({"feedback": {"grade": {"grade": "n/a"}}}))
        self.assertEqual(grade_of({"feedback": {"grade": {"grade": "0.00000"}}}), "0.00000")


class AssignsTest(unittest.TestCase):
    def test_intro_in_json_only(self):
        tmp = tmpdir(self)
        net_ = FakeNet().install(self)
        net_.reply("POST", "mod_assign_get_assignments", fixture("assignments"))
        data, text = cli.cmd_assigns(config(tmp), argparse.Namespace(course=None))
        row = next(r for r in data["assignments"] if r["assign_id"] == 11)
        self.assertEqual(row["intro"], "Сдать отчет по лабораторной работе № 1. Vagrant и Packer")
        self.assertNotIn("<p>", text)
        self.assertIn("id=11 cmid=111", text)

    def test_hidden_rows_when_course_known(self):
        """С указанным курсом виден и состав курса: задания, которых mod_assign не отдал,
        печатаются строками с причиной, а не счётчиком «Скрыто ограничением доступа»."""
        tmp = tmpdir(self)
        net_ = FakeNet().install(self)
        net_.reply("POST", ("mod_assign_get_assignments", "courseids[0]=1"),
                   fixture("assignments"))
        net_.reply("POST", ("core_course_get_contents", "courseid=1"), fixture("course_contents"))
        data, text = cli.cmd_assigns(config(tmp, "CODE 1 nettech\n"),
                                     argparse.Namespace(course="nettech"))
        row = next(r for r in data["assignments"] if r["cmid"] == 115)
        self.assertEqual((row["assign_id"], row["available"], row["source"]),
                         (None, False, "course_contents"))
        self.assertIn("cmid=115", text)
        self.assertIn("доступ закрыт: Недоступно", text)
        self.assertNotIn("Скрыто ограничением доступа", text)


class SubmitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.net = FakeNet().install(self)
        self.cfg = config(self.tmp)
        self.pdf = self.tmp / "report.pdf"
        self.pdf.write_bytes(b"%PDF" * 300)

    def submit(self, status="new", assignments=None, **kw):
        """Один вызов cmd_submit: ответы на задания и статус ставятся на каждый вызов."""
        args = argparse.Namespace(assign_id=11, text=None, attach=None, files=None, confirm=False)
        vars(args).update(kw)
        self.net.drop("mod_assign_get_assignments")
        self.net.reply("POST", "mod_assign_get_assignments", assignments or fixture("assignments"))
        st = fixture(f"submission_status_{status}") if isinstance(status, str) else status
        self.net.reply("POST", ("mod_assign_get_submission_status", f"assignid={args.assign_id}"),
                       st)
        return cli.cmd_submit(self.cfg, args)

    def assignment(self, aid, **patch):
        d = fixture("assignments")
        for c in d["courses"]:
            for a in c["assignments"]:
                if a["id"] == aid:
                    a.update(patch)
        return d

    def test_unknown_assign_id_refused(self):
        """id, которого нет в mod_assign (часто это cmid из сводки или закрытое задание):
        отказ до похода за статусом, иначе Moodle ответит невнятной ошибкой."""
        args = argparse.Namespace(assign_id=115, text=None, attach=None, files=None, confirm=True)
        self.net.reply("POST", "mod_assign_get_assignments", fixture("assignments"))
        plan, _text, rc = cli.cmd_submit(self.cfg, args)
        self.assertEqual(rc, 1)
        self.assertIn("задание id 115 не найдено", " ".join(plan["problems"]))
        self.assertEqual(self.net.calls("mod_assign_get_submission_status"), [])

    def test_plan(self):
        plan, text, rc = self.submit(attach=[str(self.pdf)])
        self.assertEqual((rc, plan["problems"], plan["attach"]),
                         (1, [], [{"name": "report.pdf", "bytes": 1200}]))
        self.assertIn("принимает: текст — да, до 500 слов · файлы — до 2, типы .pdf, до 10 МБ",
                      text)
        self.assertIn("вложения: report.pdf (1 КБ)", text)
        self.assertIn("состояние: не сдано\n", text)
        self.assertIn("после сохранения: сразу сдача (submissiondrafts=0)", text)
        self.assertIn("Повтори с --confirm", text)
        self.assertEqual(self.net.calls("mod_assign_save_submission"), [])

    def test_refused_even_with_confirm(self):
        zip_ = self.tmp / "src.zip"
        zip_.write_bytes(b"PK")
        plan, text, rc = self.submit(attach=[str(zip_)], confirm=True)
        self.assertEqual((rc, plan["problems"]), (1, ["src.zip: тип .zip не из списка .pdf"]))
        self.assertIn("Нельзя отправить:\n  – src.zip", text)
        self.assertEqual([r["url"] for r in self.net.sent if "upload" in r["url"]], [])

    def test_confirm_uploads_and_submits(self):
        self.net.reply("POST", "/webservice/upload.php", [{"itemid": 77, "filename": "report.pdf"}])
        self.net.reply("POST", "mod_assign_save_submission", [])
        plan, text = self.submit(attach=[str(self.pdf)], confirm=True)
        self.assertEqual(plan["files_itemid"], 77)
        self.assertEqual(text, "Отправлено: Сдать отчет по лабораторной работе № 1. Vagrant и "
                               "Packer (id 11)")
        form = self.net.calls("mod_assign_save_submission")[0]
        self.assertEqual(form["plugindata[files_filemanager]"], "77")
        self.assertNotIn("plugindata[onlinetext_editor][text]", form)

    def test_text_disabled(self):
        note = self.tmp / "answer.md"
        note.write_text("# Ответ", encoding="utf-8")
        plan, text, rc = self.submit(assign_id=12, text=str(note), files=77)
        self.assertEqual((rc, plan["problems"]),
                         (1, ["текст ответа в задании выключен — только файлы"]))
        self.assertIn("вложения: itemid 77 (состав по itemid не виден, не проверяется)", text)

    def test_closed_locked_graded_opens_offline(self):
        # приём закрыт: cutoff = срок (13), canedit false
        plan, text, rc = self.submit(assign_id=13, status="closed", attach=[str(self.pdf)])
        why = (f"приём закрыт {fmt.moment(1789160340)['full']} — нужна «Пересдача …» или "
               "разрешение преподавателя")
        self.assertEqual((rc, plan["problems"]), (1, [why]))
        self.assertEqual(self.net.calls("mod_assign_save_submission"), [])
        st = fixture("submission_status_new")
        st["lastattempt"].update({"locked": True, "canedit": False})
        plan, _, _ = self.submit(status=st, attach=[str(self.pdf)], confirm=True)
        self.assertEqual(plan["problems"][0][:29], "заблокировано преподавателем ")
        plan, text, _ = self.submit(assign_id=12, status="submitted", attach=[str(self.pdf)])
        self.assertEqual(plan["problems"][0][:22], "уже оценено (9.50000) ")
        self.assertIn("состояние: сдано — отправка заменит прежний ответ", text)
        later = self.assignment(11, allowsubmissionsfromdate=4102444800)
        plan, _, _ = self.submit(assignments=later, attach=[str(self.pdf)])
        self.assertEqual(plan["problems"], [f"приём откроется {fmt.moment(4102444800)['full']}"])
        st = fixture("submission_status_new")
        st["lastattempt"]["submissionsenabled"] = False
        plan, _, _ = self.submit(status=st, attach=[str(self.pdf)])
        self.assertEqual(plan["problems"],
                         ["у задания нет ответа в ТУИС (очная сдача) — отправлять нечего"])
        self.assertEqual(self.net.calls("mod_assign_save_submission"), [])

    def test_drafts_submit_for_grading(self):
        self.net.reply("POST", "/webservice/upload.php", [{"itemid": 77, "filename": "report.pdf"}])
        self.net.reply("POST", "mod_assign_save_submission", [])
        self.net.reply("POST", "mod_assign_submit_for_grading", [])
        plan, text = self.submit(assignments=self.assignment(11, submissiondrafts=1,
                                                             requiresubmissionstatement=1),
                                 attach=[str(self.pdf)], confirm=True)
        self.assertEqual((plan["drafts"], plan["statement"], plan["submitted"]), (True, True, []))
        form = self.net.calls("mod_assign_submit_for_grading")[0]
        self.assertEqual((form["assignmentid"], form["acceptsubmissionstatement"]), ("11", "1"))
        self.assertEqual(self.net.sent[-1]["retries"], 0)   # необратимо — без повторов
        self.assertTrue(text.startswith("Отправлено"))
        _, text, _ = self.submit(assignments=self.assignment(11, submissiondrafts=1),
                                 attach=[str(self.pdf)])
        self.assertIn("после сохранения: отправка на проверку (submissiondrafts=1)\n", text)

    def test_warning_is_error(self):
        # отказ Moodle приходит как HTTP 200 и warnings — «Отправлено» печатать нельзя
        self.net.reply("POST", "/webservice/upload.php", [{"itemid": 77, "filename": "report.pdf"}])
        self.net.reply("POST", "mod_assign_save_submission",
                       [{"item": "The due date for this assignment has now passed", "itemid": 11,
                         "warningcode": "couldnotsavesubmission",
                         "message": "Could not save submission."}])
        with self.assertRaises(StudyError) as e:
            self.submit(attach=[str(self.pdf)], confirm=True)
        self.assertEqual((e.exception.code, e.exception.where),
                         ("couldnotsavesubmission", "mod_assign_save_submission"))
        self.assertIn("The due date for this assignment has now passed", e.exception.message)
        self.assertEqual(self.net.calls("mod_assign_submit_for_grading"), [])


class SubmissionStateTest(unittest.TestCase):
    def test_rules(self):
        new, now = fixture("submission_status_new"), 1789538400
        a = {"duedate": now - 100, "cutoffdate": now - 100, "allowsubmissionsfromdate": 0}
        s = submission_state(a, new, now)
        self.assertEqual((s["status"], s["closed"], s["graded"], s["due"], s["cutoff"]),
                         ("new", False, False, now - 100, now - 100))   # canedit true — открыто
        s = submission_state(a, fixture("submission_status_closed"), now)
        self.assertEqual((s["status"], s["closed"], s["canedit"]), ("new", True, False))
        s = submission_state({**a, "teamsubmission": 1}, fixture("submission_status_team"), now)
        self.assertEqual((s["status"], s["team"], s["closed"]), ("submitted", True, False))
        s = submission_state({**a, "nosubmissions": 1}, new, now)
        self.assertEqual((s["status"], s["closed"]), ("offline", False))
        graded = fixture("submission_status_submitted")
        graded["lastattempt"]["submission"]["status"] = "new"   # очная защита оценена без файла
        s = submission_state({**a, "nosubmissions": 1}, graded, now)
        self.assertEqual((s["status"], s["graded"], s["grade"]), ("submitted", True, "9.50000"))
        ext = fixture("submission_status_closed")
        ext["lastattempt"].update({"extensionduedate": now + 500, "canedit": True})
        s = submission_state(a, ext, now)
        self.assertEqual((s["due"], s["cutoff"], s["closed"]), (now + 500, now + 500, False))
        s = submission_state({**a, "allowsubmissionsfromdate": now + 9}, ext, now)
        self.assertEqual(s["opens"], now + 9)
        # сдано (оценено очно) и приём откроется позже: причина отказа — оценка, не «откроется»
        s = submission_state({**a, "allowsubmissionsfromdate": now + 9}, graded, now)
        s["canedit"] = False
        self.assertEqual(check_state(s, str)[0][:21], "уже оценено (9.50000)")
        s["grade"] = None   # graded, но балла нет (marking workflow) — без «(None)»
        self.assertEqual(check_state(s, str)[0][:13], "уже оценено —")
        s = submission_state({}, {}, now)   # статус не получен: ничего не утверждаем
        self.assertEqual((s["status"], s["canedit"], s["closed"], s["due"]),
                         ("new", None, False, None))
