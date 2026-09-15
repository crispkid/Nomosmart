#!/usr/bin/env bash
# Reuse a dependency image; mount current source/tests read-only. No image build.
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
test_packages="$repo_dir/backend/.venv/lib/python3.12/site-packages"
mounts=()
for package in pytest _pytest pluggy iniconfig packaging pygments; do
  test -d "$test_packages/$package"
  mounts+=(-v "$test_packages/$package:/opt/test-deps/$package:ro")
done
mounts+=(-v "$test_packages/py.py:/opt/test-deps/py.py:ro")
docker run --rm --name chg293-test-runner --label nomosmart.change=CHG-293 \
  --network chg293-test-20260910 --entrypoint python \
  -e APP_ENV=test -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/workspace/backend:/opt/test-deps \
  -e CHG293_DATABASE_URL=postgresql+psycopg2://postgres@chg293-postgres-20260910/chg293_test \
  -e CHG293_KEYCLOAK_URL=http://chg293-keycloak-20260910:8080 \
  -e CHG293_KEYCLOAK_ADMIN=chg293-test -e CHG293_KEYCLOAK_PASSWORD=chg293-disposable-only \
  -v "$repo_dir/backend/app:/workspace/backend/app:ro" \
  -v "$repo_dir/backend/tests:/workspace/backend/tests:ro" \
  -v "$repo_dir/sql/migrations:/workspace/sql/migrations:ro" \
  "${mounts[@]}" -w /workspace nomosmart/backend:0.1.0-chg292 \
  -m pytest -c /dev/null --rootdir=/workspace -p no:cacheprovider --tb=short -q \
  backend/tests/test_chg293_project_content_and_chat_history.py "$@"
