# Commands

Every command has `--help`. `--json` before or after the command name prints the same data as
the text output.

Exit codes: `0` success; `1` a plan without confirmation or a failed check (`study submit`,
`rutube upload`, `labrelease publish` without `--confirm`; `labrelease answer` with a video that
does not match; `study update` without `--yes`); `2` an error (message and hint on stderr, bad
arguments); `130` interrupted.

## study — TUIS

| Command | What it does |
|---------|--------------|
| `study state [--days N] [--pull] [--no-save] [--since X]` | the digest; `--pull` also downloads the new course files. A run without `--no-save` moves the snapshot «new since the last run» — see [configuration](configuration.md#snapshot) |
| `study task <course> <NN\|id\|cmid>` | one assignment: full text, deadline, what the answer accepts, its state, grade, feedback and comments, the submission profile and its skill, files on disk, matching `stash/` files |
| `study assigns [--course <c>]` | assignments and deadlines, including those closed by an access restriction (with the reason) |
| `study grades [--course <c>]` · `calendar [--days N]` · `status <id>` | grades, calendar deadlines, the state of one answer |
| `study files [<course>] [--pull] [--all] [--force]` | course files new since the last run; `--pull` downloads documents up to 50 MB into `<course>/stash/` (all of them into an empty `stash/`, re-uploaded ones over the old copy); `--force` downloads everything again. Course links are listed as «ссылка … → URL» |
| `study submit <id> [--text F] [--attach F…] --confirm` | send an answer. Without `--confirm` it prints the plan; a plan that does not fit the assignment (text off, too many files, wrong type or size, closed) is refused even with `--confirm`. Sending is final |
| `study upload <file>… [--itemid N]` · `submit … --files <itemid>` | the older two-step way to attach files |
| `study courses [--all] [--setup]` | your courses with folder and profile; `--setup` edits `COURSE_IGNORE`, `CODE`, `FLOW` |
| `study me` · `functions [substring]` · `call <function> key=value…` | token owner, functions available to the token, a raw call (a repeated key becomes an array) |
| `study agent [operator…]` | install the agent instructions and skills; without arguments, show their state |
| `study update [--check\|--yes]` | update the tools — see [configuration](configuration.md#updates) |
| `study setup` | first-time setup again: tokens, folders, commands in PATH, agent, courses |

### `--json` of `study state`

`schema` (2), `now`, `days`, `tuis`, `update`, `errors`. A breaking change bumps `schema`, new
fields do not.

`tuis`: `first_run`, `since`, `courses`, `new_courses`, `deadlines`, `overdue`, `submitted`,
`not_started` (the source of «Горит»), `retakes` (with `retake_of`, `needed`), `quizzes`,
`updates`, `new_assignments`, `moved`, `notifications`, `announcements`, `feedback`,
`comments`, `grades`, `outside` (deadlines in hidden courses), `errors`.

An assignment: `assign_id`, `cmid`, `course`, `name`, `short`, `due` (with extension),
`submission` (`new` · `draft` · `reopened` · `submitted` · `offline` · `hidden`), `graded`,
`grade`, `feedback`, `comments`, `comments_new`, `closed`, `opens`, `canedit`, `locked`,
`intro`, `lab`, `retake`. A time is `{ts, iso, text, full, left, left_sec, overdue}`, always
in Moscow time.

## labrelease — a lab on camera

Run inside the course repository: the course code comes from its `COURSE` file (the teacher's
template puts it there), `tuis/` lives next to the repository.

| Command | What it does |
|---------|--------------|
| `labrelease publish <NN> [--tag T] [--confirm]` | checks that the report and slides are built, `CHANGELOG.md` has the section for the tag and the tag is pushed to both remotes; creates «vX.Y.Z — Лабораторная работа № N» on GitVerse and SourceCraft with the CHANGELOG section as notes and uploads the missing ones of seven files (report `.pdf`/`.docx`/`.md`, slides `.pdf`/`.md`/`-html.zip`, `-sources.zip`) |
| `labrelease answer <NN> [--tag T]` | writes `tuis/labNN.md` with links to the playlist, videos, repositories and release; the first run creates an empty `tuis/labNN.env`. Refuses if a Rutube video has no work number in its title or was uploaded before the previous release |

The whole procedure: skill [lab-release-with-screencasts](../skills/lab-release-with-screencasts/SKILL.md).

## gitverse, sourcecraft

```
gitverse    releases | release <tag> --title T --notes F | update <tag> [--title T] [--notes F] | asset <release-id> <file> | api <path>
sourcecraft releases | release <tag> --title T --notes F | update <tag> [--title T] [--notes F] | asset <tag> <file>        | api <path>
```

The repository comes from the git remote of the current directory (`origin` — GitVerse, `src` —
SourceCraft), otherwise from `GV_REPO` / `SC_REPO`. API notes: [hosting-api.md](hosting-api.md).

## rutube

```
rutube jwt [--refresh T] | login [--email E] | me | api <path> | categories
rutube video <id> | edit <id> [--title T] [--desc F] [--category N] [--age A] [--hidden | --visible]
rutube playlist list | create --title T [--hidden] [--slot playlist --env F] | videos <id> | add <playlist> <video> | remove <playlist> <video>
rutube upload <file> | --url U [--title T] [--category N] [--age A] [--hidden] [--playlist ID] [--slot lab|report|presentation|defense [--env F]] --confirm
```

`--slot … --env <course>/tuis/labNN.env` writes the link into the `RUTUBE_<SLOT>` line of that
file. If the playlist does not take a fresh video yet (still processing), the upload succeeds
anyway and prints the `rutube playlist add` to run later. Signing in: [configuration](configuration.md#tokens).
