"""Настройки: единственный парсер config.env, курсы, пути, токены.

Приоритет значений: переменная окружения → строка в config.env → значение по умолчанию.
Если ключ в config.env встречается дважды, побеждает последнее вхождение.
"""
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent.parent  # каталог digest/
ROOT = HERE.parent                                     # ~/work/study

DEFAULTS = {
    "TUIS_URL": "https://esystem.rudn.ru",
    "TUIS_TOKEN_FILE": "~/.config/tuis/token",
    "GITVERSE_TOKEN_FILE": "~/.config/gitverse/token",
    "SOURCECRAFT_TOKEN_FILE": "~/.config/sourcecraft/token",
    "RUTUBE_TOKEN_FILE": "~/.config/rutube/token",
    "DIGEST_DAYS": "21",
    "DIGEST_STATE": "~/.config/tuis/state.json",
    "GV_REPO": "",
    "SC_REPO": "",
}

# Подсказки к известным кодам ошибок — что делать пользователю.
HINTS = {
    "invalidtoken": "Токен просрочен или отозван. Профиль Moodle → «Ключи безопасности» → "
                    "служба Moodle mobile web service → «Очистка», значение показывается один раз.",
    "nopermissiontoviewgrades": "Запись на курс истекла, оценки недоступны.",
    "invalidrecord": "Функция не входит в службу этого токена: у служб РУДН свои ключи.",
    "notoken": "Нет файла с токеном. См. README.md, раздел «Развернуть с нуля».",
}


class StudyError(Exception):
    """Единственный тип ошибки во всём инструменте."""

    def __init__(self, source, message, code=None, where=None):
        self.source = source          # config | moodle | gitverse | sourcecraft | git
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


class Course:
    """Строка COURSE из config.env."""

    def __init__(self, cid, code, title):
        self.id = int(cid)
        self.code = None if code == "-" else code
        self.title = title

    @property
    def dir(self):
        return ROOT / self.code if self.code else None

    def as_dict(self):
        return {"id": self.id, "code": self.code, "title": self.title}


class Config:
    def __init__(self, path=None):
        self.path = pathlib.Path(path) if path else HERE / "config.env"
        self._values = {}
        self._courses = []
        self._tokens = {}
        self._read()

    def _read(self):
        if not self.path.exists():
            return
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("COURSE"):
                parts = line.split(None, 3)
                if len(parts) == 4 and parts[1].isdigit():
                    self._courses.append(Course(parts[1], parts[2], parts[3].strip()))
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                self._values[key.strip()] = value.strip()

    def get(self, key, default=None):
        if os.environ.get(key):
            return os.environ[key]
        if self._values.get(key):
            return self._values[key]
        value = DEFAULTS.get(key, "")
        return value if value else ("" if default is None else default)

    def path_of(self, key):
        """Путь из настройки: тильда разворачивается, относительный — от корня учебной директории."""
        p = pathlib.Path(self.get(key)).expanduser()
        return p if p.is_absolute() else ROOT / p

    def token(self, key):
        """Токен читается лениво, чтобы --help работал без токенов."""
        if key not in self._tokens:
            f = self.path_of(key)
            if not f.exists():
                raise StudyError("config", f"нет файла {f}", code="notoken")
            self._tokens[key] = f.read_text().strip()
        return self._tokens[key]

    def courses(self):
        return list(self._courses)

    def days(self):
        return int(self.get("DIGEST_DAYS"))

    def state_file(self):
        return self.path_of("DIGEST_STATE")
