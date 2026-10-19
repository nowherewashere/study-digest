# Study directory and the `study` tools

> Audience: an AI agent working in this folder; read before any work here.
> `study agent <operator>` installs this text into the operator file (`CLAUDE.md`, `AGENTS.md`, …)
> and the skills from `.digest/skills/` into `.claude/skills/` or `.agents/skills/`.

Talk to the user and write `NOTES.md` in Russian. Tool output is Russian as well.

Just updated from 1.x (`study agent` shows the block «устарел», or there are no `study-*`
skills yet): follow `.digest/docs/upgrade-2.0.md` once.

## Layout

- `.digest/` — the tools (Python, stdlib only) and their settings: `study` (TUIS = Moodle),
  `gitverse`, `sourcecraft`, `rutube`, `labrelease`. `study setup` puts all five into
  `~/.local/bin`; otherwise run `python3 .digest/<command>` from the study root (Windows: `py`).
  Settings and tokens: `.digest/config.env`, outside git.
- `<course>/` — one folder per tracked course (`CODE <id> <folder>` in `config.env`):
  - `NOTES.md` — what is known about the course: teacher, submission format, deadlines, findings.
  - `stash/` — course materials from TUIS (`study files <course> --pull`).
  - `screencast` courses: the course repository (only the work itself, the teacher reviews it)
    and `tuis/` next to it (screencast links, answer draft).
  - `direct` courses: `labNN/` with the work and the files to hand in.

## Submission profiles

Every course has `FLOW <id> screencast|direct` in `config.env` (`study courses` shows it,
`study courses --setup` writes it). `study task <course> <NN>` prints the profile and its skill.

- `screencast` — the lab is done on camera: course repo from the teacher's template, git-flow,
  release with files on GitVerse and SourceCraft, Rutube videos, answer with links.
- `direct` — the answer goes straight into TUIS: text and/or files, whatever the assignment takes.

## Skills

| Skill | Use when |
|-------|----------|
| `study-digest` | the scheduled morning digest, or the user asks for the study summary |
| `study-task` | "what about lab N", preparing an assignment, reading a new handout |
| `study-lab` | doing and handing in a `direct` work (default report: Word, GOST 7.32) |
| `lab-release-with-screencasts` | a `screencast` lab: report, release, videos, answer |
| `study-course` | a new course, or the digest line «Без папки (файлы не скачиваются)» |
| `study-update` | the digest ends with «Обновление study: …» or «Блок агента … устарел» |

## Commands

Every command has `--help`; `--json` before or after the command name gives the same data.

| Command | What it does |
|---------|--------------|
| `study state [--pull] [--no-save] [--since X]` | the digest as markdown: deadlines with TUIS state, grades, notifications, new course files, «Горит»; `--pull` downloads new files into `stash/` |
| `study task <course> <NN\|id\|cmid>` | one assignment: full text, deadline, what it accepts, answer state, grade, feedback, profile and skill, files on disk, matching `stash/` files |
| `study assigns [--course <c>]` · `grades` · `calendar` · `status <id>` | assignments, grades, deadlines, answer state |
| `study files [<course>] [--pull\|--all\|--force]` | course files: new since last run, download |
| `study submit <id> [--text F] [--attach F…] --confirm` | send an answer; without `--confirm` prints the plan and checks it against the assignment settings |
| `study courses [--setup]` · `me` · `functions` · `call <fn> k=v` | courses and folders, token owner, raw Moodle calls |
| `study agent [operator…]` · `update [--check\|--yes]` · `setup` | install instructions and skills, update the tools, first-time setup |
| `gitverse` / `sourcecraft` `releases\|release\|update\|asset\|api` | releases; run inside the course repo |
| `rutube me\|video\|edit\|playlist …\|upload … --confirm` | own videos, playlists, upload |
| `labrelease publish NN [--confirm]` · `labrelease answer NN` | release a screencast lab on both hostings, compose the TUIS answer; run inside the course repo |

## Rules

- Nothing leaves the machine without the user's explicit "yes": `study submit`, `rutube upload`
  and `labrelease publish` are public or irreversible. Run them without `--confirm`, show the
  plan, wait, then repeat with `--confirm`.
- Never print tokens or copy them into notes or files. On `invalidtoken` the user issues a new
  Moodle token and runs `study setup` themselves.
- To look at the digest while debugging, use `study state --no-save`: a plain run moves the
  snapshot and the morning digest loses "new since last run".
- The course repository holds only the work. Service files (`tuis/`, drafts, links) live beside
  it and are not mentioned in the course `.gitignore`.
- Work recorded on screencast is performed by the user. Prepare the environment, reports,
  slides and uploads; do not run ahead.
- Before working on a course read its `NOTES.md`; after each work or finding, append to it.
- A refusal from `study submit` (closed, locked, restricted, wrong files) is final: report it,
  do not work around it.
- A bug in the tools: an issue or PR at github.com/nowherewashere/study-digest. Do not edit
  `.digest/` locally — `study update` is `git pull --ff-only` and stops on local commits.

## References

`.digest/docs/`: `cli.md` — every command, `--json` fields, exit codes; `configuration.md` —
`config.env`, tokens, courses, snapshot, updates; `daily-digest.md` — setting up the morning
task; `tuis-api.md`, `hosting-api.md` — the APIs.
