# dosing-monitoring-system

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch, commit and pull request convention.

`legacy/` holds the previous prototype (backend, frontend, sandbox and early project notes). It is kept as reference only and is excluded from linting, type checking, tests and import contracts. New code lives in `src/dms/`.

## Python and tooling

Python 3.14, the system interpreter of Ubuntu 26.04. Release 1.0 is installed natively on an offline machine, so building on the system Python avoids shipping a separate interpreter. `requires-python` has an upper bound on purpose: moving to 3.15 is a deliberate change.

```bash
uv sync
make check
```

`make check` runs, in order: formatting check (ruff), lint (ruff), type check (mypy, strict), import contracts (import-linter, `.importlinter`) and tests (pytest). Run `make check`, not just `pytest`, before opening a pull request; import contracts are not part of the test suite.

CI (GitHub Actions, `.github/workflows/ci.yml`) runs `make check` on every pull request and on every push to `main`. Merging into `main` requires a green CI run.

| Target | Runs |
|---|---|
| `make format` | `ruff format` and `ruff check --fix` |
| `make lint` | `ruff check` |
| `make typecheck` | `mypy` |
| `make imports` | `lint-imports` |
| `make test` | all tests |
| `make test-unit`, `make test-integration`, `make test-e2e` | tests of one level |
| `make coverage` | tests with a coverage report |

Pass extra pytest arguments through `ARGS`, e.g. `make test-unit ARGS='-k parser'`. Tests get their level marker (`unit`, `integration`, `e2e`) from their directory under `tests/`.

## Development environment

Target system: Ubuntu 26.04 (the same as the production thin client). PostgreSQL is not installed locally; it runs in containers (see [Database](#database)).

### uv

Installed per user into `~/.local/bin`, no `sudo`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Docker Engine and GitHub CLI

Docker Engine from Docker's apt repository (no Docker Desktop) and `gh` from the GitHub CLI apt repository. Run as root from your user account (`sudo bash install.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_USER="${SUDO_USER:?run with sudo from your user account}"

apt-get update
apt-get install -y ca-certificates curl wget

install -m 0755 -d /etc/apt/keyrings

curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF

wget -nv -O /etc/apt/keyrings/githubcli-archive-keyring.gpg https://cli.github.com/packages/githubcli-archive-keyring.gpg
chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  > /etc/apt/sources.list.d/github-cli.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin gh

usermod -aG docker "$TARGET_USER"
```

The script adds you to the `docker` group, which lets you run Docker without `sudo` but is effectively root access on the machine. Log out and back in (or reboot) for the group to apply, then check:

```bash
docker run --rm hello-world
```

### GitHub CLI login

```bash
gh auth login
gh auth status
```

Choose GitHub.com and SSH as the git protocol. Log in through the browser or with a personal access token (scopes `repo`, `read:org`, `admin:public_key`). A token with an expiry date requires logging in again once it expires.

### PostgreSQL check

Use the major version packaged in Ubuntu 26.04 (`apt-cache policy postgresql` shows 18):

```bash
docker run -d --rm --name pg-check -e POSTGRES_PASSWORD=test -p 5432:5432 postgres:18
docker exec pg-check pg_isready -U postgres -h localhost
docker exec pg-check psql -U postgres -c "select version();"
docker stop pg-check
```

`pg_isready` may report `no response` for a few seconds while the server starts.

## Database

PostgreSQL 18. The database is set up by plain SQL files in `scripts/db/`, run by `psql` in development and by `psycopg` in tests:

- `roles.sql` creates the roles; running it again changes nothing. Roles are shared by the whole server.
- `database.sql` runs inside a freshly created database: it limits `CONNECT` to the DMS roles and creates the `dms` schema owned by `dms_owner`.

| Role | Login | Purpose |
|---|---|---|
| `dms_owner` | yes | owns the `dms` schema; used only by `dms-migrate` |
| `dms_writer` | yes | acquisition service; writes data, no DDL |
| `dms_read` | no | group with read access |
| `dms_api` | yes | API; member of `dms_read` |

Table privileges are granted by migrations. `roles.sql` sets no passwords.

### Development database

```bash
scripts/db-reset.sh
```

Starts the container `dms-dev-pg` (image `postgres:18`, data in the volume `dms-dev-pg-data`, port `5432` on `127.0.0.1` only) or reuses it if it already exists, then drops and recreates the database `dms`. Run it the first time and whenever you want a clean database; roles survive a reset.

Development passwords, for this container only: superuser `postgres` / `postgres`, roles `dms_owner`, `dms_writer` and `dms_api` / `dms`.

```bash
docker exec -it dms-dev-pg psql -U postgres -d dms
```

### Integration tests

Integration tests need Docker: testcontainers starts one `postgres:18` container per test session. Each session creates its own database `dms_test_<random>` and drops it at the end.

Without Docker, point the tests at an existing server with a superuser account:

```bash
DMS_TEST_PG_URL=postgresql://postgres:postgres@localhost:5432/postgres make test-integration
```

The tests then use that server instead of a container. They still work in their own `dms_test_*` database, so the development database `dms` is left untouched; roles are created there if missing.

## Configuration and logging

Services read TOML files from `DMS_CONFIG_DIR` (default `/etc/dms`): `shared.toml` (`[database]`, `[logging]`) and `acquisition.toml` (`[engine]`, `[[meters]]`, `[[silos]]`). Unknown fields are rejected, and all errors found in a file are reported together, each with the path of the field. The database password is never in these files; libpq reads it from `PGPASSWORD`.

Logs are structured (structlog). `format = "auto"` prints a human-readable console format on a terminal and JSON otherwise; standard library logs go through the same renderer. Event names are listed in [docs/log-events.md](docs/log-events.md).
