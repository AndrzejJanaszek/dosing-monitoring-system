#!/usr/bin/env bash
set -euo pipefail

CONTAINER=dms-dev-pg
VOLUME=dms-dev-pg-data
IMAGE=postgres:18
HOST_PORT=5432
SUPERUSER_PASSWORD=postgres
ROLE_PASSWORD=dms
DATABASE=dms
READY_ATTEMPTS=30

SQL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/db"

psql_in_container() {
    docker exec -i "$CONTAINER" psql --username postgres --no-psqlrc --quiet -v ON_ERROR_STOP=1 "$@"
}

running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
if [[ -z "$running" ]]; then
    docker run --detach --name "$CONTAINER" \
        --env POSTGRES_PASSWORD="$SUPERUSER_PASSWORD" \
        --volume "$VOLUME":/var/lib/postgresql \
        --publish "127.0.0.1:$HOST_PORT:5432" \
        "$IMAGE" > /dev/null
elif [[ "$running" == false ]]; then
    docker start "$CONTAINER" > /dev/null
fi

for ((attempt = 1; ; attempt++)); do
    if docker exec "$CONTAINER" pg_isready --username postgres --host localhost --quiet; then
        break
    fi
    if ((attempt >= READY_ATTEMPTS)); then
        echo "PostgreSQL in $CONTAINER is not ready after $READY_ATTEMPTS s" >&2
        exit 1
    fi
    sleep 1
done

psql_in_container --dbname postgres < "$SQL_DIR/roles.sql"
psql_in_container --dbname postgres \
    -c "ALTER ROLE dms_owner PASSWORD '$ROLE_PASSWORD'" \
    -c "ALTER ROLE dms_writer PASSWORD '$ROLE_PASSWORD'" \
    -c "ALTER ROLE dms_api PASSWORD '$ROLE_PASSWORD'" \
    -c "DROP DATABASE IF EXISTS $DATABASE WITH (FORCE)" \
    -c "CREATE DATABASE $DATABASE"
psql_in_container --dbname "$DATABASE" < "$SQL_DIR/database.sql"

echo "Database $DATABASE is ready at localhost:$HOST_PORT"
