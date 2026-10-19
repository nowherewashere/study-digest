# study 2.0 — one-time migration from 1.x

> This file exists only for installs updated from study 1.x: the 1.x updater writes it into the
> operator file. Step 1 replaces it with the real 2.0 instructions (`docs/agent.md`), so it is
> read once. Fresh 2.x installs never see it.

The tools were just updated from 1.x. Talk to the user in Russian. Do these steps once, show the
user each change before making it, then report what was done:

1. **Instruction and skills.** `study agent` lists the operator files; run `study agent <operator>`
   for every installed one. This replaces this block with the 2.0 instructions and installs the
   skills (`.claude/skills/` or `.agents/skills/`). Continue with the steps below.
2. **Commands.** `study setup < /dev/null` — without a terminal it only puts `study`, `gitverse`,
   `sourcecraft`, `rutube`, `labrelease` into `~/.local/bin`. Check: `labrelease --help`.
3. **Profiles.** Every course with a `CODE` line needs `FLOW <id> screencast|direct` in
   `.digest/config.env` (`study courses` shows them): `screencast` if the course folder holds the
   course repository from the teacher's template, otherwise `direct`. Old `release`/`file` keep
   working. Show the proposed lines, append after a "yes".
4. **Daily digest task.** If its text points to `.digest/docs/daily-digest-prompt.md` (gone),
   replace it with «Прочитай `.claude/skills/study-digest/SKILL.md` и выполни его»
   (`.agents/skills/…` for Codex, Gemini, Copilot). Claude Code Desktop keeps the task text in
   `~/.claude/scheduled-tasks/<task>/SKILL.md`.
5. **Tell the user what changed:** `study gv/sc/rt` → `gitverse`/`sourcecraft`/`rutube`;
   `study answer` → `labrelease answer <NN>` from the course repository; release files →
   `labrelease publish <NN>`; `study digest` and `state --local` are gone; `FLOW release|file` →
   `screencast|direct`; the old docs became skills. Tokens, `.secrets/`, `tuis/labNN.env` and the
   digest snapshot are unchanged. Offer to update old command names in `NOTES.md` files.
