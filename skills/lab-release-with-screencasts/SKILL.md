---
name: lab-release-with-screencasts
description: Hand in a `screencast` lab — course repository from the teacher's template, git-flow, Quarto report and slides, release with files on GitVerse and SourceCraft, Rutube screencasts, TUIS answer with links. Use when `study task` names this skill (Kulyabov's and Korolkova's courses, e.g. net-os-admin, nettech).
metadata:
  source: study-digest
---

# Lab with release and screencasts

The teacher reviews the repository itself: branches, tags and commits follow the course rules
exactly. Before the first lab in a course read «Регламент курса» in its `NOTES.md` (repository
from the template, `git flow init`, Git and GPG settings, first release); the primary source is
`stash/000 Подготовка стенда.pdf`. Commits are Conventional Commits and GPG-signed.

Two steps on GitVerse are web-only, the API cannot do them: creating the course repository from
the teacher's template, and a pull request from your fork into the teacher's repository. Give the
user the link and the exact clicks instead of trying `gitverse api`.

The user performs the lab on camera. Prepare the environment and a cheat sheet beforehand; do
not run the lab steps yourself.

**The release comes last**: it needs the finished report and slides.

## Steps

1. **Work, on camera.** `git flow feature start labNN` → commits `feat(labNN): …` →
   `git flow feature finish labNN`.
2. **Screenshots** from the recording (`ffmpeg`) into `labs/labNN/report/image/`; cover the
   webcam corner.
3. **Report** `labs/labNN/report/<course>-labNN-report.qmd`, `make` in that folder
   (`quarto render`) → `_output/*.docx`, `*.pdf`. Sections: goal, task, theory, steps with
   figures, differences from the handout, answers to the control questions, conclusions,
   references, appendix with the changed files.
4. **Slides** `labs/labNN/presentation/<course>-labNN-presentation.qmd`, `make` →
   `_output/*.pdf` (beamer), `*.html` (revealjs).
5. **Commit** `docs(labNN): add report and presentation`.
6. **Git release.** `git flow release start X.Y.Z` → bump `version` in `package.json` (after
   `release start`: a dirty tree makes it fail; without the bump `standard-changelog` adds no
   section) → `standard-changelog -c .changelogrc.json` → commit `chore(site): release X.Y.Z` →
   `git flow release finish -s X.Y.Z` →
   `git push origin master develop --tags` and the same to `src` → copy `CHANGELOG.md` into
   `<course>/release/`.
7. **Hosting releases.** In the repo: `labrelease publish NN`. The plan checks that the report
   and slides are built, `CHANGELOG.md` has the section for the tag and the tag is pushed to both
   remotes; it lists what will be created and uploaded. Show it, wait for "yes", repeat with
   `--confirm`. It creates «vX.Y.Z — Лабораторная работа № N» on both hostings with the
   CHANGELOG section as notes and uploads seven files: report `.pdf`/`.docx`/`.md`, slides
   `.pdf`/`.md`/`-html.zip`, `-sources.zip`. Running it again uploads only what is missing.
8. **Screencasts** (Rutube; VK is optional and manual). A playlist per lab:
   `rutube playlist create --title "…" --slot playlist --env <course>/tuis/labNN.env`. Each video:
   `rutube upload <file> --title "<course>/labNN — …" --slot lab|report|presentation|defense
   --env <course>/tuis/labNN.env --playlist <id>` → plan → "yes" → `--confirm`. The command
   writes the link into `labNN.env` itself. The title must contain the lab number as `labNN`
   or `№ N`. If the playlist did not take the video yet (still processing), the output gives the
   `rutube playlist add …` to run later. Never look a video up by title in the channel list.
9. **Answer.** `labrelease answer NN` → `<course>/tuis/labNN.md` (the first run creates
   `labNN.env`). It refuses when a video does not match the lab — no number in the title, or
   uploaded before the previous release; fix the link (`rutube playlist remove`, re-upload)
   and run again. Compare the «Видео в ответе» list with the recordings.
10. **Submit.** `study task <course> NN` for the id →
    `study submit <id> --text <course>/tuis/labNN.md --attach <report.pdf> <slides.pdf>` →
    plan → "yes" → `--confirm`.

`tuis/` stays outside the repository and out of its `.gitignore`.

## Fixing a published release

Typo or missing file: `git flow hotfix start X.Y.Z+1` from `master` → `fix(labNN): …` → bump
`version` → `standard-changelog -c .changelogrc.json` → `chore(site): release X.Y.Z+1` →
`git flow hotfix finish -s X.Y.Z+1` → push both branches and the tag to both remotes →
`labrelease publish NN --tag vX.Y.Z+1`. Keep the old release.

## CHANGELOG and links

`standard-changelog` (angular preset) writes GitHub-style links; GitVerse has `/commit/<sha>` and
no tag comparison. That is why the repo root has `.changelogrc.json` with
`{"commit": "commit", "linkCompare": false}`. Full regeneration (`-r 0`) yields nothing under
git-flow (tags sit on merge commits) — only the new section is written. `sourcecraft release`
and `sourcecraft update` rewrite GitVerse links into SourceCraft ones, so one CHANGELOG serves
both. Fix the notes of a published release: `gitverse update <tag> --notes F`,
`sourcecraft update <tag> --notes F`.
