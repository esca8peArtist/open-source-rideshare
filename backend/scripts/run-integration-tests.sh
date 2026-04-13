#!/bin/bash
set -e

echo "Starting test infrastructure..."
docker compose -f docker-compose.test.yml up -d --wait

echo "Running integration tests..."
OPENRIDE_TEST_DATABASE_URL="postgresql+asyncpg://openride_test:openride_test@localhost:5433/openride_test" \
  python -m pytest tests/integration/ -v --tb=short "$@"

echo "Tearing down test infrastructure..."
docker compose -f docker-compose.test.yml down -v
