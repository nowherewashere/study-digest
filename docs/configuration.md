# Configuration

Everything lives in `.digest/config.env` (outside git, mode 600 on POSIX; the template is
`config.env.example`). `study setup` writes it; rerun it to change tokens or courses.

## Study directory

```
<study directory>/
├── .digest/            the tools, config.env, .secrets/ (Rutube), .state.json, state/
├── <course>/
│   ├── NOTES.md        what is known about the course; study setup writes a stub once
│   ├── stash/          course files from TUIS
│   ├── labNN/          direct courses: the work and the files to hand in
│   ├── <course repo>/  screencast courses: the repository from the teacher's template
│   └── tuis/           screencast courses: labNN.env (video links), labNN.md (answer)
└── CLAUDE.md, AGENTS.md, …   operator files with the block from study agent
```

Paths: no `=` (breaks libvirt/virtiofs) and nothing long (Packer plugin sockets are limited to
108 bytes) — `install.py` checks this.

## Tokens

| Key / file | Where to get it |
|------------|-----------------|
| `TUIS_TOKEN` | Moodle profile → «Ключи безопасности» → *Moodle mobile web service*; shown once. `invalidtoken` means it was reissued — run `study setup` |
| `GITVERSE_TOKEN` | user icon → «Настройки» → «Управление токенами», access «Репозитории» |
| `SOURCECRAFT_TOKEN` | Home → Access → Personal Access Tokens |
| `.secrets/rutube-refresh` | accounts via VK ID / Gazprom ID: copy `refreshToken` from the rutube.ru cookies once and run `rutube jwt`; it refreshes itself for a year |
| `.secrets/rutube-token` | accounts with a password: `rutube login` |

Each token is needed only for its own service.

## Courses

| Line | Meaning |
|------|---------|
| `COURSE_IGNORE=<id> <id>…` | courses not tracked at all |
| `CODE <id> <folder>` | the course folder; without it the course shows up only by its deadlines, and the digest repeats «Без папки (файлы не скачиваются)» until you add a folder or ignore it |
| `FLOW <id> screencast\|direct` | how the course is handed in (required with `CODE`): `screencast` — lab on camera with repository, release and videos; `direct` — answer straight into TUIS. Old `release`/`file` still work |

`study courses --setup` edits all three. A course hidden in TUIS itself (not ignored) shows
its deadlines in «Сроки в скрытых курсах»; a new enrolment is announced once with «Новый курс в
ТУИС: …».

Other keys: `TUIS_URL` (default `https://esystem.rudn.ru`), `DIGEST_DAYS` (deadline window, 21),
`DIGEST_ACTIVE_DAYS` (a course not visited this long is suggested for the ignore list, 60),
`GV_REPO`, `SC_REPO` (hosting repository when not run from a repo).

## Snapshot

"New" in the digest means new since the previous run. `.digest/.state.json` keeps the time of
the run, deadlines, grades and course contents; a daily copy goes to `.digest/state/` for 60
days. Every `study state` without `--no-save` moves it — use `--no-save` to look without
consuming. `--since 2026-09-12` or `--since 3` (days) compares with the nearest older daily copy,
`--since never` behaves like a first run, `--since all` treats everything as new. A broken
`.state.json` falls back to the last daily copy.

Sections that could not be built after retries are skipped and named in the closing line
«Не удалось: …» (`errors` in JSON).

## Updates

`.digest/` is a git clone of this repository. `study update` shows the incoming commits,
`diff --stat` and whether the top commit's GPG signature verifies, asks, then runs
`git pull --ff-only` and refreshes the agent blocks and skills. Without a terminal it needs
`--yes`; `--check` only shows the plan. To make the signature check meaningful, import the key
from the signed tags. The digest checks for updates itself and ends with «Обновление study: …»
when there is one; an agent offers the update but never runs it without consent.

Versions are signed `vX.Y.Z` tags on `master` with
[GitHub Releases](https://github.com/nowherewashere/study-digest/releases); `master` is what
`install.py` installs.
