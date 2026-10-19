# GitVerse and SourceCraft API

> Audience: whoever edits `src/hosting/client.py` or calls `gitverse api` / `sourcecraft api`.
> Read when adding a hosting or when a request fails with an unclear 4xx.

The course repository lives on two hostings: GitVerse is the main one (remote `origin`),
SourceCraft is the mirror (remote `src`). A lab release with the report and slides goes to both.

Tokens: `GITVERSE_TOKEN` and `SOURCECRAFT_TOKEN` in `config.env`. The repository comes from the
git remote of the current directory (`origin` for GitVerse, `src` for SourceCraft; a remote
pointing to another host is ignored), otherwise from `GV_REPO` / `SC_REPO` in `config.env`.

Quirks of both APIs (headers, body format, field names, file types) are handled in the client and
pinned by `tests/test_hosting.py`; this page lists only the endpoints and what the APIs cannot do.

## GitVerse

Base `https://api.gitverse.ru`, `Authorization: Bearer <token>`.

| Request | Purpose |
|---------|---------|
| `GET /repos/{owner}/{repo}/releases` | list releases (a bare array) |
| `POST /repos/{owner}/{repo}/releases` | create: `tag_name`, `target_commitish` (full SHA), `name`, `body`, `draft`, `prerelease` |
| `PATCH /repos/{owner}/{repo}/releases/{id}` | edit `name`, `body` |
| `POST /repos/{owner}/{repo}/releases/{id}/assets?name=<file>` | upload an asset, multipart |
| `GET /repos/{owner}/{repo}`, `/branches`, `/contents/{path}` | repository, branches, files |

Release page: `https://gitverse.ru/{owner}/{repo}/releases/tag/{tag}`.

What the API cannot do:

- No official CLI, and `docs/public-api` is sometimes 404. The OpenAPI spec lives in GitVerse
  itself: repository `gitverse/rest-api-description`, file `v1/openapi-1.9.json`; raw links do not
  work — fetch it with `GET /repos/gitverse/rest-api-description/contents/…` and decode base64.
- Creating a repository from a template — web interface only.
- A pull request from a fork into someone else's repository: `POST /repos/{owner}/{repo}/pulls`
  returns 400 for any form of `head`. Inside one repository it works. The web interface
  sometimes fails with «Сервис временно недоступен» — retry later.

## SourceCraft

Base `https://api.sourcecraft.tech`, `Authorization: Bearer <token>`. Swagger:
`https://api.sourcecraft.tech/sourcecraft.swagger.json`.

| Request | Purpose |
|---------|---------|
| `GET /repos/{org}/{repo}/releases` | list releases (`{"releases": [...]}`) |
| `POST /repos/{org}/{repo}/releases` | create: `tag`, `title`, `release_notes`, `publish` (no `target_branch` for an existing tag) |
| `PATCH /repos/{org}/{repo}/releases/tag/{tag}` | edit `title`, `release_notes` (by tag, not by id) |
| `POST /repos/{org}/{repo}/releases/tag/{tag}/attachments` | upload an asset, multipart |
| `GET /repos/{org}/{repo}`, `POST /orgs/{org}/repos` | repository, create a repository |

Release page: `https://sourcecraft.dev/{org}/{repo}/releases/{tag}`. The official `src` CLI is
not needed: everything goes through REST.

## Release notes and links

Both hostings take Markdown. `sourcecraft release` and `sourcecraft update` rewrite
`https://gitverse.ru/<gv-repo>` into `https://sourcecraft.dev/<sc-repo>`, so one CHANGELOG section
serves both; why the CHANGELOG uses `/commit/` links and no compare links — skill
`lab-release-with-screencasts`, «CHANGELOG and links».
