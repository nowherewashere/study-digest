import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Optional

from . import moodle as moodle_api
from .config import Course, StudyError
from .fmt import lab_number, moment, parse_name, plain, short_name

DATE_IDS = {"duedate", "timeclose"}
OPEN_IDS = {"allowsubmissionsfromdate", "timeopen"}
KINDS = {"assign": "задание", "choice": "выбор темы",
         "workshop": "взаимная проверка", "feedback": "опрос"}
SUBMISSION = {**moodle_api.SUBMISSION, "hidden": "доступ закрыт"}


@dataclass
class Work:

    course: Course
    cmid: int
    name: str
    source: str
    assign_id: Optional[int] = None
    modname: str = "assign"
    due: Optional[int] = None
    opens: Optional[int] = None
    section: str = ""
    intro: str = ""
    visible: bool = True
    reason: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def available(self):
        return self.assign_id is not None

    @property
    def lab(self):
        return lab_number(self.name)

    @property
    def num(self):
        p = parse_name(self.name)
        return p["num"].zfill(2) if p else None

    @property
    def retake(self):
        return lab_number(self.name, "retake")

    @property
    def short(self):
        return short_name(self.name)

    def as_item(self, now):
        base = {"cmid": self.cmid, "course": self.course.as_dict(), "name": self.name,
                "short": self.short, "due": moment(self.due, now), "lab": self.lab,
                "retake": self.retake}
        if self.source == "assign_api":
            return dict(base, kind="assign", source=self.source, assign_id=self.assign_id,
                        submission=None, intro=plain(self.intro), graded=False, closed=False,
                        opens=None, canedit=None, locked=False)
        return dict(base, kind="activity", source=self.source, modname=self.modname, intro="",
                    submission="hidden" if self.modname == "assign" else None)


def from_api(course, a):
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
    return Work(course=course, cmid=m["id"], name=m.get("name") or "", source="course_contents",
                modname=m.get("modname") or "", due=date_of(m, DATE_IDS),
                opens=date_of(m, OPEN_IDS), section=section,
                intro=plain(m.get("description"), 20000),
                visible=bool(m.get("uservisible", True)),
                reason=plain(m.get("availabilityinfo"), 500), raw=m)


class Registry:

    def __init__(self, moodle, courseids=None, soft=None, contents=None):
        self.moodle = moodle
        self.courseids = list(courseids) if courseids else None
        self._contents = contents or moodle.contents
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
        self._load()
        return self._titles.get(course_id)

    def courses(self, codes=None):
        self._load()
        codes = codes or {}
        return [Course(cid, codes.get(cid), title) for cid, title in self._titles.items()]

    def sections(self, course):
        if course.id not in self._sections:
            self._sections[course.id] = []
            with self.guard(f"состав курса {course.id}"):
                self._sections[course.id] = [(m, s.get("name") or "")
                                             for s in self._contents(course.id)
                                             for m in s.get("modules") or []]
        return self._sections[course.id]

    def works(self, course, contents=True):
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
        return [from_module(course, m, section) for m, section in self.sections(course)
                if m.get("modname") in kinds]

    def find(self, course, what):
        works = self.works(course)
        label = course.code or str(course.id)
        if not works:
            raise StudyError("moodle", f"в курсе {label} заданий нет: "
                                       "ТУИС по этому курсу ничего не принимает")
        m = re.fullmatch(r"(?:lab)?(\d{1,2})", what.strip().lower())
        if m:
            num = m.group(1).zfill(2)
            for w in works:
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
            for w in works:
                if w.cmid == n:
                    return w
        raise StudyError("moodle", f"в курсе {label} нет задания «{what}»: "
                                   f"study assigns --course {label}")
