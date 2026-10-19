---
name: study-digest
description: Morning study digest — run `study state --pull` and print its markdown verbatim. Use for the scheduled daily digest task or when the user asks for the study summary («сводка», «что по учёбе»).
metadata:
  source: study-digest
---

# Daily digest

The program renders the whole digest itself: deadlines with TUIS state, grades, notifications,
announcements, new course files (already downloaded into `<course>/stash/`) and «Горит». The
agent only runs it and passes the output on. Work silently; reply once, in Russian.

## Run

The working folder is the study root — the directory that contains `.digest/`.

```bash
study state --pull
```

If `study` is not on PATH: `python3 .digest/study state --pull` (Windows: `py .digest/study
state --pull`, Git Bash).

Only when the working folder is a WSL path (`\\wsl.localhost\…`) and the shell is a Windows one,
go through WSL:

```bash
MSYS_NO_PATHCONV=1 wsl.exe -d <distro> -- bash -c 'cd ~/work/study && study state --pull'
```

Without `MSYS_NO_PATHCONV` Git Bash rewrites paths; `bash -lc '…'` one-liners lose variables —
anything longer than one command goes into a script under `//wsl.localhost/<distro>/tmp/` and
runs as `bash /tmp/<name>.sh`. Read files by their normal paths, not through `wsl.exe`.

## Output

1. Print the output exactly as is: no rewording, no trimming, no added sections, comments or
   plans. Open no files, start no work, send nothing to TUIS.
2. If it ends with «Обновление study: …» or «Блок агента … устарел», offer the `study-update`
   skill and wait for consent; do not run the update yourself.
3. If the command fails, say in one line what failed. Nothing else.
