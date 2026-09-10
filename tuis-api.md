# ТУИС: справочник ручек

Moodle 4.5 на `https://esystem.rudn.ru`. Все вызовы — POST на
`/webservice/rest/server.php` с параметрами `wstoken`, `wsfunction`, `moodlewsrestformat=json`.
Загрузка файлов — отдельный эндпоинт `/webservice/upload.php`.

Токен: `~/.config/tuis/token` (права 600). Получается в профиле Moodle,
раздел «Ключи безопасности», служба **Moodle mobile web service**; значение
показывается один раз при создании или после «Очистка». Токен даёт полный
доступ к учётной записи — в репозитории и заметки не класть.

Обёртки — единый CLI `digest/study`: произвольный вызов `study call <функция> ключ=значение`,
сводка `study digest`, состояние `study state`. Про хостинги кода — `hosting-api.md`.

## Что используется сейчас

| Функция | Зачем | Ключевые параметры |
|---------|-------|--------------------|
| `core_webservice_get_site_info` | проверка токена, `userid`, список доступных функций (454 шт.) | — |
| `core_enrol_get_users_courses` | мои курсы: id, название, `hidden`, даты | `userid` |
| `core_course_get_contents` | разделы курса, модули, файлы с `timemodified` и **сроки в `dates`** | `courseid` |
| `core_course_get_updates_since` | что изменилось в курсе с момента времени — основа отслеживания обновлений | `courseid`, `since` (unix) |
| `mod_assign_get_assignments` | все задания всех курсов: `id`, `cmid`, `duedate`, `intro`, настройки сдачи | без параметров — по всем курсам |
| `mod_assign_get_submission_status` | состояние моего ответа: статус, попытка, оценка, отзыв | `assignid` |
| `mod_quiz_get_quizzes_by_courses` | тесты курсов: `timeopen`, `timeclose`, `timelimit`, число попыток | `courseids[]` |
| `mod_choice_get_choices_by_courses` | элементы «выбор темы доклада»: `id` и `coursemodule` для связи с cmid из состава курса | `courseids[]` |
| `mod_choice_get_choice_options` | варианты выбора; у выбранного `checked: true` — так видно, выбрана ли тема | `choiceid` |
| `mod_quiz_get_user_attempts` | мои попытки прохождения теста | `quizid`, `status=all` |
| `gradereport_user_get_grade_items` | баллы: строки ведомости, `graderaw`/`grademax`, итог курса | `courseid`, `userid` |
| `core_calendar_get_action_events_by_timesort` | события календаря: сроки всех курсов, в том числе не из `config.env` | `timesortfrom`, `timesortto`, `limitnum` (максимум **50**) |
| `core_message_get_messages` | уведомления ТУИС (о сроках, о проверке работ) | `useridto`, `type=notifications`, `read=0`, `limitnum` |
| `/webservice/upload.php` | загрузка файла в черновую область, возвращает `itemid` | `token`, `filearea=draft`, `itemid`, `file_1=@файл` |
| `mod_assign_save_submission` | сохранение ответа на задание | `assignmentid`, `plugindata[onlinetext_editor][text]`, `[format]=4`, `[itemid]=0`, `plugindata[files_filemanager]=<itemid>` |

Виды `updates` у `core_course_get_updates_since`: `contentfiles` и `contents` — новые
или изменённые файлы, `configuration` — правка настроек модуля, `submissions`,
`grades`, `answers` — активность (своя и чужая), в сводке отфильтрованы как шум.

## Пригодится дальше

| Функция | Зачем |
|---------|-------|
| `mod_assign_submit_for_grading` | явная отправка на проверку (в наших курсах не нужна: `submissiondrafts=0`, сохранение = сдача) |
| `core_calendar_get_calendar_upcoming_view` | то же в виде готового блока «предстоящее» |
| `gradereport_user_get_grade_items` | оценки и баллы по курсу |
| `core_completion_get_activities_completion_status` | отметки о выполнении элементов курса |
| `mod_forum_get_forums_by_courses`, `mod_forum_add_discussion_post` | форумы и объявления курса |
| `core_course_get_courses_by_field` | сведения о курсе по id/короткому имени |
| `core_files_get_files` | обход файлового хранилища напрямую |
| `mod_choice_submit_choice_response` | выбрать тему доклада за меня (пока не используется: тему выбирает пользователь) |
| `mod_quiz_get_attempt_review` | разбор уже сданной попытки: вопросы, правильные ответы, комментарии — для подготовки |

Полный список: `study functions` — общее число, `study functions assign` — фильтр по подстроке.

## Идентификаторы курсов

| id | Курс |
|----|------|
| 131 | Администрирование сетевых подсистем |
| 130 | Сетевые технологии |
| 5934 | Вычислительные методы |
| 6087 | Реляционные базы данных |

## Грабли

- Отправка ответа необратима: у заданий `submissiondrafts=0`, сохранение сразу считается сдачей.
  Поэтому `study submit` без `--confirm` только печатает план и выходит с кодом 1.
- Формат текста ответа: `[format]=4` — это FORMAT_MARKDOWN, как и просит чек-лист преподавателя.
  (HTML был бы `1`, простой текст `2`.)
- Файлы сначала грузятся в черновую область (`upload.php`), затем `itemid`
  передаётся в `mod_assign_save_submission`. Несколько файлов — один и тот же `itemid`.
- Ограничение на размер файла: 3 ГБ (`usermaxuploadfilesize` из `site_info`).
- **`mod_assign_get_assignments` показывает не все задания.** Элементы с ограничением
  доступа (например, «Сдать доклад» до выбора темы) в ответ не попадают, вместо них
  приходит `warnings: No access rights in module context`. Сроки таких заданий видны
  только через `core_course_get_contents` в поле `dates` — сводка берёт их оттуда.
- **В календаре Moodle нет расписания занятий** — только сроки сдач (`due`, `close`).
  Расписание живёт в отдельных службах РУДН (`rudn_get_calendar_monthly_view`,
  `local_course_tasks_service`), у каждой свой токен на странице «Ключи безопасности»;
  токеном mobile-службы они не открываются (`invalidrecord`).
- Календарь тоже показывает не всё: задания с ограничением доступа («Сдать доклад»)
  в события не попадают, их видно только через `core_course_get_contents`.
- `enddate` у курсов почти везде пустой, определить «актуальность» по датам курса нельзя.
- Оценки закрытого курса недоступны: `nopermissiontoviewgrades`, если запись на курс истекла.
- **Файлы курса качаются не через REST.** В `core_course_get_contents` у каждого файла
  есть `fileurl` вида `…/webservice/pluginfile.php/<contextid>/<компонент>/…`; скачивается
  он обычным GET с токеном в query: `<fileurl>&token=<токен>` (проверено 10.09.2026, 200 OK).
  Полезные поля рядом: `filename`, `filesize`, `timemodified` — по последнему видно, что файл
  обновился. Элементы `mod_page` отдают `index.html` с `filesize: 0` — это не файл, а страница.
- **Массивы параметров кодируются по-Moodle**: `courseids[0]=131&courseids[1]=130`,
  а не повторением ключа и не JSON-массивом.
- **Ошибка приходит с HTTP 200.** Тело вида `{"exception": …, "errorcode": …, "message": …}`
  — проверять надо тело ответа, а не код. Частые коды: `invalidtoken` (токен перевыпущен),
  `nopermissiontoviewgrades` (запись на курс истекла), `invalidrecord` (функция не входит в
  службу этого токена).
- **Уведомления**: `core_message_get_messages` с `useridfrom=0`, `type=notifications`, `read=0`,
  `newestfirst=1`. Сообщения «Новый вход в ваш аккаунт» отфильтровывать — иначе забивают сводку.
- **Сроки в составе курса** (`core_course_get_contents`) лежат в `dates[]`, и у каждой записи
  есть машинное поле `dataid`: `duedate` у заданий, `timeclose`/`timeopen` у тестов и выбора
  темы. Фильтровать по нему, а не по подписи `label` — подпись зависит от языка интерфейса.
- Прохождение тестов (`mod_quiz_start_attempt`, `save_attempt`, `process_attempt`) технически
  доступно, но не используется: отвечать за студента на оценочный тест — не наша задача.
  Из тестов берём только сроки, число попыток и разбор уже сданных попыток.
