import contextlib
import os
import pathlib
import re
from dataclasses import dataclass
from typing import Optional

HERE = pathlib.Path(__file__).resolve().parents[2]
ROOT = HERE.parent

FLOWS = ("release", "file")

DEFAULTS = {
    "TUIS_URL": "https://esystem.rudn.ru",
    "RUTUBE_TOKEN_FILE": ".secrets/rutube-token",
    "RUTUBE_REFRESH_FILE": ".secrets/rutube-refresh",
    "RUTUBE_ACCESS_FILE": ".secrets/rutube-access",
    "DIGEST_DAYS": "21",
    "DIGEST_ACTIVE_DAYS": "60",
    "DIGEST_STATE": ".state.json",
    "GV_REPO": "",
    "SC_REPO": "",
}

HINTS = {
    "invalidtoken": "Токен просрочен или отозван. Профиль Moodle → «Ключи безопасности» → "
                    "служба Moodle mobile web service → «Очистка», значение показывается один раз.",
    "nopermissiontoviewgrades": "В курсе выключен показ оценок студентам (или запись истекла); "
                                "сводка такой курс в «Баллах» пропускает.",
    "invalidrecord": "Функция не входит в службу этого токена: у служб РУДН свои ключи.",
    "notoken": "Статические токены — строками в config.env (их спрашивает `study setup`), "
               "Rutube — `study rt jwt` или `study rt login`. См. README.md, «Установка».",
    "certificate": "Python не нашёл корневые сертификаты. macOS со сборкой python.org: "
                   "запусти «Install Certificates.command» из папки Python в /Applications; "
                   "иначе проверь прокси или антивирус, подменяющий TLS.",
}


def write_atomic(path, text, mode=None):
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode or 0o666)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    tmp.replace(path)


class StudyError(Exception):

    def __init__(self, source, message, code=None, where=None):
        self.source = source
        self.message = str(message)
        self.code = code
        self.where = where
        super().__init__(self.text())

    def text(self):
        parts = [self.source]
        if self.where:
            parts.append(self.where)
        parts.append(self.message)
        line = ": ".join(parts)
        if self.code:
            line += f" ({self.code})"
        return line

    def hint(self):
        return HINTS.get(self.code or "")

    def as_dict(self):
        return {"source": self.source, "where": self.where,
                "code": self.code, "message": self.message}


@contextlib.contextmanager
def soft(errors, where):
    try:
        yield
    except StudyError as e:
        errors.append({**e.as_dict(), "where": where})


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


class Config:
    def __init__(self, path=None):
        self.path = pathlib.Path(path) if path else HERE / "config.env"
        self._values = {}
        self._codes = {}
        self._flows = {}
        self._ignore = set()
        self._tokens = {}
        self._read()

    def _read(self):
        if not self.path.exists():
            return
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 2)
            if parts[0] == "CODE" and len(parts) == 3 and parts[1].isdigit():
                self._codes[int(parts[1])] = parts[2].strip()
            elif parts[0] == "FLOW" and len(parts) == 3 and parts[1].isdigit():
                if parts[2].strip() not in FLOWS:
                    raise StudyError("config", f"FLOW {parts[1]}: ожидается {' или '.join(FLOWS)}, "
                                               f"а не «{parts[2].strip()}»")
                self._flows[int(parts[1])] = parts[2].strip()
            elif "=" in line:
                key, _, value = line.partition("=")
                self._values[key.strip()] = value.strip()
        self._ignore = {int(x) for x in re.findall(r"\d+", self._values.pop("COURSE_IGNORE", ""))}

    def get(self, key):
        return os.environ.get(key) or self._values.get(key) or DEFAULTS.get(key, "")

    def path_of(self, key):
        p = pathlib.Path(self.get(key)).expanduser()
        return p if p.is_absolute() else HERE / p

    def token(self, name):
        if name not in self._tokens:
            val = self.get(name)
            if not val:
                f = self.path_of(name + "_FILE") if self.get(name + "_FILE") else None
                if not f or not f.exists():
                    raise StudyError("config", f"нет {name} в {self.path.name}", code="notoken")
                val = f.read_text(encoding="utf-8").strip()
            self._tokens[name] = val
        return self._tokens[name]

    def put(self, key, value):
        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
        self._write([ln for ln in lines if not re.match(rf"\s*{re.escape(key)}\s*=", ln)]
                    + [f"{key}={value}"])
        self._values[key] = value
        self._tokens.pop(key, None)


    def ignore(self):
        return set(self._ignore)

    def codes(self):
        return dict(self._codes)

    def flows(self):
        return dict(self._flows)

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

    def _write(self, lines):
        write_atomic(self.path, "\n".join(lines) + "\n", 0o600)


    def days(self):
        return int(self.get("DIGEST_DAYS"))

    def active_days(self):
        return int(self.get("DIGEST_ACTIVE_DAYS"))

    def state_file(self):
        return self.path_of("DIGEST_STATE")
