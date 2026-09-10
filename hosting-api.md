# GitVerse и SourceCraft: справочник

Два хостинга кода, на которых лежит репозиторий курса: GitVerse — основной (remote `origin`),
SourceCraft — зеркало (remote `src`). По чек-листу преподавателя релиз с файлами отчёта и
презентации нужен на обоих.

Токены: `~/.config/gitverse/token` и `~/.config/sourcecraft/token`, права 600, пути задаются в
`config.env`. Репозиторий определяется по git-remote того каталога, откуда запущена команда,
либо задаётся переменными `GV_REPO` / `SC_REPO` (приоритет: переменная → `config.env` → remote).

## GitVerse

База `https://api.gitverse.ru`, авторизация `Authorization: Bearer <токен>`.

| Запрос | Назначение |
|--------|-----------|
| `GET /repos/{owner}/{repo}` | сведения о репозитории |
| `GET /repos/{owner}/{repo}/releases` | список релизов — **голый массив** |
| `POST /repos/{owner}/{repo}/releases` | создать релиз |
| `PATCH /repos/{owner}/{repo}/releases/{id}` | изменить релиз |
| `POST /repos/{owner}/{repo}/releases/{id}/assets?name=<имя>` | вложение, multipart |
| `GET /repos/{owner}/{repo}/branches`, `/contents/{path}` | ветки, файлы |

Тело создания релиза: `tag_name`, `target_commitish`, `name`, `body`, `draft`, `prerelease`.

Ссылка на релиз для человека: `https://gitverse.ru/{owner}/{repo}/releases/tag/{tag}`.

**Грабли, каждая стоила времени:**

1. **Обязателен заголовок** `Accept: application/vnd.gitverse.object+json;version=1`. Без него —
   400 с пустым телом, без единого намёка на причину.
2. **JSON-тело без хвостового перевода строки.** Если тело записано в файл через `print()` и
   отправлено целиком, сервер отвечает 422 с пустым телом. Сериализовать и отправлять байты как
   есть, ничего не дописывая в конец.
3. **`target_commitish` — только полный SHA коммита.** Имя ветки не принимается: 422.
   Значение берётся как `git rev-parse <тег>^{commit}`.
4. **Вложения**: имя файла передаётся query-параметром `?name=`, сам файл — в multipart-поле
   **`attachment`**. Расширения `.qmd` и `.html` отклоняются с `VALIDATION_ERROR`: `.qmd`
   копировать под именем `.md`, html класть в zip.
5. Официального CLI нет. Документация `docs/public-api` временами отдаёт 404; OpenAPI-спека
   лежит в самом GitVerse: репозиторий `gitverse/rest-api-description`, файл `v1/openapi-1.9.json`
   (raw-ссылки не работают, тянуть через `GET /repos/gitverse/rest-api-description/contents/…`
   и раскодировать base64). Копия — `~/.config/gitverse/openapi-1.9.json`.
6. **Создание репозитория из шаблона API не умеет** — только веб-интерфейс.
7. **PR из форка в чужой репозиторий API не создаёт**: `POST /repos/{owner}/{repo}/pulls`
   отвечает 400 при любой форме `head`. Внутри одного репозитория работает. Веб-интерфейс тоже
   падал с «Сервис временно недоступен», поэтому замечания преподавателю ушли на GitHub.

## SourceCraft

База `https://api.sourcecraft.tech`, авторизация `Authorization: Bearer <токен>`.
Swagger открыт: `https://api.sourcecraft.tech/sourcecraft.swagger.json`.

| Запрос | Назначение |
|--------|-----------|
| `GET /repos/{org}/{repo}/releases` | список — **объект** `{"releases": [...]}` |
| `POST /repos/{org}/{repo}/releases` | создать релиз |
| `POST /repos/{org}/{repo}/releases/tag/{tag}/attachments` | вложение, multipart |
| `POST /orgs/{org}/repos` | создать репозиторий |
| `GET /repos/{org}/{repo}` | сведения о репозитории |

Тело создания релиза: `tag`, `target_branch`, `title`, `release_notes`, `publish`.
Это то же самое, что делает `src release create --publish`, поэтому **CLI `src` не нужен**.

Ссылка на релиз для человека: `https://sourcecraft.dev/{org}/{repo}/releases/{tag}`.

**Грабли:**

1. **Вложение грузится строго в поле `file`** (не `attachment`, как у GitVerse). Ошибка при
   неверном имени поля внятная: `multipart/form must have file provided in "file" field`.
2. **Форма ответа отличается** от GitVerse: список релизов — объект с ключом `releases`,
   поля называются `tag`, `title`, `status`, вложения лежат в `assets`.
3. Расширения не ограничены: `.qmd` и `.html` принимаются как есть.
4. CLI `src` существует (`~/sourcecraft/bin/src`), берёт токен из переменной `SOURCECRAFT_TOKEN`,
   отдельный `login` не нужен. После перехода на REST он остаётся только для ручных задач.
5. Адрес remote — вида `ssh://ssh.sourcecraft.dev/{org}/{repo}.git`, **без `git@`**. Разбор
   remote должен переживать и такую форму, и `ssh://git@host:port/…`, и `git@host:…`, и `https://…`.

## Что общего

- Оба принимают Bearer-токен и отдают JSON.
- Оба различают репозиторий по паре `владелец/имя`.
- Формы ответов и имена полей у них **разные**, поэтому в коде они за одним интерфейсом
  (`releases`, `release`, `asset`, `web_url`), а различия спрятаны внутри классов.
- Порядок выпуска релиза описан в `../CLAUDE.md`, раздел «Порядок сдачи лабораторной работы»:
  сначала отчёт и презентация, потом тег через git-flow, и только потом релиз с файлами.
