---
name: study-lab
description: Do and hand in a work for a `direct` course — the answer goes straight into TUIS as text and/or files. Default report is a Word document by GOST 7.32 built from Markdown. Use when `study task` names this skill, or the user asks to write a report, lab, homework or IDZ for a course without a release repository.
metadata:
  source: study-digest
---

# Work handed in directly to TUIS

Start with `study-task`: it gives the assignment text, what the answer accepts and the handout.

## What the result must look like

Take the first source that says anything:

1. the teacher: the assignment text, a template or example in `stash/`, the course syllabus;
2. the `NOTES.md` header of the course (format, title page fields, earlier decisions);
3. the default below.

If the course already has its own pipeline (LaTeX, typst, Quarto — see `NOTES.md` and earlier
`labNN/`), keep using it. Not every answer is a report: if the assignment wants a `.docx`, a
spreadsheet, code or just text, hand in that.

## Default: Word report, GOST 7.32

Layout: `<course>/labNN/` (also `hwNN/`, `idzNN/`) with `report.md`, `image/` and the code.

1. Copy `report.md` from this skill's folder into `<course>/labNN/`.
2. Fill the placeholders `{…}`: full name — `study me`; subject — course title; faculty,
   department, group, teacher — the `NOTES.md` header (ask the user once if missing and record
   the answer there); work number, topic and variant — from the assignment. Drop sections the
   work does not need; keep the order «Цель работы → Задание → Ход работы → Результаты →
   Выводы → Список литературы».
3. Figures: `![Рисунок N — подпись](image/NN.png){width=80%}`; tables: a paragraph
   «Таблица N — название» right above the table; code in fenced blocks.
4. Build: `python3 <this skill>/scripts/build.py <course>/labNN/report.md --pdf`. Needs `pandoc`;
   `--pdf` uses Word (Windows or WSL) or LibreOffice. The result is
   `<course>-labNN-report.docx` (and `.pdf`) next to `report.md`: Times New Roman 14, line
   spacing 1.5, margins 30/15/20/20 mm, paragraph indent 1.25 cm, page numbers from page 2,
   bordered tables. Extra pandoc options go after the file name.
5. Look at the PDF before handing it in: `pdftoppm -png -r 60 <pdf> page`, then read the images.

A teacher's own `.docx` template is filled in place rather than rebuilt; Anthropic's `docx` skill
(plugin `document-skills` from `anthropics/skills`) handles editing existing Word files.

## Handing in

1. `study task <course> NN` — what the assignment accepts: text on/off, number, types and size
   of files.
2. `study submit <id> --attach <file>…` (plus `--text <file>` only if the assignment takes text)
   — prints the plan and refuses on a mismatch.
3. Show the plan, wait for an explicit "yes", repeat with `--confirm`. Sending is final:
   TUIS keeps no draft.
4. Append a line to «Лабы» in `NOTES.md`.
