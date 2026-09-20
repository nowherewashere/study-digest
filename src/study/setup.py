"""Первоначальная настройка: токены, каталоги, проверка связи, ИИ-оператор, курсы.

Продолжение install.py (тот ставит код и зовёт `study setup`), но работает и сам по себе —
перенастроить токены, оператора или курсы. Каждый шаг — свой экран: [n/N] в заголовке,
строка прогресса, снизу — результат; всё, что шаги сообщили, собирается и показывается
ещё раз на итоговом экране. Шаги, уже сделанные install.py, и их результаты приходят
в переменной STUDY_SETUP (JSON: {"steps": [...], "log": [[ok|warn, шаг, текст], ...]}).
"""
import contextlib
import ctypes
import getpass
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import textwrap
import webbrowser

try:
    import winreg
except ImportError:   # не Windows
    winreg = None

from . import agent, courses, files, local
from .config import HERE, ROOT, StudyError
from .moodle import Moodle
from .snapshot import load_state

STEPS = ["Токены", "Каталоги", "Проверка", "Оператор", "Курсы"]
RULE = "-" * 72
POSIX = os.name == "posix"
TOKENS = [   # ключ в config.env, название, где взять, страница токена относительно TUIS_URL
    ("TUIS_TOKEN", "Moodle (нужен для сводки)",
     "профиль -> Ключи безопасности -> служба Moodle mobile web service", "/user/managetoken.php"),
    ("GITVERSE_TOKEN", "GitVerse (необязательно)",
     "иконка пользователя -> Настройки -> Управление токенами, доступ Репозитории", None),
    ("SOURCECRAFT_TOKEN", "SourceCraft (необязательно)",
     "Home -> Access -> Personal Access Tokens", None),
]
NEXT = """
  {B}Дальше{N}
  study state --pull       сводка: сроки, тесты, баллы, новое в курсах
  study files --pull       материалы всех курсов в stash/ (в пустую папку - всё, дальше - новое)
  study courses --setup    перенастроить курсы и папки
  study agent <код>        файл инструкций для ИИ-оператора (claude, codex, gemini, copilot)
  study update             обновить инструмент

  {B}Ежедневная сводка{N}
  Claude Code Desktop -> Code -> Routines -> New routine -> Local:
  рабочая папка {root},
  в Instructions - текст из {prompt}"""


# --- оформление: цвета только в терминале, без них — тот же текст

class Screen:
    def __init__(self, steps, log=()):
        self.steps, self.log, self.n = list(steps), [list(x) for x in log], 0
        self.tty = sys.stdout.isatty()
        self.B, self.D, self.G, self.Y, self.R, self.N = (
            ("\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")
            if self.tty else ("",) * 6)

    def step(self, n):
        """Новый экран: заголовок [n/N], строка прогресса, черта."""
        self.n = n
        crumbs = []
        for i, name in enumerate(self.steps, 1):
            if i < n:
                crumbs.append(f"{self.G}[x]{self.N} {self.D}{name}{self.N}")
            elif i == n:
                crumbs.append(f"{self.B}[>] {name}{self.N}")
            else:
                crumbs.append(f"{self.D}[ ] {name}{self.N}")
        clear = "\033[H\033[2J" if self.tty else ""
        title = f"{self.B}[{n}/{len(self.steps)}] {self.steps[n - 1]}{self.N}"
        sys.stdout.write(f"{clear}{self.B}study{self.N}  установка  {title}\n"
                         f"{'  '.join(crumbs)}\n{RULE}\n\n")
        sys.stdout.flush()

    def ok(self, text):
        print(f"  {self.G}+{self.N} {text}")
        self.log.append(["ok", self.steps[self.n - 1], text])

    def warn(self, text):
        print(f"  {self.Y}!{self.N} {text}")
        self.log.append(["warn", self.steps[self.n - 1], text])

    def note(self, text):
        print(f"  {self.D}{text}{self.N}")

    def ask(self, question):
        return input(f"  {self.B}>{self.N} {question} ")

    def secret(self):
        prompt = f"  {self.B}>{self.N} вставь токен (ввод скрыт, Enter - пропустить): "
        return getpass.getpass(prompt)

    def final(self, root, prompt):
        """Итоговый экран: всё, что сообщили шаги, и что делать дальше."""
        self.steps.append("Готово")
        self.step(len(self.steps))
        mark = {"ok": f"{self.G}+{self.N}", "warn": f"{self.Y}!{self.N}"}
        lines = [f"  {mark[kind]} {step}: {text}" for kind, step, text in self.log]
        return "\n".join(lines) + "\n" + NEXT.format(B=self.B, N=self.N, root=root, prompt=prompt)


def yes(answer, default):
    """[Y/n] и [y/N]: пустой ввод — значение по умолчанию."""
    return (answer.strip() or default)[:1].lower() == "y"


# --- платформа: браузер, команда в PATH

def wsl():
    return "microsoft" in platform.uname().release.lower()


def open_url(url):
    """Открыть ссылку в браузере, не роняя установку; False — не вышло, пусть откроют руками."""
    if wsl():
        opener = shutil.which("wslview") or shutil.which("explorer.exe")
        if not opener:
            return False
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY")
                                                 or os.environ.get("WAYLAND_DISPLAY")):
        return False   # без графики webbrowser поднимет lynx/w3m прямо в терминале
    return webbrowser.open(url)


def bin_dir():
    return pathlib.Path.home() / ".local" / "bin"


def link_command():
    """Команда study в ~/.local/bin: симлинк на POSIX; на Windows — study.cmd для cmd и
    PowerShell и sh-скрипт study для Git Bash, оба зовут этот же python с лаунчером."""
    launcher, b = HERE / "study", bin_dir()
    b.mkdir(parents=True, exist_ok=True)
    if POSIX:
        link = b / "study"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(launcher)
        return f"~/.local/bin/study -> {launcher}"
    py = pathlib.Path(sys.executable)
    # cmd читает .cmd в OEM-кодировке: пути под профилем пишем через %USERPROFILE%
    home = re.escape(str(pathlib.Path.home()))
    cmd = re.sub(home, "%USERPROFILE%", f'@"{py}" "{launcher}" %*\r\n', flags=re.IGNORECASE)
    try:
        raw = cmd.encode("oem")
    except (UnicodeEncodeError, LookupError):
        raw = cmd.encode("utf-8")
    (b / "study.cmd").write_bytes(raw)
    sh = f'#!/bin/sh\nexec "{py.as_posix()}" "{launcher.as_posix()}" "$@"\n'
    (b / "study").write_bytes(sh.encode("utf-8"))
    return f"{b / 'study.cmd'} -> {launcher}"


def user_path():
    """PATH пользователя из реестра Windows: (значение, тип) — тип нужен, чтобы записать так же."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        try:
            return winreg.QueryValueEx(k, "Path")
        except FileNotFoundError:
            return "", winreg.REG_EXPAND_SZ


def in_path(b):
    """Каталог уже в PATH: текущем или, на Windows, в PATH пользователя из реестра."""
    def norm(p):
        return os.path.normcase(os.path.normpath(os.path.expandvars(p.strip())))
    seen = [norm(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p.strip()]
    if winreg:
        with contextlib.suppress(OSError):   # реестр недоступен — значит, и в PATH нет
            seen += [norm(p) for p in user_path()[0].split(";") if p.strip()]
    return norm(str(b)) in seen


def add_user_path(b):
    """Дописать каталог в PATH пользователя (HKCU\\Environment) и оповестить систему.
    setx не годится: обрезает значение на 1024 символах и меняет его тип."""
    value, kind = user_path()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Path", 0, kind, (value.rstrip(";") + ";" if value else "") + str(b))
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, None)


def path_hint(s):
    """Команда лежит в ~/.local/bin — но есть ли он в PATH."""
    b = bin_dir()
    if in_path(b):
        return
    if sys.platform == "darwin":
        s.warn('добавь в ~/.zprofile строку export PATH="$HOME/.local/bin:$PATH" '
               "и перезайди в оболочку")
    elif POSIX:
        s.warn("добавь ~/.local/bin в PATH или перезайди в оболочку")
    elif sys.stdin.isatty() and yes(s.ask(f"добавить {b} в PATH пользователя? [Y/n]"), "y"):
        try:
            add_user_path(b)
            s.ok("добавлено в PATH пользователя: подействует в новом терминале")
        except OSError:
            s.warn(f"не удалось: добавь {b} в PATH пользователя сам "
                   "(Параметры -> Переменные среды)")
    else:
        s.warn(f"добавь {b} в PATH пользователя (Параметры -> Переменные среды)")


# --- шаги

def ask_token(s, cfg, key, name, where, url):
    short = name.split()[0]
    print(f"\n  {s.B}{name}{s.N}")
    s.note(f"где взять: {where}")
    if url:
        s.note(f"ссылка: {url}")
        if yes(s.ask("открыть в браузере? [Y/n]"), "y") and not open_url(url):
            s.warn("не открылось: перейди по ссылке вручную")
    if cfg.get(key) and not yes(s.ask("токен уже есть, заменить? [y/N]"), "n"):
        s.ok(f"{short}: оставлен прежний")
        return
    token = s.secret().strip()
    if not token:
        s.warn(f"{short}: пропущен, команды этого сервиса работать не будут")
        return
    cfg.put(key, token)
    s.ok(f"{short}: сохранён в config.env")
    if key == "TUIS_TOKEN" and not re.fullmatch(r"[0-9a-f]{32}", token):
        # у Moodle токен — 32 hex; в скрытый ввод легко вставить дважды
        s.warn(f"{short}: токен не похож на 32 hex-символа ({len(token)}) — не вставлен ли дважды?")


def tokens(s, cfg):
    if not cfg.path.exists():
        shutil.copy(HERE / "config.env.example", cfg.path)
        if POSIX:
            cfg.path.chmod(0o600)
        s.ok("создан config.env из примера"
             + (" (права 600: в нём хранятся токены)" if POSIX else ""))
    s.note("все три хранятся в config.env (" + ("права 600, " if POSIX else "")
           + "в git не входит); Enter - пропустить")
    if not sys.stdin.isatty():
        s.warn("нет терминала, ввод токенов пропущен")
        return
    base = cfg.get("TUIS_URL").rstrip("/")
    for key, name, where, page in TOKENS:
        ask_token(s, cfg, key, name, where, base + page if page else None)


def dirs(s, cfg):
    state = cfg.state_file().parent
    state.mkdir(parents=True, exist_ok=True)
    s.ok(f"снимок состояния сводки: {state}")
    codes = cfg.codes()
    titles = load_state(cfg).get("courses") or {}   # сети на этом шаге нет — названия из снимка
    for cid, code in codes.items():
        (ROOT / code / "stash").mkdir(parents=True, exist_ok=True)   # tuis/ заведёт study answer
        made = courses.notes_stub(code, cid, titles.get(str(cid)), local.flow_of(cfg, code))
        s.ok(f"{ROOT / code}{os.sep}{{stash" + (",NOTES.md}" if made else "}"))
    if not codes:
        s.note("папки курсов появятся на шаге «Курсы»")


def check(s, m):
    try:
        s.ok("Moodle отвечает: " + m.me()["fullname"].strip())
    except StudyError:
        s.warn("Moodle не отвечает: проверь токен и TUIS_URL в config.env")
    try:
        s.ok("команда study: " + link_command())
    except OSError as e:
        s.warn(f"команда study не поставлена ({e}): запускай {HERE / 'study'}")
        return
    path_hint(s)


def operator(s):
    s.note("инструкция для агента (.digest/docs/AGENTS.md) кладётся блоком в файл оператора")
    s.note("в корне учебной директории; всё вне блока - личные правила, они не трогаются")
    print()
    if not sys.stdin.isatty():
        s.warn("нет терминала, шаг пропущен: позже study agent <код>")
        return
    print(textwrap.indent(agent.render([agent.status(o) for o in agent.OPERATORS]), "  "))
    print()
    answer = s.ask("какие поставить (коды через пробел, Enter - пропустить):").split()
    if not answer:
        s.note("пропущено: позже study agent <код>")
    elif all(o in agent.OPERATORS for o in answer):
        for o in answer:
            agent.install(o)
        s.ok("поставлено: " + " ".join(answer))
    else:
        s.warn("не удалось, проверь коды: study agent")


def courses_(s, cfg, m):
    s.note("какие курсы не отслеживать и как зовутся их папки; потом - первое наполнение stash/")
    if not sys.stdin.isatty():
        s.warn("нет терминала, шаг пропущен: позже study courses --setup")
        return
    try:
        out = courses.setup(cfg, courses.rows(cfg, m))
    except StudyError:
        s.warn("не удалось (нет токена Moodle?): позже study courses --setup")
        return
    print("config.env обновлён: COURSE_IGNORE ({}), CODE ({})".format(
        len(out["ignore"]), len(out["code"])))
    s.ok(f"записаны в config.env: {len(out['code'])} папок")
    # сводка тянет только новое с прошлого запуска, поэтому первое наполнение - отдельно
    print()
    if not yes(s.ask("скачать материалы всех курсов в stash/ сейчас? [Y/n]"), "y"):
        s.note("позже: study files --pull")
        return
    progress = files.Progress()
    try:
        for d in files.walk(cfg, m, do_pull=True, progress=progress):
            progress.clear()
            print("  " + files.summary(d, pulled=True))
    except StudyError:
        progress.clear()
        s.warn("не всё скачалось: позже study files --pull")
    else:
        s.ok("материалы курсов в stash/")


def resume():
    """Шаги, уже сделанные install.py, и их результаты — из STUDY_SETUP."""
    raw = os.environ.get("STUDY_SETUP")
    d = json.loads(raw) if raw else {}
    return list(d.get("steps") or []), [list(x) for x in d.get("log") or []]


def run(cfg):
    """Все шаги по очереди; вернуть лог и текст итогового экрана."""
    done, log = resume()
    s = Screen(done + STEPS, log)
    m = Moodle(cfg)   # токен читается лениво — уже после шага «Токены»
    plan = [lambda: tokens(s, cfg), lambda: dirs(s, cfg), lambda: check(s, m),
            lambda: operator(s), lambda: courses_(s, cfg, m)]
    for i, fn in enumerate(plan, len(done) + 1):
        s.step(i)
        fn()
    return s.log, s.final(ROOT, HERE / "docs" / "daily-digest-prompt.md")
