# Development

```bash
python3 -m unittest                      # no network, no tokens
ruff check src skills tests study gitverse sourcecraft rutube labrelease install.py
shellcheck setup.sh
```

CI runs the same on Linux, macOS and Windows with Python 3.8 and 3.12.

## Layout

```
.digest/
├── study · gitverse · sourcecraft · rutube · labrelease   launchers (UTF-8 and VT mode on Windows)
├── src/kit/          shared: config.env and errors, net (urllib, retries), git, CLI plumbing
├── src/study/        TUIS: cli · digest · moodle · assigns · files · task · courses · agent
│                     · setup · update · config · fmt · snapshot
├── src/hosting/      GitVerse and SourceCraft clients and their CLI
├── src/rutube/       Rutube client and CLI
├── src/labrelease/   lab on camera: publish · answer · lab · cli
├── skills/           agent skills, copied out by study agent
├── docs/             documentation; agent.md is the agent instruction block,
│                     AGENTS.md only the 1.x → 2.0 bridge
├── tests/            unittest; fixtures/ hold TUIS replies and the reference digest
└── install.py        installer: dependencies, clone, then study setup
```

`study` never imports `hosting`, `rutube` or `labrelease`. All network calls go through
`src/kit/net.py`; each API's quirks stay inside its client, each `cli.py` only parses and prints.

## Where to change what

| Change | Where |
|--------|-------|
| digest layout | `src/study/digest.py`, `render` |
| a new TUIS data source | `src/study/moodle.py`, `digest.py`, a row in `docs/tuis-api.md` |
| a new code hosting | a class in `src/hosting/client.py`, `docs/hosting-api.md` |
| agent rules / scenarios | `docs/agent.md` / `skills/<skill>/`, then `study agent <operator>` |
| a new AI operator | `OPERATORS` in `src/study/agent.py` |

## Rules

- Standard library only; Python 3.8 syntax (no `match`, `X | Y` annotations, `removeprefix`,
  `dict | dict`, `zip(strict=)`).
- No comments or docstrings — explanations go into names, commits and `docs/`; every
  `open`/`read_text`/`write_text` names `encoding=`. `tests/test_style.py` enforces both.
- Tests never touch the network: `tests/__init__.py` makes `urlopen` fail, network tests put
  `tests/fakes.py: FakeNet` over `net.send` (a queue of replies matched by method and URL or form
  substrings, plus a log of everything sent). Git is either a stubbed map or a temporary
  repository. Tests that write course files patch `ROOT` with a temporary directory.
- Time is fixed with `fakes.NOW`; the digest prints Moscow time on any machine.
- Conventional Commits, GPG-signed; versions are signed `vX.Y.Z` tags with GitHub Releases.
