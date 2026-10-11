# Contributing

This convention applies to `dosing-monitoring-system` and `dms-arduino`.

Work is tracked in Jira. Every change belongs to a ticket, and the ticket key (e.g. `INZ-22`) links the code to it. Tickets are written in Polish; branches, commits and pull requests are in English.

## Branches

- Name: ticket key + short description, separated by hyphens, no type prefix (`feat/`, `chore/`, ...).
- Branch off `main`.

```
INZ-22-walking-skeleton
```

## Commits

- [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `type(scope): description`.
- Ticket key in the footer: `Refs: INZ-22`.
- AI-assisted commits end with a `Co-Authored-By:` trailer naming the model.

```
feat(acquisition): add meter frame parser

Refs: INZ-22
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

## Pull requests

- Keep pull requests small: one iteration, easy to review in one sitting. A larger ticket is split into several pull requests rather than delivered in one.
- Usually one pull request belongs to one ticket. When it covers several, the title and the `Refs:` footer list all their keys.
- Title starts with the ticket key: `INZ-22: Walking skeleton – meter frame parser`.
- Merged with **squash merge**, so each pull request becomes a single commit on `main`. The squash commit message follows the commit convention above, including the `Refs:` footer.

## Code

- Names of functions, classes and variables should make the code self-explanatory; where they don't, prefer rewriting the code over explaining it in a comment. An outdated comment is worse than none.
- Comments are rare and added deliberately by a human. AI-generated code contains no comments or docstrings, including tool suppressions such as `# noqa` and `# type: ignore`; rule exceptions for whole files go to `pyproject.toml`.
- No magic numbers: give numeric constants a name. Tests may use literal values where a name would add nothing. Ruff's `PLR2004` enforces this only for comparisons, so the rest is up to the author and the reviewer.
- Run `make check` before opening a pull request.
