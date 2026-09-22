"""Реестр заданий курса: единственное место, которое знает, что задание живёт в двух ручках.

`mod_assign_get_assignments` знает всё про приём ответа, но молчит о заданиях с ограничением
доступа — вместо них приходит warning «No access rights in module context».
`core_course_get_contents` отдаёт все модули курса, включая недоступные, но из задания знает
только имя, срок, описание и причину недоступности. Слияние нужно и сводке, и карточке, и
отправке, поэтому живёт здесь, а не у каждого потребителя по-своему.
"""
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Optional

from . import moodle as moodle_api
from .config import Course, StudyError
from .fmt import lab_number, moment, parse_name, plain, short_name

# Сроки в составе курса: машинные идентификаторы, а не подписи — подпись зависит от языка.
DATE_IDS = {"duedate", "timeclose"}
OPEN_IDS = {"allowsubmissionsfromdate", "timeopen"}
KINDS = {"assign": "задание", "choice": "выбор темы",
         "workshop": "взаимная проверка", "feedback": "опрос"}
# «hidden» — не статус Moodle, а наш: у задания из состава курса статуса ответа нет вовсе
SUBMISSION = {**moodle_api.SUBMISSION, "hidden": "доступ закрыт"}


@dataclass
class Work:
    """Задание курса, откуда бы оно ни пришло. Без `assign_id` про него нельзя спросить
    состояние ответа и нельзя ничего отправить: в mod_assign такого задания нет."""

    course: Course
    cmid: int
    name: str
    source: str                          # assign_api | course_contents
    assign_id: Optional[int] = None
    modname: str = "assign"
    due: Optional[int] = None
    opens: Optional[int] = None
    section: str = ""
    intro: str = ""
    visible: bool = True
    reason: str = ""                     # availabilityinfo: почему задание недоступно
    raw: dict = field(default_factory=dict)

    @property
    def available(self):
        return self.assign_id is not None

    @property
    def lab(self):
        return lab_number(self.name)

    @property
    def num(self):
        """Номер работы любого вида: у курса бывают не лабы, а задачи ИДЗ или доклады."""
        p = parse_name(self.name)
        return p["num"].zfill(2) if p else None

    @property
    def retake(self):
        return lab_number(self.name, "retake")

    @property
    def short(self):
        return short_name(self.name)

    def as_item(self, now):
        """Запись для сводки. Форма зависит от источника — ровно так её собирал Collector:
        у задания из mod_assign есть поля состояния ответа, у взятого из состава курса их нет,
        потому что статус по нему не спросить (requireloginerror)."""
        base = {"cmid": self.cmid, "course": self.course.as_dict(), "name": self.name,
                "short": self.short, "due": moment(self.due, now), "lab": self.lab,
                "retake": self.retake}
        if self.source == "assign_api":
            return dict(base, kind="assign", source=self.source, assign_id=self.assign_id,
                        submission=None, intro=plain(self.intro), graded=False, closed=False,
                        opens=None, canedit=None, locked=False)
        # описание модуля в сводку не идёт: его показывает карточка `study task`
        return dict(base, kind="activity", source=self.source, modname=self.modname, intro="",
                    submission="hidden" if self.modname == "assign" else None)


def from_api(course, a):
    """Задание из `mod_assign_get_assignments`."""
    return Work(course=course, cmid=a["cmid"], name=a["name"], source="assign_api",
                assign_id=a["id"], due=a.get("duedate") or None,
                opens=a.get("allowsubmissionsfromdate") or None,
                intro=a.get("intro") or "", raw=a)


def date_of(module, ids):
    for d in module.get("dates") or []:
        if d.get("dataid") in ids and d.get("timestamp"):
            return int(d["timestamp"])
    return None


def from_module(course, m, section=""):
    """Элемент курса из `core_course_get_contents` — задание, тест, выбор темы."""
    return Work(course=course, cmid=m["id"], name=m.get("name") or "", source="course_contents",
                modname=m.get("modname") or "", due=date_of(m, DATE_IDS),
                opens=date_of(m, OPEN_IDS), section=section,
                intro=plain(m.get("description"), 20000),
                visible=bool(m.get("uservisible", True)),
                reason=plain(m.get("availabilityinfo"), 500), raw=m)


class Registry:
    """Задания курсов из обеих ручек. `mod_assign` зовётся один раз на все курсы сразу,
    состав курса — по курсу; неудача состава мягкая, если дан `soft` (сводке нельзя падать
    из-за одного курса), иначе ошибка идёт наверх."""

    def __init__(self, moodle, courseids=None, soft=None):
        self.moodle = moodle
        self.courseids = list(courseids) if courseids else None
        self.warnings = []
        self._soft = soft
        self._api = None
        self._titles = {}
        self._works = {}
        self._sections = {}

    def guard(self, where):
        return self._soft(where) if self._soft else nullcontext()

    def _load(self):
        if self._api is None:
            courses, self.warnings = self.moodle.assignments(self.courseids)
            self._api = {c["id"]: c.get("assignments") or [] for c in courses}
            self._titles = {c["id"]: c.get("fullname") or "" for c in courses}

    def api(self, course_id):
        self._load()
        return self._api.get(course_id, [])

    def title(self, course_id):
        """Название курса так, как его зовёт ТУИС; у курса без заданий — пусто."""
        self._load()
        return self._titles.get(course_id)

    def courses(self, codes=None):
        """Курсы, о которых знает mod_assign, с именами локальных папок (строки CODE)."""
        self._load()
        codes = codes or {}
        return [Course(cid, codes.get(cid), title) for cid, title in self._titles.items()]

    def sections(self, course):
        """Состав курса как [(модуль, имя раздела)]; не прочитался — пусто, ошибка уже учтена."""
        if course.id not in self._sections:
            self._sections[course.id] = []
            with self.guard(f"состав курса {course.id}"):
                self._sections[course.id] = [(m, s.get("name") or "")
                                             for s in self.moodle.contents(course.id)
                                             for m in s.get("modules") or []]
        return self._sections[course.id]

    def works(self, course, contents=True):
        """Задания курса: всё из mod_assign плюс то, чего он не отдал (ограничение доступа).
        `contents=False` — только mod_assign: состав курса стоит запроса на каждый курс,
        и списку по всем курсам сразу он не по карману."""
        api = [from_api(course, a) for a in self.api(course.id)]
        if not contents:
            return api
        if course.id not in self._works:
            seen = {w.cmid for w in api}
            self._works[course.id] = api + [
                from_module(course, m, section) for m, section in self.sections(course)
                if m.get("modname") == "assign" and m["id"] not in seen]
        return self._works[course.id]

    def modules(self, course, kinds):
        """Прочие элементы курса со сроком (выбор темы, опрос) — их показывает сводка."""
        return [from_module(course, m, section) for m, section in self.sections(course)
                if m.get("modname") in kinds]

    def find(self, course, what):
        """Задание по номеру лабы (NN, labNN), id из `study assigns` или cmid из сводки."""
        works = self.works(course)
        label = course.code or str(course.id)
        if not works:
            raise StudyError("moodle", f"в курсе {label} заданий нет: "
                                       "ТУИС по этому курсу ничего не принимает")
        m = re.fullmatch(r"(?:lab)?(\d{1,2})", what.strip().lower())
        if m:
            num = m.group(1).zfill(2)
            for w in works:                     # лаба важнее: у неё есть каталог labNN
                if w.lab == num:
                    return w
            for w in works:
                if w.num == num:
                    return w
        if what.strip().isdigit():
            n = int(what)
            for w in works:
                if w.assign_id == n:
                    return w
            for w in works:                     # скрытое задание знает только свой cmid
                if w.cmid == n:
                    return w
        raise StudyError("moodle", f"в курсе {label} нет задания «{what}»: "
                                   f"study assigns --course {label}")
