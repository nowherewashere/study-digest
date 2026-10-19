---
name: study-task
description: Analyse one assignment before working on it — full text, deadline, accepted answer, handout from stash, submission profile. Use for «что по лабе N», «разбери задание», preparing an environment, or when the digest named new files for a course the user is about to work on.
metadata:
  source: study-digest
---

# Analysing an assignment

1. Read `<course>/NOTES.md`. No file → `study-course` skill first.
2. `study task <course> <NN>` (`NN` — work number; or an id from `study assigns`, or a cmid from
   the digest). It prints the text, deadline, what the answer accepts (text, number and types of
   files), answer state, grade and feedback, the submission profile with its skill, what is on
   disk, and `stash/` files whose names match the number.
3. Read the handout from `stash/`. Missing → `study files <course> --pull`, then read. If the
   digest reported new files for this course, read them first.
4. Append to `NOTES.md`: deadline, variant, report requirements, anything non-obvious
   (one line per fact; the «Задания и сроки» table — from `study assigns --course <course>`).
5. Continue with the skill the task card names: `study-lab` (`direct`) or
   `lab-release-with-screencasts` (`screencast`). «Сдача: не задана» → `study-course`.

What the card tells you and what to do about it:

- «доступ закрыт» / «нужна группа …» — the assignment is closed by a restriction; the answer
  cannot be sent until the teacher opens it. Say so, do not search for a way around.
- «приём закрыт» — the deadline passed and TUIS takes no answer; a «Пересдача …» assignment, if
  there is one, is where the work goes now.
- «на доработку» — the answer was returned; the feedback and comments are on the card.
- «очно / без ответа в ТУИС» — nothing to submit online.
