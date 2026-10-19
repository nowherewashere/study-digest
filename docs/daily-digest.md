# Daily digest task

Once a day an AI agent runs `study state --pull` and prints the result as is — the program lays
out the digest, the agent adds nothing. The steps are the skill
[study-digest](../skills/study-digest/SKILL.md), installed by `study agent`.

## Claude Code Desktop

Code → **Routines** → New routine → **Local** (a cloud routine cannot see local files and
tokens):

| Field | Value |
|-------|-------|
| Working folder | the study directory |
| Schedule | Daily, 9:00 |
| Instructions | `Run the study-digest skill.` |

Press **Run now** once and answer «always allow» for `study` (with WSL — for `wsl.exe`),
otherwise every run waits for confirmation.

## Linux, macOS

The task runs from the study directory. If its PATH lacks `~/.local/bin` (macOS: add
`export PATH="$HOME/.local/bin:$PATH"` to `~/.zprofile`), the skill falls back to
`python3 .digest/study state --pull`.

## Windows

Claude Code Desktop runs commands in Git Bash and finds `~/.local/bin/study` when
`%USERPROFILE%\.local\bin` is in the user PATH (`study setup` offers to add it); otherwise
`py .digest/study state --pull`. Output is UTF-8 regardless of the console code page.

## Windows with the tools in WSL

Install from WSL. The task's working folder is `\\wsl.localhost\<distro>\home\<…>\study`, the
shell is Git Bash, and commands go through `wsl.exe`:

```bash
MSYS_NO_PATHCONV=1 wsl.exe -d <distro> -- bash -c 'cd ~/work/study && study state --pull'
```

- `MSYS_NO_PATHCONV=1` is required: otherwise Git Bash turns `/tmp/x.sh` into a Windows path.
- Loops and variables break inside `bash -c '…'`; anything longer than one command goes into a
  script written to `//wsl.localhost/<distro>/tmp/` and run as `bash /tmp/<name>.sh`.
- Files are read through the `\\wsl.localhost` path directly; WSL symlinks do not open there,
  which is why the operator file and skills are copies, not links.
