# TUIS (Moodle) API

> Audience: whoever edits `src/study/moodle.py`, `assigns.py`, `digest.py` or calls `study call`.
> Read when adding a data source to the digest or when TUIS answers strangely.

Moodle 4.5 at `https://esystem.rudn.ru` (`TUIS_URL` in `config.env`). Every call is a POST to
`/webservice/rest/server.php` with `wstoken`, `wsfunction`, `moodlewsrestformat=json`; file
uploads go to `/webservice/upload.php`.

Token: `TUIS_TOKEN` in `config.env`, issued in the Moodle profile, «Ключи безопасности», service
**Moodle mobile web service**; the value is shown once, on creation or after «Очистка». It grants
full access to the account — never put it into a repository or notes.

Raw calls: `study call <function> key=value` (a repeated key becomes an array); the list of
functions available to the token: `study functions [substring]`; course ids: `study courses`.

How the replies are interpreted — errors inside HTTP 200, warnings from the write calls, paging,
hidden assignments, the state of an answer, new files — is the client's job and is pinned by
`tests/test_moodle.py`, `test_assigns.py`, `test_digest.py`, `test_files.py`.

## Functions in use

| Function | Used for | Key parameters |
|----------|----------|----------------|
| `core_webservice_get_site_info` | token check, `userid`, available functions, upload size limit | — |
| `core_enrol_get_users_courses` | my courses | `userid` |
| `core_course_get_contents` | sections, modules, files, deadlines in `dates[]` (also of restricted assignments) | `courseid` |
| `core_course_get_updates_since` | what changed in a course since a moment | `courseid`, `since` |
| `mod_assign_get_assignments` | assignments with their submission settings | — (all courses) |
| `mod_assign_get_submission_status` | my answer: state, attempt, grade, feedback | `assignid` |
| `core_comment_get_comments` | comments under my answer | `contextlevel=module`, `instanceid=<cmid>`, `component=assignsubmission_comments`, `itemid=<submission id>`, `area=submission_comments` |
| `mod_quiz_get_quizzes_by_courses` | quizzes: open/close time, time limit, attempts | `courseids[]` |
| `mod_quiz_get_user_attempts` | my quiz attempts | `quizid`, `status=all` |
| `mod_choice_get_choices_by_courses`, `mod_choice_get_choice_options` | talk topic choices and whether one is chosen | `courseids[]`, `choiceid` |
| `gradereport_user_get_grade_items` | grades and course total | `courseid`, `userid` |
| `core_calendar_get_action_events_by_timesort` | deadlines of all courses | `timesortfrom`, `timesortto`, `limitnum` ≤ 50, cursor `aftereventid` |
| `core_message_get_messages` | TUIS notifications | `useridto`, `type=notifications`, `read=0` |
| `mod_forum_get_forums_by_courses`, `mod_forum_get_forum_discussions` | announcements (forums of `type: news`) | `courseids[]`, `forumid` |
| `/webservice/upload.php` | upload a file into a draft area → `itemid` | `token`, `filearea=draft`, `itemid` |
| `mod_assign_save_submission` | save an answer (with `submissiondrafts=0` that is the submission) | `assignmentid`, `plugindata[…]` |
| `mod_assign_submit_for_grading` | submit a draft when `submissiondrafts=1` | `assignmentid`, `acceptsubmissionstatement` |

Course files are downloaded by plain GET: `<fileurl>&token=<token>`.

## Not available

- **Class schedule.** The Moodle calendar holds only deadlines. The schedule lives in separate
  RUDN services (`rudn_get_calendar_monthly_view`, `local_course_tasks_service`), each with its
  own token on the «Ключи безопасности» page; the mobile-service token does not open them.
- **Course relevance by dates**: `enddate` is empty for almost every course.
- **Taking quizzes** (`mod_quiz_start_attempt`, `save_attempt`, `process_attempt`) is technically
  available but not used by design: answering a graded quiz for the student is not our job.

## Might be useful later

| Function | For |
|----------|-----|
| `core_calendar_get_calendar_upcoming_view` | the ready-made «upcoming» block |
| `core_completion_get_activities_completion_status` | completion marks of course items |
| `mod_forum_add_discussion_post` | replying in a forum |
| `core_course_get_courses_by_field` | course details by id or short name |
| `core_files_get_files` | walking the file storage directly |
| `mod_choice_submit_choice_response` | choosing a talk topic (not used: the user chooses) |
| `mod_quiz_get_attempt_review` | review of a finished attempt for preparation |
