#!/usr/bin/env bash
# Bring up Postgres, load schema, seed data. Idempotent.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "→ Starting postgres (docker)..."
docker compose up -d

echo "→ Waiting for postgres to be ready..."
for i in {1..30}; do
  if docker compose exec -T postgres pg_isready -U banking -d banking >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "→ Loading schema..."
docker compose exec -T postgres psql -U banking -d banking < app/db/schema.sql

echo "→ Seeding data..."
python -m app.db.seed

echo "→ Done. Verify with:"
echo "    psql postgresql://banking:banking@localhost:5433/banking -c 'SELECT * FROM v_table_counts ORDER BY table_name;'"
