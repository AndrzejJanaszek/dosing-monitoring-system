# Contributing

This convention applies to `dosing-monitoring-system` and `dms-arduino`.

Branches, commits and pull requests are in English.

## Branches

- Name: Conventional Commits type + short description in kebab-case, separated by a slash.
- Branch off `main`.

```
feat/arduino-signal-input
fix/writer-reconnect
docs/contributing
```

## Commits

- [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `type(scope): description`.
- AI-assisted commits end with a `Co-Authored-By:` trailer naming the model.

```
feat(acquisition): add meter frame parser

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

## Pull requests

- Keep pull requests small: one step of the work, easy to review in one sitting. A larger change is split into several pull requests rather than delivered in one.
- Title follows the commit convention: `feat(acquisition): add meter frame parser`.
- Merged with **squash merge**, so each pull request becomes a single commit on `main`. The squash commit message follows the commit convention above.

## Code

- Names of functions, classes and variables should make the code self-explanatory; where they don't, prefer rewriting the code over explaining it in a comment. An outdated comment is worse than none.
- Comments are rare and added deliberately by a human. AI-generated code contains no comments or docstrings, including tool suppressions such as `# noqa` and `# type: ignore`; rule exceptions for whole files go to `pyproject.toml`.
- No magic numbers: give numeric constants a name. Tests may use literal values where a name would add nothing. Ruff's `PLR2004` enforces this only for comparisons, so the rest is up to the author and the reviewer.
- Run `make check` before opening a pull request.
