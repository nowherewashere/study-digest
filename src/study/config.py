import re
from dataclasses import dataclass
from typing import ClassVar, Optional

from kit.config import ROOT, Env, ToolError

FLOWS = ("screencast", "direct")
FLOW_ALIASES = {"release": "screencast", "file": "direct"}
SKILLS = {"screencast": "lab-release-with-screencasts", "direct": "study-lab"}


@dataclass
class Course:
    id: int
    code: Optional[str] = None
    title: str = ""

    @property
    def dir(self):
        return ROOT / self.code if self.code else None

    def as_dict(self):
        return {"id": self.id, "code": self.code, "title": self.title}


class Config(Env):
    DEFAULTS: ClassVar[dict] = {
        **Env.DEFAULTS,
        "TUIS_URL": "https://esystem.rudn.ru",
        "DIGEST_DAYS": "21",
        "DIGEST_ACTIVE_DAYS": "60",
        "DIGEST_STATE": ".state.json",
    }

    def __init__(self, path=None):
        self._codes = {}
        self._flows = {}
        self._ignore = set()
        super().__init__(path)

    def _read(self):
        super()._read()
        for line in self.lines():
            parts = line.split(None, 2)
            table = {"CODE": self._codes, "FLOW": self._flows}.get(parts[0])
            if table is None or len(parts) != 3 or not parts[1].isdigit():
                continue
            value = parts[2].strip()
            if table is self._flows:
                value = FLOW_ALIASES.get(value, value)
                if value not in FLOWS:
                    raise ToolError("config", f"FLOW {parts[1]}: ожидается "
                                              f"{' или '.join(FLOWS)}, а не «{value}»")
            table[int(parts[1])] = value
        self._ignore = {int(x) for x in re.findall(r"\d+", self._values.pop("COURSE_IGNORE", ""))}

    def ignore(self):
        return set(self._ignore)

    def codes(self):
        return dict(self._codes)

    def flows(self):
        return dict(self._flows)

    def flow(self, code):
        cid = next((i for i, c in self._codes.items() if c == code), None)
        if cid is None or cid not in self._flows:
            raise ToolError("config", f"у курса {code} не задана сдача: строка FLOW <id> "
                                      f"{'|'.join(FLOWS)} в config.env или `study courses --setup`")
        return self._flows[cid]

    def track(self, courses):
        return [Course(c["id"], self._codes.get(c["id"]), c.get("fullname") or "")
                for c in courses if c["id"] not in self._ignore]

    def write_courses(self, ignore_ids, codes, flows=None):
        flows = self._flows if flows is None else flows
        flows = {cid: f for cid, f in flows.items() if cid in codes}
        keep = [ln for ln in self.path.read_text(encoding="utf-8").splitlines()
                if not re.match(r"\s*(COURSE_IGNORE\s*=|CODE\s|COURSE\s|FLOW\s)", ln)]
        keep.append("COURSE_IGNORE=" + " ".join(str(i) for i in sorted(ignore_ids)))
        keep += [f"CODE {cid} {code}" for cid, code in sorted(codes.items())]
        keep += [f"FLOW {cid} {flow}" for cid, flow in sorted(flows.items())]
        self._write(keep)
        self._ignore, self._codes, self._flows = set(ignore_ids), dict(codes), dict(flows)

    def days(self):
        return int(self.get("DIGEST_DAYS"))

    def active_days(self):
        return int(self.get("DIGEST_ACTIVE_DAYS"))

    def state_file(self):
        return self.path_of("DIGEST_STATE")
