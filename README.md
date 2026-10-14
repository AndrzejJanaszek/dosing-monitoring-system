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

Services read TOML files from `DMS_CONFIG_DIR` (default `/etc/dms`): `shared.toml` (`[database]`, `[logging]`) and `acquisition.toml` (`[engine]`, `[[meters]]`, `[[silos]]`, optional `[board]` and `[[tanks]]`). Unknown fields are rejected, and all errors found in a file are reported together, each with the path of the field. The database password is never in these files; libpq reads it from `PGPASSWORD`.

`[board]` describes the Arduino signal module (a serial port like a meter's) and `[[tanks]]` assign its pins to tank signals: `dispense = { pin = 4, active_level = 0 }` means the tank dispenses while pin 4 reads 0. `active_level` is mandatory, `0` or `1`; a pin can be assigned once; a silo has at most two tanks; tanks need `[board]`. A silo without tanks is allowed. `max_frame_length` (optional, in `[[meters]]` and `[board]`; defaults 64 and 512 bytes) caps the length of one frame; longer ones are dropped and counted as garbage. A tank `id` is never reused for another tank, and a tank never moves to another silo: startup is refused (`catalog.identity_violation`) when the database knows the tank under a different silo. Tanks removed from the file stay in `dms.tank` as inactive.

Logs are structured (structlog). `format = "auto"` prints a human-readable console format on a terminal and JSON otherwise; standard library logs go through the same renderer. Event names are listed in [docs/log-events.md](docs/log-events.md).

## Migrations

`dms-migrate` applies the SQL files from `src/dms/persistence/migrations/` as role `dms_owner`. Each file runs in its own transaction together with its row in `dms.schema_migration`. It refuses to run when an applied file changed (checksum) or when the database has migrations the package does not know. The first line of every file declares the change: `-- schema-change: major|minor|patch`; the schema version is computed from these headers.

On the development database (see [Development database](#development-database)):

```bash
PGPASSWORD=dms DMS_CONFIG_DIR=config/example uv run dms-migrate
```


## Running acquisition locally

The acquisition service reads a meter on a serial port and stores one reading per second per silo in `dms.meter_reading`. It also reads the Arduino signal module on a second port and logs every change of a tank signal (`signal.changed`); events are not derived from the signals yet. Without hardware, `dms-simulator` plays a named scenario on pseudo-terminals: one for the Dini Argeo DGTP meter of each silo and one for the Arduino signal module.

```bash
scripts/db-reset.sh
export PGPASSWORD=dms DMS_CONFIG_DIR=config/example
uv run dms-migrate
uv run dms-simulator run dispense-single --link-dir /tmp/dms --wait
```

In a second terminal start the service (`export PGPASSWORD=dms DMS_CONFIG_DIR=config/example` first), then press Enter in the first one to start the scenario:

```bash
uv run dms-acquisition
```

`config/example/` points at the development database, at `/tmp/dms/meter-1` and at `/tmp/dms/arduino`, the links that `dms-simulator run <scenario> --link-dir /tmp/dms` creates for the meter of silo 1 and for the Arduino module. Without `--wait` the scenario starts immediately; the simulator sends the resting state until then and holds the final state after the scenario ends, until `Ctrl+C`. Like a real serial device, a port only carries frames while something has it open: nothing piles up for a reader that connects later, and the Arduino port sends its startup banner on every new connection, as the board does after the reset on port open. `dms-simulator list` shows the scenarios and `dms-simulator config <scenario> --link-dir DIR` prints the `acquisition.toml` that matches a scenario's layout. In a third terminal:

```bash
docker exec -it dms-dev-pg psql -U postgres -d dms -c "SELECT * FROM dms.meter_reading ORDER BY t DESC LIMIT 5"
```

Stop the service with `Ctrl+C` or `SIGTERM`; it finishes writing queued readings and sets `stopped_at` on its row in `dms.run`. If the database is unreachable at that moment, the queued readings are dropped after one last attempt (`writer.abandoned`) and `stopped_at` stays empty.

### Simulator scenarios

A scenario (`src/dms/simulator/scenario.py`) is a plant layout (silos, tanks, signal module pins and polarity, meters), the starting masses and a list of `Dispense`/`Refill` events on tanks. The meter readings and the Arduino pin states are both computed from the same events, so the frames are consistent. The catalog is `src/dms/simulator/catalog.py`; to add a scenario, add it to the list passed to `build_catalog` there (or to one of the helper groups in that list).

Scenarios describe only normal operation (golden flow). A scenario is validated when it is built: physically impossible or abnormal definitions (overlapping events of the same type, a dispense that empties the silo, durations or rates outside the normal range, an event during the initial quiet period, and so on) raise `ScenarioError` listing every problem, so such a scenario cannot be run and the catalog does not import.

| Exit code of `dms-acquisition` | Meaning |
|---|---|
| 0 | clean shutdown |
| 1 | startup failed (database unreachable, schema incompatible, a tank moved to another silo), a thread crashed, or the shutdown lost readings or could not set `stopped_at` |
| 2 | configuration invalid; all errors are printed |

A meter or the Arduino module that is unplugged or silent does not stop the service: the port is reopened every `reconnect_delay_s`, and no reading is stored while there is none.

The frame format of the Arduino module is provisional: only `src/dms/acquisition/arduino/frames.py` knows it, and it will be rewritten after the firmware changes.
