---
name: study-update
description: Update the study tools from their repository after the user agrees. Use when the digest ends with «Обновление study: …» or «Блок агента … устарел», or the user asks to update study.
metadata:
  source: study-digest
---

# Updating the tools

An update changes code that handles the user's tokens, so it never runs on its own.

1. `study update --check` — show the user the plan as printed: commits, `diff --stat`, and
   whether the signature of the upstream commit was verified. An unverified signature is worth
   saying out loud.
2. Wait for an explicit "yes".
3. `study update --yes`. It pulls (`git pull --ff-only`) and refreshes the installed instruction
   blocks and skills. If only the block is stale («Блок агента … устарел»), `study agent <operator>`
   is enough.
4. The instructions in the operator file and the skills are new now — re-read them before
   continuing.

If `--check` says the clone has local commits or `git pull --ff-only` fails, do not fix it by
hand: report it. Local changes to `.digest/` are not supported; fixes go upstream as a PR.
