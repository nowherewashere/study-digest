---
name: study-course
description: Set up a course folder — `CODE`/`FLOW` lines, `stash/`, `NOTES.md` from the syllabus. Use for a new course, when the digest shows «Без папки (файлы не скачиваются)» or «Новый курс в ТУИС», or when a course has no `NOTES.md`.
metadata:
  source: study-digest
---

# Setting up a course

The digest repeats «Без папки (файлы не скачиваются): …» until the course is either set up or
ignored — never drop that line silently. Ask the user which one they want.

## Ignore

Add the course id to `COURSE_IGNORE=` in `.digest/config.env` (or `study courses --setup`).

## Set up

1. Pick a short folder code (`nettech`, `rel-db`): latin, no `=`, short — paths with `=` break
   libvirt/virtiofs and long ones break Packer sockets.
2. `study courses --setup` asks for the folder and the profile and writes `CODE <id> <folder>` and
   `FLOW <id> screencast|direct` to `config.env`; it also creates `<folder>/stash/` and a
   `NOTES.md` stub. Editing `config.env` by hand is fine too — both lines are required.
   - `screencast` — the course has a repository from the teacher's template, git-flow, releases
     and screencasts (Kulyabov's and Korolkova's courses);
   - `direct` — everything else: the answer goes straight into TUIS.
3. `study files <folder> --pull` — materials into `stash/`.
4. Fill the `NOTES.md` header from the syllabus and grading rules in `stash/` (programme, БРС — the
   grading scheme, ФОС — the assessment materials): course in TUIS, teacher, submission format, grading. Fill «Задания и сроки» from
   `study assigns --course <folder>`.

For `direct` courses also record in the header what the title page needs: faculty, department,
group, teacher — the `study-lab` report template takes them from here.
