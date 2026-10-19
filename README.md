# study

> Moodle from the command line for a RUDN student: deadlines, grades, course files, submitting
> answers and a daily markdown digest — plus releases on GitVerse/SourceCraft and Rutube videos
> for labs done on camera.

[![ci](https://github.com/nowherewashere/study-digest/actions/workflows/ci.yml/badge.svg)](https://github.com/nowherewashere/study-digest/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.8%2B-blue)
![deps](https://img.shields.io/badge/deps-stdlib%20only-success)
![platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

- **Digest.** Deadlines with the state of your answer, quizzes, grades, teacher feedback and
  comments, notifications, announcements, new course files — one markdown page, new since the
  last run.
- **Assignments.** The full card of an assignment, and submitting an answer only after a plan
  that is checked against what the assignment accepts.
- **Course files** go into each course's `stash/`.
- **Labs on camera.** `labrelease` checks the build and the tag, publishes the release with
  its files on both hostings and writes the answer with links; `gitverse`, `sourcecraft`,
  `rutube` cover the services one by one.
- **AI agents.** `--json` everywhere; `study agent` installs instructions and skills for
  Claude Code, Codex, Gemini CLI or Copilot.

The tool's output is in Russian, like TUIS (the university Moodle) itself.

## The digest

`study state --pull` (made-up courses; empty sections are omitted):

```markdown
# Учёба · чт 08.10 09:00

## Сроки

| Когда | Осталось | Работа | Курс | Состояние |
| ----- | -------- | ------ | ---- | --------- |
| **06.10 23:59** | **просрочено** | **ДЗ 2 — Нормализация до 3НФ** | **databases** | **не сдано** |
| 12.10 23:59 | 4 дн | ЛР 3 — Индексы и планы запросов | databases | не сдано |
| 15.10 23:59 | 7 дн | Тема доклада к лекции 5 | crypto | не выбрана, 9 вариантов |
| 15.10 23:59 | 7 дн | Доклад к лекции 5 | crypto | доступ закрыт |
| 20.10 23:55 | 12 дн | Расчётно-графическая работа | Теоретическая механика | не сдано |

## Тесты

| Когда | Осталось | Тест | Курс | Попытки | Время |
| ----- | -------- | ---- | ---- | ------- | ----- |
| **09.10 18:00** | **1 дн** | **Тест после лекции №4** | **crypto** | **0 из 2** | **15 мин** |
| 23.10 18:00 | 15 дн | Тест после лекции №5 | crypto | 0 из 2 | 15 мин |

## Баллы

| Курс | Итого | Новое |
| ---- | ----- | ----- |
| databases | 14.50 / 20 | ЛР 2 4.50/5 |
| crypto | 9.00 / 12 | — |

## Уведомления

| Когда | Тема |
| ----- | ---- |
| 07.10 16:42 | Оценена работа «ЛР 2. Хранимые процедуры» |

## Объявления

| Когда | Курс | Тема |
| ----- | ---- | ---- |
| 08.10 09:12 | databases | **Лекция 5 переносится** · Петров П.: на пятницу, аудитория та же. |

## Новое в курсах

| Курс | Раздел | Что | Файлы |
| ---- | ------ | --- | ----- |
| crypto | Лекции | Материалы лекции 5: новые файлы | 05-rsa.pdf, 05-rsa-slides.pdf |
| databases | Общее | Объявления: изменены настройки | — |

## Горит

- **ДЗ 2 — Нормализация до 3НФ** · databases · до 06.10 23:59 · просрочено · методички: databases/stash/
- **ЛР 3 — Индексы и планы запросов** · databases · до 12.10 23:59 · 4 дн · методички: databases/stash/
```

«Горит» (urgent) is what is unsubmitted, overdue or due within a week, and still accepted.

## Install

Linux, macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/nowherewashere/study-digest/master/install.py -o install.py && python3 install.py; rm -f install.py
```

Windows (PowerShell; with Python from the Microsoft Store use `python` instead of `py`; in Git
Bash run `winpty py install.py`, otherwise it cannot ask questions):

```powershell
iwr https://raw.githubusercontent.com/nowherewashere/study-digest/master/install.py -OutFile install.py; py install.py; del install.py
```

Needs `python3` 3.8+ and `git`. The installer clones the tool into `<study directory>/.digest`
and runs `study setup`: tokens, course folders, commands in `~/.local/bin`, the AI agent, the
first download of course files. Tokens and options: [docs/configuration.md](docs/configuration.md).

## Use

```bash
study state --pull           # the digest; new course files into stash/
study task <course> <NN>     # one assignment: text, deadline, what it accepts, your answer
study submit <id> --attach report.pdf          # shows the plan; again with --confirm to send
```

All commands: [docs/cli.md](docs/cli.md). Every command has `--help`.

## Daily digest and agents

An AI agent task can run the digest every morning and print it as is:
[docs/daily-digest.md](docs/daily-digest.md) (Claude Code Desktop, Linux, macOS, Windows, WSL).
`study agent <claude|codex|gemini|copilot>` puts [the agent instructions](docs/AGENTS.md) into
the operator file and the [skills](skills/) into its skills folder; your own text and skills
next to them stay untouched.

## Updating

`study update` shows the incoming commits and whether they are signed, then pulls. The digest
says when an update is available. Coming from 1.x: [docs/upgrade-2.0.md](docs/upgrade-2.0.md).

Found a bug? Open an issue or a pull request — do not edit `.digest/` locally, `git pull
--ff-only` stops on local commits. Development: [docs/development.md](docs/development.md).

## License

[MIT](LICENSE).
