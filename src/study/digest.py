"""Сводка по ТУИС: сбор данных в структуру и рендер.

Данные и рендер разделены: `--json` отдаёт ровно то, что видит рендер, без второго обхода API.
"""
import contextlib
import time

from . import files, hosting, local, update
from .config import Course, StudyError
from .fmt import md_table, moment, parse_name, plain, short_name, weekday
from . import moodle as moodle_api
from .moodle import PENDING, submission_state
from .snapshot import load_state, save_state

# Что считаем новостью в core_course_get_updates_since; остальное (submissions, grades,
# answers) — своя же активность и чужие голоса, то есть шум.
USEFUL = {"contentfiles", "introfiles", "configuration", "contents", "files"}
FILES = {"contentfiles", "files", "contents"}
# Сроки в составе курса: машинные идентификаторы, а не подписи — подпись зависит от языка.
DATE_IDS = {"duedate", "timeclose"}
KINDS = {"assign": "задание", "choice": "выбор темы",
         "workshop": "взаимная проверка", "feedback": "опрос"}
SUBMISSION = {**moodle_api.SUBMISSION, "hidden": "доступ закрыт"}
# Уведомления, которые Moodle шлёт сам: про наши же действия, про сроки (они уже в таблице)
# и про входы в аккаунт. Отсев по eventtype, а не по теме: тема зависит от языка.
AUTO_EVENTS = {"assign_due_soon", "assign_due_digest", "assign_notification", "newlogin"}
DAY = 86400
URGENT = 2 * DAY
HOT = 7 * DAY       # «Горит»: несданное, что просрочено или на этой неделе
MONTH = 30 * DAY


@contextlib.contextmanager
def soft(errors, where):
    """Мягкая ошибка: копится в списке и не роняет сводку, но и не теряется."""
    try:
        yield
    except StudyError as e:
        errors.append({**e.as_dict(), "where": where})


def pending(a):
    """Работа не сдана: ждёт ответа (не начато, черновик, на доработку), статус неизвестен
    или ответа в ТУИС нет вовсе (очно) — в просроченное, но не в «Горит»: слать нечего."""
    return a["submission"] in PENDING or a["submission"] in (None, "offline")


def news(course, m, section, what):
    """Строка «Новое в курсах» для модуля курса."""
    return {"course": course, "section": section, "item": m["name"],
            "modname": m.get("modname", ""), "files": [], "what": what}


def lab_number(name, work="lab"):
    """Номер лабы из названия задания (labNN); у домашних и докладов каталога нет."""
    p = parse_name(name)
    return p["num"].zfill(2) if p and p["work"] == work else None


def by_due(items):
    return sorted(items, key=lambda x: x["due"]["ts"])


class Collector:
    """Один обход ТУИС. Каждый метод — раздел сводки; общее (окно, снимок, курсы) — в атрибутах."""

    def __init__(self, cfg, moodle, days, state, errors=()):
        self.moodle = moodle
        self.now = int(time.time())
        self.days = days
        self.horizon = self.now + days * DAY
        self.since = state.get("last_run")            # None — первый запуск
        self.known = state.get("assignments", {})     # id задания → срок с прошлого запуска
        self.graded = state.get("grades")             # {курс: {работа: балл}}; None — нет снимка
        self.files = state.get("files")               # {курс: [cmid/файл]}; None — нет состава
        self.seen_courses = state.get("courses")      # {id: название}; None — снимка нет
        self.fb = state.get("feedback")               # {id задания: отзыв}; None — снимка нет
        self.announced = state.get("announcements")   # {курс: [id обсуждений]}; None — нет
        self._forums = {}                             # курс → [id обсуждений], что прочитали
        self.errors = list(errors)                    # с чем пришёл снимок
        self.courses = {c.id: c for c in cfg.track(moodle.courses())}
        self.ignore = cfg.ignore()   # решение пользователя: этих курсов в сводке нет вовсе
        self.assigns = {}       # id задания → строка сводки (для снимка)
        self.raw = {}           # id задания → сырое задание из mod_assign_get_assignments
        self.asked = set()      # задания, чей статус уже запрошен
        self.soon, self.overdue = [], []
        self._contents = {}

    def soft(self, where):
        return soft(self.errors, where)

    def course(self, cid):
        c = self.courses.get(cid)
        return c.as_dict() if c else {"id": cid, "code": None, "title": ""}

    def contents(self, cid):
        """Состав курса; неудача запоминается (None), чтобы не ходить и не жаловаться дважды."""
        if cid not in self._contents:
            self._contents[cid] = None
            with self.soft(f"состав курса {cid}"):
                self._contents[cid] = self.moodle.contents(cid)
        return self._contents[cid] or []

    def within(self, ts):
        return self.now <= ts <= self.horizon

    # --- разделы

    def assignments(self):
        """Задания из mod_assign: сроки в окне и просроченные; новые и сдвинутые — против снимка."""
        new, moved = [], []
        course_list, _ = self.moodle.assignments()
        for c in course_list:
            if c["id"] not in self.courses:
                continue
            for a in c["assignments"]:
                item = {"kind": "assign", "source": "assign_api", "assign_id": a["id"],
                        "cmid": a["cmid"], "course": self.course(c["id"]), "name": a["name"],
                        "short": short_name(a["name"]), "due": moment(a.get("duedate"), self.now),
                        "submission": None, "intro": plain(a.get("intro")),
                        "lab": lab_number(a["name"]), "retake": lab_number(a["name"], "retake"),
                        "graded": False, "closed": False, "opens": None, "canedit": None,
                        "locked": False}
                self.assigns[str(a["id"])] = item
                self.raw[a["id"]] = a
                due = a.get("duedate") or 0
                prev = self.known.get(str(a["id"]))
                # пересдача — не новость: новостью была сама лаба
                if self.since and prev is None and not item["retake"]:
                    new.append(item)
                elif prev is not None and due and prev != due:
                    moved.append({**item, "was": moment(prev, self.now)})
                if not due:
                    continue
                if self.within(due):
                    self.soon.append(item)
                elif due < self.now <= due + MONTH:
                    self.overdue.append(item)

        live = by_due(self.soon + self.overdue)
        for item in live:
            if not item["retake"]:
                self.status(item)
        self.retakes([a for a in live if a["retake"]])
        # продление срока преподавателем могло вывести работу из просроченного — пересобрать;
        # продлённое за горизонт окна уходит из обоих списков, как любой далёкий срок
        self.soon = [a for a in live if self.within(a["due"]["ts"])]
        self.overdue = [a for a in live if a["due"]["ts"] < self.now]
        return new, moved

    def status(self, item):
        """Состояние ответа и оценка из mod_assign_get_submission_status — один раз на задание."""
        if item["assign_id"] in self.asked:
            return
        self.asked.add(item["assign_id"])
        with self.soft(f"статус задания {item['assign_id']}"):
            st = self.moodle.submission_status(item["assign_id"])
            s = submission_state(self.raw[item["assign_id"]], st, self.now)
            item.update(submission=s["status"], grade=s["grade"], feedback=s["feedback"],
                        graded=s["graded"], closed=s["closed"], canedit=s["canedit"],
                        locked=s["locked"],
                        opens=moment(s["opens"], self.now) if s["opens"] else None)
            if s["due"] and s["due"] != (item["due"] or {}).get("ts"):
                item["due"] = moment(s["due"], self.now)   # индивидуальное продление срока
            item["feedback_new"] = bool(item["feedback"]) and self.fb is not None \
                and self.fb.get(str(item["assign_id"])) != item["feedback"]

    def retakes(self, items):
        """Пересдача нужна, только если оригинал просрочен, не сдан и не оценен; иначе это
        не срок, а запасной выход, и в сроки она не идёт. Оригинал без пары — считаем нужной."""
        labs = {(a["course"]["id"], a["lab"]): a for a in self.assigns.values() if a["lab"]}
        for r in items:
            orig = labs.get((r["course"]["id"], r["retake"]))
            r["retake_of"] = orig["assign_id"] if orig else None
            if orig:
                self.status(orig)   # оригинал может быть старше окна — статус ещё не брали
            r["needed"] = orig is None or (orig["submission"] != "submitted"
                                           and not orig.get("graded")
                                           and (not orig["due"] or orig["due"]["overdue"]
                                                or orig.get("closed")))
            if r["needed"] and r["source"] == "assign_api":
                self.status(r)

    def activities(self):
        """Элементы курса со сроками — ловят задания, скрытые ограничением доступа.
        Статус ответа у них не запросить (requireloginerror), поэтому сразу "hidden"."""
        seen = {a["cmid"] for a in self.assigns.values()}
        for cid in self.courses:
            for sec in self.contents(cid):
                for m in sec.get("modules", []):
                    if m["id"] in seen or m["modname"] not in KINDS:
                        continue
                    for d in m.get("dates") or []:
                        ts = d.get("timestamp") or 0
                        if d.get("dataid") in DATE_IDS and self.within(ts):
                            self.soon.append({
                                "kind": "activity", "source": "course_contents",
                                "modname": m["modname"], "cmid": m["id"],
                                "course": self.course(cid), "name": m["name"],
                                "short": short_name(m["name"]), "due": moment(ts, self.now),
                                "submission": "hidden" if m["modname"] == "assign" else None,
                                "intro": "", "lab": lab_number(m["name"]),
                                "retake": lab_number(m["name"], "retake")})
        # скрытая пересдача сданной лабы — тоже не срок
        self.retakes([a for a in self.soon if a["source"] == "course_contents" and a["retake"]])

    def choices(self):
        """Выбор темы доклада: сам срок ничего не говорит, важно, выбрана ли тема."""
        picks = [a for a in self.soon if a.get("modname") == "choice"]
        if not picks:
            return
        by_cmid = {}
        with self.soft("темы докладов"):
            by_cmid = {c["coursemodule"]: c["id"]
                       for c in self.moodle.choices({a["course"]["id"] for a in picks})}
        for a in picks:
            cid = by_cmid.get(a["cmid"])
            if not cid:
                continue
            with self.soft(f"варианты выбора {cid}"):
                opts = self.moodle.choice_options(cid)
                mine = [o["text"] for o in opts if o.get("checked")]
                # disabled — вариант заполнен (maxanswers) или выбор закрыт: его не предлагать
                a["choice"] = {"chosen": mine[0] if mine else None,
                               "options": sum(1 for o in opts if not o.get("disabled"))}
                a["submission"] = "submitted" if mine else "new"

    def quizzes(self):
        """Тесты со сроком закрытия на месяц вперёд — отдельный раздел, не «Сроки»;
        timeclose = 0 — не срок, как duedate = 0 у задания. abandoned-попытки Moodle
        считает в лимит наравне с finished — здесь тоже."""
        out = []
        with self.soft("тесты"):
            for q in self.moodle.quizzes(list(self.courses)):
                close = q.get("timeclose") or 0
                if not close or not self.now <= close <= self.now + MONTH:
                    continue
                tries = None
                with self.soft(f"попытки теста {q['id']}"):
                    tries = self.moodle.quiz_attempts(q["id"])
                states = [t.get("state") for t in tries or []]
                # finished — тест сдан, как задание со статусом submitted; inprogress/overdue —
                # начат, но не отправлен: это важнее срока
                item = {"kind": "quiz", "source": "quiz", "quiz_id": q["id"],
                        "course": self.course(q["course"]), "name": q["name"],
                        "short": short_name(q["name"]), "due": moment(close, self.now),
                        "submission": "submitted" if "finished" in states else None,
                        "opens": (moment(q["timeopen"], self.now)
                                  if (q.get("timeopen") or 0) > self.now else None),
                        "open_attempt": any(st in ("inprogress", "overdue") for st in states),
                        "attempts_used": None if tries is None else len(tries),
                        "attempts_max": q.get("attempts") or None,
                        "timelimit_min": (q.get("timelimit") or 0) // 60 or None}
                out.append(item)
        return by_due(out)

    def updates(self):
        """Что изменилось в курсах: по core_course_get_updates_since и по составу против снимка.
        Ручка не видит файл, положенный в курс со старой датой (скопирован из прошлогоднего
        курса) или просто открытый студентам, — такой ловится тем, что в снимке его не было."""
        out = []
        if not self.since:
            return out
        for cid in self.courses:
            changed = []
            with self.soft(f"обновления курса {cid}"):
                changed = [u for u in self.moodle.updates_since(cid, self.since)
                           if u.get("updates")]
            modules = {m["id"]: (m, sec["name"]) for sec in self.contents(cid)
                       for m in sec.get("modules", [])}
            known = self.files.get(str(cid)) if self.files is not None else None
            known = set(known) if known is not None else None
            rows, course = {}, self.course(cid)
            for u in changed:
                kinds = {x["name"] for x in u["updates"]} & USEFUL
                if not kinds:
                    continue
                m, section = modules.get(u["id"], ({"name": f"(модуль {u['id']})"}, ""))
                rows[u["id"]] = news(course, m, section,
                                     "новые файлы" if kinds & FILES else "изменены настройки")
            # имена файлов — чтобы сводка говорила «появился 002-dns.pdf», а не «новые файлы»
            for mid, (m, section) in modules.items():
                new_files = [files.label(c) for c in m.get("contents") or []
                             if ((files.is_file(c) and c.get("filesize")) or files.is_link(c))
                             and files.fresh(m, c, self.since, known)]
                if new_files:
                    rows.setdefault(mid, news(course, m, section, "новые файлы"))
                    rows[mid]["files"] = new_files
            out.extend(rows.values())
        return out

    def announcements(self):
        """Новые записи в форумах объявлений (type news) — против снимка по id, а не по дате:
        правки и задним числом написанные посты тоже видны. Старый снимок — по времени."""
        out = []
        if not self.since:
            return out
        forums = []
        with self.soft("форумы"):
            forums = [f for f in self.moodle.forums(list(self.courses)) if f.get("type") == "news"]
        for f in forums:
            cid = f.get("course")
            if cid not in self.courses:
                continue
            with self.soft(f"объявления курса {cid}"):
                known = (self.announced or {}).get(str(cid))
                seen = self._forums.setdefault(cid, [])
                for d in self.moodle.discussions(f["id"]):
                    seen.append(d["id"])
                    ts = d.get("timemodified") or d.get("created") or 0
                    if (d["id"] not in known) if known is not None else ts > self.since:
                        out.append({"id": d["id"], "course": self.course(cid),
                                    "at": moment(ts, self.now),
                                    "subject": plain(d.get("subject") or d.get("name"), 120),
                                    "author": d.get("userfullname") or "",
                                    "text": plain(d.get("message"), 200)})
        return sorted(out, key=lambda a: -a["at"]["ts"])

    def notifications(self):
        """Непрочитанные уведомления, пришедшие после прошлого запуска, без автоматических."""
        out = []
        with self.soft("уведомления"):
            for m in self.moodle.notifications(limit=20):
                if m["timecreated"] > (self.since or 0) and m.get("eventtype") not in AUTO_EVENTS:
                    out.append({"id": m["id"], "at": moment(m["timecreated"], self.now),
                                "subject": plain(m.get("subject"), 120)})
        return sorted(out, key=lambda n: -n["at"]["ts"])

    def grades(self):
        """Баллы: итог по курсу и то, что появилось или изменилось с прошлого запуска."""
        out = []
        for cid in self.courses:
            with self.soft(f"оценки, курс {cid}"):
                try:
                    report = self.moodle.grades(cid)
                except StudyError as e:
                    if e.code == "nopermissiontoviewgrades":
                        continue   # в курсе выключен показ оценок: настройка, а не сбой
                    raise
                for t in report:
                    got = [i for i in t.get("gradeitems", [])
                           if i.get("graderaw") is not None and i.get("itemtype") != "course"]
                    if not got:
                        continue
                    total = next((i for i in t.get("gradeitems", [])
                                  if i.get("itemtype") == "course"), None)
                    # Итог курса Moodle может прятать; тогда считаем сумму работ сами.
                    raw = total.get("graderaw") if total else None
                    tot = ({"raw": raw, "max": total["grademax"], "computed": False}
                           if raw is not None else
                           {"raw": sum(i["graderaw"] for i in got),
                            "max": (total or {}).get("grademax") or sum(i["grademax"] for i in got),
                            "computed": True})
                    before = (self.graded or {}).get(str(cid), {})
                    items = [{"name": i["itemname"], "short": short_name(i["itemname"], tail=False),
                              "raw": i["graderaw"], "max": i["grademax"],
                              "new": self.graded is not None
                              and before.get(i["itemname"]) != i["graderaw"]}
                             for i in got]
                    out.append({"course": self.course(cid), "items": items, "total": tot})
        return out

    def outside(self):
        """Сроки по календарю у курсов, скрытых в ТУИС: вдруг скрыт по ошибке. Игнор — нет."""
        events = []
        with self.soft("календарь"):
            events = self.moodle.calendar(self.now - 7 * DAY, self.now + 120 * DAY)
        groups = {}
        for e in events:
            c = e.get("course") or {}
            if (c.get("id") and c["id"] not in self.courses and c["id"] not in self.ignore
                    and self.within(e.get("timesort", 0))):
                groups.setdefault((c["id"], c.get("fullname") or c.get("shortname")), []).append(e)
        return [{"course": {"id": cid, "title": name}, "count": len(evs),
                 "nearest": {"name": (min(evs, key=lambda x: x["timesort"])["name"] or "")[:60],
                             "at": moment(min(e["timesort"] for e in evs), self.now)}}
                for (cid, name), evs in groups.items()]

    # --- сборка

    def run(self):
        new, moved = self.assignments()
        self.activities()
        self.choices()
        deadlines = [a for a in by_due(self.soon) if a.get("needed", True)]
        overdue = [a for a in by_due(self.overdue) if a.get("needed", True)]
        return {
            "schema": 1, "now": moment(self.now, self.now), "days": self.days,
            "first_run": not self.since,
            "since": moment(self.since, self.now) if self.since else None,
            "courses": [c.as_dict() for c in self.courses.values()],
            # курс, которого не было в снимке: новая запись или снятый игнор
            "new_courses": [c.as_dict() for c in self.courses.values()
                            if self.seen_courses is not None
                            and str(c.id) not in self.seen_courses],
            "deadlines": deadlines,
            "overdue": [a for a in overdue if pending(a)],
            "submitted": [a for a in overdue if not pending(a)],
            # просроченное и несданное — впереди: пересдача всё ещё стоит баллов; но не то,
            # что ТУИС уже не примет (приём закрыт) — туда ведёт задание «Пересдача»
            "not_started": [a for a in overdue + deadlines
                            if a["source"] == "assign_api" and a["submission"] in PENDING
                            and not a.get("closed")],
            # отзывы преподавателя, которых в снимке ещё не было
            "feedback": [a for a in by_due(self.soon + self.overdue) if a.get("feedback_new")],
            "retakes": [{"assign_id": a.get("assign_id"), "cmid": a["cmid"], "short": a["short"],
                         "course": a["course"], "due": a["due"], "retake_of": a["retake_of"],
                         "needed": a["needed"]}
                        for a in by_due(self.soon + self.overdue) if a.get("retake")],
            "quizzes": self.quizzes(),
            "announcements": self.announcements(),
            "updates": self.updates(), "new_assignments": new, "moved": moved,
            "notifications": self.notifications(), "grades": self.grades(),
            "outside": self.outside(),
            "errors": self.errors,
        }

    def snapshot(self, data):
        """Что запомнить до следующего запуска."""
        return {
            "last_run": self.now,
            # исходный срок, не продлённый: иначе продление даст «срок сдвинут» каждый день
            "assignments": {i: self.raw[a["assign_id"]].get("duedate") or 0
                            for i, a in self.assigns.items()},
            "courses": {str(c.id): c.title for c in self.courses.values()},
            "grades": {str(g["course"]["id"]): {i["name"]: i["raw"] for i in g["items"]}
                       for g in data["grades"]},
            # состав курса не прочитался — оставить прошлый, иначе завтра всё окажется новым
            "files": {str(cid): files.keys(self._contents[cid])
                      if self._contents.get(cid) is not None
                      else (self.files or {}).get(str(cid), [])
                      for cid in self.courses},
            # объявления: прочитанные форумы дописывают свои id, непрочитанные оставляют прежние
            "announcements": {str(cid): sorted(set((self.announced or {}).get(str(cid), []))
                                               | set(self._forums[cid]))[-50:]
                              if cid in self._forums
                              else (self.announced or {}).get(str(cid), [])
                              for cid in self.courses},
            # отзывы: статус запрашивался не у всех — прошлые остаются
            "feedback": {**(self.fb or {}),
                         **{str(a["assign_id"]): a["feedback"] for a in self.assigns.values()
                            if a.get("feedback")}},
        }


def collect(cfg, moodle, days=None, save=True, since=None):
    """Всё, что знает ТУИС: дедлайны, тесты, обновления, уведомления, баллы.

    `since` — что считать прошлым запуском, строка `--since` (см. `snapshot.load_state`)."""
    errors = []
    c = Collector(cfg, moodle, days or cfg.days(), load_state(cfg, since, errors), errors)
    data = c.run()
    if save:
        save_state(cfg, c.snapshot(data))
    return data


# --- рендер

def attempts(q):
    """«попыток 1 из 3»; неизвестное число — «?», без предела — «∞»."""
    used = "?" if q["attempts_used"] is None else q["attempts_used"]
    return f"{used} из {q['attempts_max'] or '∞'}"


def status_of(a):
    """Колонка «Состояние» — только по ТУИС. Готовность лабы на диске (`labs[].ready`)
    остаётся в JSON для сессий над лабой: лаба делается в один заход, в сводке это шум."""
    pick = a.get("choice")
    if pick:
        return ("выбрана: " + pick["chosen"] if pick["chosen"]
                else f"не выбрана, {pick['options']} вариантов")
    if a["submission"] is None:
        # статус не получен (ошибка в errors) или элемент без ответа: опрос, взаимная проверка
        return KINDS.get(a.get("modname"), "?") if a["kind"] == "activity" else "?"
    if a.get("opens") and a["submission"] in PENDING:   # сданному «откроется» ни к чему
        return "откроется " + a["opens"]["text"]
    if a.get("closed"):
        return "заблокировано" if a.get("locked") else "приём закрыт"
    if a["submission"] == "reopened" and a.get("feedback"):
        return "на доработку: " + plain(a["feedback"], 60)
    return SUBMISSION.get(a["submission"], a["submission"])


def label(a):
    """Курс в таблице: имя папки из config.env, а без него — название из ТУИС."""
    return a["course"]["code"] or a["course"]["title"]


def bold(cells):
    return [f"**{c}**" if c not in ("", "—") else c for c in cells]


def when(m):
    return m["text"] if m else "—"


def repo_trouble(c):
    """Неполадки репозитория курса — одной строкой, только когда они есть."""
    repo = c["repo"]
    if not repo:
        return None
    bad = []
    if repo["dirty"]:
        bad.append(f"незакоммичено {len(repo['dirty'])}")
    for u in c["unreleased_tags"]:
        bad.append(f"нет релиза на {u['hosting']} ({', '.join(u['tags'])})")
    for name, r in c["releases"].items():
        latest = r.get("latest")
        if latest and not latest.get("assets"):
            bad.append(f"релиз {latest['tag']} на {name} без файлов")
    return f"{c['code']}: {', '.join(bad)}" if bad else None


def news_rows(t):
    """«Новое в курсах»: файлы и настройки, новые задания, сдвинутые сроки."""
    rows = []
    for u in t.get("updates", []):
        if u.get("pulled"):
            files_ = ", ".join(u["pulled"])
        elif not u["files"]:
            files_ = "—"
        elif u["course"]["code"]:
            files_ = ", ".join(u["files"]) + " — не скачаны"
        else:
            files_ = ", ".join(u["files"]) + " — у курса нет папки (CODE в config.env)"
        rows.append([label(u), u["section"] or "—", f"{u['item']}: {u['what']}", files_])
    for a in t.get("new_assignments", []):
        rows.append([label(a), "—", f"новое задание: {a['short']}, до {when(a['due'])}", "—"])
    for a in t.get("moved", []):
        rows.append([label(a), "—", (f"срок сдвинут: {a['short']}, было {when(a['was'])} "
                                     f"→ стало {when(a['due'])}"), "—"])
    return rows


def deadline_rows(t):
    """«Сроки»: просроченное жирным, затем окно; сданное не показывается."""
    rows = [bold([a["due"]["text"], "просрочено", a["short"], label(a), status_of(a)])
            for a in t.get("overdue", [])]
    for a in t.get("deadlines", []):
        if a["submission"] == "submitted":
            continue
        cells = [a["due"]["text"], a["due"]["left"], a["short"], label(a), status_of(a)]
        rows.append(bold(cells) if a["due"]["left_sec"] < URGENT else cells)
    return rows


def announcement(a):
    return f"**{a['subject']}** · {a['author']}: {a['text']}"


def grade_rows(t):
    rows = []
    for g in t.get("grades", []):
        fresh = [f"{i['short']} {i['raw']:.2f}/{i['max']:g}" for i in g["items"] if i["new"]]
        rows.append([label(g), f"{g['total']['raw']:.2f} / {g['total']['max']:g}",
                     " · ".join(fresh) or "—"])
    return rows


def quiz_rows(t):
    """«Тесты»: пройденные не показываются; срочные и начатые, но не отправленные — жирным."""
    rows = []
    for q in t.get("quizzes", []):
        if q["submission"] == "submitted":
            continue
        tries = ((f"откроется {q['opens']['text']}; " if q.get("opens") else "")
                 + ("начат, не отправлен; " if q["open_attempt"] else "") + attempts(q))
        cells = [q["due"]["text"], q["due"]["left"], q["short"], label(q), tries,
                 f"{q['timelimit_min']} мин" if q["timelimit_min"] else "—"]
        rows.append(bold(cells) if q["due"]["left_sec"] < URGENT or q["open_attempt"] else cells)
    return rows


def hot_line(a):
    """Строка «Горит»: несданная работа, когда и где методички — без домыслов агента."""
    code = a["course"]["code"]
    left = "просрочено" if a["due"]["overdue"] else a["due"]["left"]
    return (f"- **{a['short']}** · {label(a)} · до {a['due']['text']} · {left} · "
            f"методички: {code + '/stash/' if code else 'каталога курса нет'}")


def outside_rows(t):
    return [[o["nearest"]["at"]["text"], o["nearest"]["name"],
             f"{o['course']['title']} (id {o['course']['id']}, ещё {o['count']})"]
            for o in t.get("outside", [])]


def render(d):
    """Готовая сводка в markdown: то, что рутина печатает как есть."""
    t = d.get("tuis") or {}
    now = d["now"]["ts"]
    out = [f"# Учёба · {weekday(now)} {d['now']['text']}"]
    if t.get("first_run"):
        out.append("\nПервый запуск: обновления в курсах начнут отслеживаться со следующего раза. "
                   "Материалы курсов пока не скачаны: `study files --pull` — "
                   "в пустую stash/ забирает всё.")
    for c in t.get("new_courses", []):
        out.append(f"\nНовый курс в ТУИС: {c['title']} (id {c['id']}) — "
                   + (f"папка {c['code']}." if c["code"] else
                      f"строка `CODE {c['id']} <папка>` или `COURSE_IGNORE` в config.env."))

    news = news_rows(t)
    rows = deadline_rows(t)
    if rows:
        out += ["\n## Сроки\n",
                md_table(rows, ["Когда", "Осталось", "Работа", "Курс", "Состояние"])]
    elif d.get("tuis") is None:
        out.append("\nТУИС не опрашивался (`--local`): только состояние репозиториев.")
    else:
        tail = "" if news or t.get("first_run") or t.get("new_courses") else " Обновлений нет."
        out.append(f"\nСроков в ближайшие {d['days']} дн нет.{tail}")

    trouble = [s for s in map(repo_trouble, d["courses"]) if s]
    if trouble:
        out.append("\n" + "; ".join(trouble) + ".")

    # курс без папки: сроки видны, а файлы качать некуда. Строка про новый курс бывает один
    # раз, поэтому напоминание держится в каждой сводке, пока курс не заведён или не в игноре
    named = {c["id"] for c in t.get("new_courses", [])}
    unset = [c for c in t.get("courses", []) if not c["code"] and c["id"] not in named]
    if unset:
        out.append("\nБез папки (файлы не скачиваются): "
                   + ", ".join(f"{c['title']} (id {c['id']})" for c in unset)
                   + " — строка `CODE <id> <папка>` или `COURSE_IGNORE` в config.env.")

    sections = [
        ("Тесты", quiz_rows(t), ["Когда", "Осталось", "Тест", "Курс", "Попытки", "Время"]),
        ("Баллы", grade_rows(t), ["Курс", "Итого", "Новое"]),
        ("Отзывы", [[label(a), a["short"], a["feedback"]] for a in t.get("feedback", [])],
         ["Курс", "Работа", "Отзыв преподавателя"]),
        ("Уведомления", [[n["at"]["text"], n["subject"]] for n in t.get("notifications", [])],
         ["Когда", "Тема"]),
        ("Объявления", [[a["at"]["text"], label(a), announcement(a)]
                        for a in t.get("announcements", [])], ["Когда", "Курс", "Тема"]),
        ("Новое в курсах", news, ["Курс", "Раздел", "Что", "Файлы"]),
        ("Сроки в скрытых курсах", outside_rows(t), ["Когда", "Работа", "Курс"]),
    ]
    for title, rows, headers in sections:
        if rows:
            out += [f"\n## {title}\n", md_table(rows, headers)]
    hot = [a for a in t.get("not_started", []) if a["due"]["left_sec"] < HOT]
    if hot:
        out += ["\n## Горит\n"] + [hot_line(a) for a in hot]
    if d.get("errors"):
        # сбой раздела — не молча: в тексте иначе не видно, чего в сводке не хватает
        out.append("\nНе удалось: " + "; ".join(
            f"{e['source']} · {e['where']} · {e['message'][:80]}" for e in d["errors"]) + ".")
    hints = update.note(d.get("update"))
    if hints:
        out.append("\n" + "\n".join(hints))
    return "\n".join(out)


def render_digest(d):
    """`study digest`: тот же вид, но без состояния локальных репозиториев."""
    return render({"now": d["now"], "days": d["days"], "tuis": d, "courses": [],
                   "errors": d["errors"]})


# --- состояние локальных репозиториев

def pull_updates(cfg, moodle, tuis, errors):
    """Забрать файлы, о которых сообщила сводка; в каждой строке `updates` пометить скачанное."""
    # что новое, уже решила сводка (снимок к этому моменту сдвинут на «сейчас») — берём по именам
    for c in tuis["courses"]:
        todo = [u for u in tuis["updates"] if u["files"] and u["course"]["id"] == c["id"]]
        if not todo or not c["code"]:
            continue
        course = Course(c["id"], c["code"], c["title"])
        wanted = {n for u in todo for n in u["files"]}
        with soft(errors, f"файлы, курс {c['code']}"):
            d = files.listing(cfg, moodle, course, everything=True)
            d["files"] = [f for f in d["files"] if f["name"] in wanted]
            got = files.pull(moodle, d)
            names = [g["name"] for g in got["pulled"]]
            for u in todo:
                u["pulled"] = [n for n in u["files"] if n in names]
            errors.extend(got["errors"])


def course_state(cfg, course, by_lab, errors):
    """Курс на диске: профиль сдачи, а у release — git, релизы на хостингах, лабы с их
    готовностью и парой в ТУИС. У file-курса репозиторий (если есть) не смотрится."""
    item = {**course.as_dict(), "dir": str(course.dir), "flow": local.flow_of(cfg, course.code),
            "repo": None, "releases": {}, "unreleased_tags": [], "labs": []}
    repo = local.course_repo(course.code) if item["flow"] == "release" else None
    if not repo:
        return item
    item["repo"] = local.repo_state(repo)
    item["repo"]["remotes"] = {}
    for cls in hosting.HOSTS.values():
        slug = local.repo_from_remote(repo, cls.remote, cls.host)
        item["repo"]["remotes"][cls.source] = slug or None
        item["releases"][cls.source] = {"ok": False, "latest": None}
        with soft(errors, f"{cls.source}, курс {course.code}"):
            rels = cls(cfg, path=repo).releases()
            tags = [r["tag"] for r in rels]
            item["releases"][cls.source] = {"ok": True, "latest": rels[0] if rels else None,
                                            "tags": tags}
            missing = [t for t in item["repo"]["tags"] if t not in tags]
            if missing:
                item["unreleased_tags"].append({"hosting": cls.source, "tags": missing})
    for lab in local.labs(repo, course.code):
        found = by_lab.get((course.code, lab["num"]))
        lab["tuis"] = ({"assign_id": found["assign_id"], "name": found["name"],
                        "due": found["due"], "submission": found["submission"],
                        "matched_by": "number"} if found else None)
        lab["ready"] = {
            "report": lab["report"]["built"],
            "presentation": lab["presentation"]["built"],
            "videos": lab["videos"]["filled"] == lab["videos"]["total"],
            "submitted": bool(found and found["submission"] == "submitted"),
        }
        item["labs"].append(lab)
    return item


def state(cfg, moodle, days=None, with_tuis=True, save=True, pull=False, since=None):
    """Сводка ТУИС плюс состояние локальных репозиториев — всё одним объектом."""
    errors = []
    tuis = None
    if with_tuis:
        tuis = collect(cfg, moodle, days=days, save=save, since=since)
        if pull:
            pull_updates(cfg, moodle, tuis, errors)

    # Пара «лаба на диске ↔ задание в ТУИС» — по номеру в названии задания.
    t = tuis or {}
    by_lab = {(a["course"]["code"], a["lab"]): a
              for a in t.get("deadlines", []) + t.get("overdue", []) + t.get("submitted", [])
              if a.get("lab") and a["course"].get("code")}
    titles = {c["id"]: c["title"] for c in t.get("courses", [])}
    courses = [course_state(cfg, Course(cid, code, titles.get(cid, "")), by_lab, errors)
               for cid, code in cfg.codes().items()]

    # Есть ли обновление самого инструмента и актуальны ли блоки агента — только подсказка
    upd = None
    with soft(errors, "обновление study"):
        upd = update.check()

    return {"schema": 1, "now": moment(int(time.time())), "days": days or cfg.days(),
            "tuis": tuis, "courses": courses, "update": upd,
            "errors": errors + t.get("errors", [])}
