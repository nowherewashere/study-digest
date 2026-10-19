# Upgrading from study 1.x to 2.0 — once

> Audience: the agent, right after `study update` brought the tools from 1.x to 2.0. The 1.x
> updater pulled the code and rewrote the instruction block, but it does not know about skills,
> new commands or profile names. Do the steps below once, tell the user what was done, and do
> not come back to this file.

You are here if `study --version` is v2.x and there are no `study-*` skill folders in
`.claude/skills/` or `.agents/skills/` yet. A stale block alone («устарел» in `study agent`)
is an ordinary update — `study agent <operator>` is enough, this file is not needed.

1. **Instruction and skills.** `study agent` lists the operator files; for every one marked
   «устарел» run `study agent <operator>`. It rewrites the block and copies the skills.
2. **Commands.** `study setup < /dev/null` — without a terminal it skips tokens, operators and
   courses and only puts `study`, `gitverse`, `sourcecraft`, `rutube`, `labrelease` into
   `~/.local/bin` (on Windows: `.cmd` + sh scripts). Check: `labrelease --help`.
3. **Profiles.** `study courses` prints every course with its folder and profile («сдача»).
   Every course with a folder needs `FLOW <id> screencast|direct` in `.digest/config.env`:
   - `screencast` — the folder holds the course repository from the teacher's template
     (git-flow, releases, screencasts) — that is what 1.x guessed as `release`;
   - `direct` — everything else.
   Old values `release` / `file` keep working. For courses without a `FLOW` line, show the user
   the proposed profile per course, and after a "yes" append the lines to `config.env` (or let
   the user run `study courses --setup`).
4. **Daily digest task.** If its instructions point to `.digest/docs/daily-digest-prompt.md`
   (that file is gone), replace them with: «Прочитай `.claude/skills/study-digest/SKILL.md` и
   выполни его» (Codex, Gemini, Copilot: `.agents/skills/…`). For Claude Code Desktop the task
   text is `~/.claude/scheduled-tasks/<task>/SKILL.md` (Windows: under `%USERPROFILE%`). Show the
   user the change before writing it. A task that has the old prompt pasted in and runs
   `study state --pull` keeps working as is.
5. **Tell the user what changed for them:**

   | 1.x | 2.0 |
   |-----|-----|
   | `study gv …`, `study sc …`, `study rt …` | `gitverse …`, `sourcecraft …`, `rutube …` |
   | `study answer <course> <NN>` | `labrelease answer <NN>`, from the course repository |
   | uploading release files by hand | `labrelease publish <NN>` |
   | `study digest`, `study state --local` | `study state` (repository state is gone) |
   | `FLOW release\|file` | `FLOW screencast\|direct` |
   | `docs/daily-digest-prompt.md`, `docs/lab-submission.md` | skills `study-digest`, `lab-release-with-screencasts` |

6. **Notes.** `NOTES.md` files and the user's own part of the operator file may mention the old
   commands; offer to update those lines. History entries (what was done on a date) stay as
   they are.

Tokens, `.secrets/`, `tuis/labNN.env` and the digest snapshot are unchanged.
