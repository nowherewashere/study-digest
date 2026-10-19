import contextlib
import os
import pathlib
import re
from typing import ClassVar

HERE = pathlib.Path(__file__).resolve().parents[2]
ROOT = HERE.parent

HINTS = {
    "invalidtoken": "Токен просрочен или отозван. Профиль Moodle → «Ключи безопасности» → "
                    "служба Moodle mobile web service → «Очистка», значение показывается один раз.",
    "nopermissiontoviewgrades": "В курсе выключен показ оценок студентам (или запись истекла); "
                                "сводка такой курс в «Баллах» пропускает.",
    "invalidrecord": "Функция не входит в службу этого токена: у служб РУДН свои ключи.",
    "notoken": "Статические токены — строками в .digest/config.env (их спрашивает `study setup`), "
               "Rutube — `rutube jwt` или `rutube login`. См. .digest/docs/configuration.md.",
    "certificate": "Python не нашёл корневые сертификаты. macOS со сборкой python.org: "
                   "запусти «Install Certificates.command» из папки Python в /Applications; "
                   "иначе проверь прокси или антивирус, подменяющий TLS.",
}


def write_atomic(path, text, mode=None, dirmode=None):
    path = pathlib.Path(path)
    if dirmode:
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            path.parent.chmod(dirmode)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode or 0o666)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    tmp.replace(path)


class ToolError(Exception):

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
    except ToolError as e:
        errors.append({**e.as_dict(), "where": where})


class Env:
    DEFAULTS: ClassVar[dict] = {
        "RUTUBE_TOKEN_FILE": ".secrets/rutube-token",
        "RUTUBE_REFRESH_FILE": ".secrets/rutube-refresh",
        "RUTUBE_ACCESS_FILE": ".secrets/rutube-access",
        "GV_REPO": "",
        "SC_REPO": "",
    }

    def __init__(self, path=None):
        self.path = pathlib.Path(path) if path else HERE / "config.env"
        self._values = {}
        self._tokens = {}
        self._read()

    def lines(self):
        if not self.path.exists():
            return []
        return [ln.strip() for ln in self.path.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]

    def _read(self):
        for line in self.lines():
            if "=" in line and " " not in line.partition("=")[0].strip():
                key, _, value = line.partition("=")
                self._values[key.strip()] = value.strip()

    def get(self, key):
        return os.environ.get(key) or self._values.get(key) or self.DEFAULTS.get(key, "")

    def path_of(self, key):
        p = pathlib.Path(self.get(key)).expanduser()
        return p if p.is_absolute() else HERE / p

    def token(self, name):
        if name not in self._tokens:
            val = self.get(name)
            if not val:
                f = self.path_of(name + "_FILE") if self.get(name + "_FILE") else None
                if not f or not f.exists():
                    raise ToolError("config", f"нет {name} в {self.path.name}", code="notoken")
                val = f.read_text(encoding="utf-8").strip()
            self._tokens[name] = val
        return self._tokens[name]

    def put(self, key, value):
        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
        mine = re.compile(rf"\s*{re.escape(key)}\s*=")
        at = next((i for i, ln in enumerate(lines) if mine.match(ln)), len(lines))
        lines = [ln for i, ln in enumerate(lines) if i == at or not mine.match(ln)]
        self._write([*lines[:at], f"{key}={value}", *lines[at + 1:]])
        self._values[key] = value
        self._tokens.pop(key, None)

    def _write(self, lines):
        write_atomic(self.path, "\n".join(lines) + "\n", 0o600)
