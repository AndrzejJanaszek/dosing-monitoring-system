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

Target system: Ubuntu 26.04 (the same as the production thin client). PostgreSQL is not installed locally; tests run it in containers (testcontainers).

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
