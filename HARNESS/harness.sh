#!/usr/bin/env bash
set -euo pipefail

HARNESS_SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${NOMOSMART_HARNESS_ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

python_bin() {
  if [[ -n "${NOMOSMART_PYTHON:-}" ]]; then
    [[ "$NOMOSMART_PYTHON" = /* && -x "$NOMOSMART_PYTHON" ]] || { echo "NOMOSMART_PYTHON must be an absolute executable path." >&2; return 64; }
    printf '%s\n' "$NOMOSMART_PYTHON"
  elif [[ -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
    printf '%s\n' "$ROOT_DIR/backend/.venv/bin/python"
  elif [[ -x "$ROOT_DIR/backend/venv/bin/python" ]]; then
    printf '%s\n' "$ROOT_DIR/backend/venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    echo "Python is required but no python executable was found." >&2
    exit 127
  fi
}

run() {
  echo "+ $*"
  "$@"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 127
  fi
}

live_policy_guard() {
  section "TEST-002 live-only policy guard"
  local paths=("$@")
  if [[ "${#paths[@]}" -eq 0 ]]; then
    paths=(backend/tests frontend/tests)
  fi

  local expressions=(
    -e 'from unittest\.mock' \
    -e '\bMagicMock\b' \
    -e '\bMockTransport\b' \
    -e '\bvi\.(useFakeTimers|advanceTimersByTimeAsync|advanceTimersByTime|runAllTimers)\b' \
    -e '\bvi\.spyOn\(window, "matchMedia"\)' \
    -e 'Object\.defineProperty\(window, "(localStorage|matchMedia)"' \
    -e 'Object\.defineProperty\(Element\.prototype, "scrollTo"' \
    -e '^class ResizeObserver *\{' \
    -e '\bmonkeypatch\.setattr\b' \
    -e '\bmonkeypatch\.setitem\b' \
    -e '\bclass Fake[A-Za-z0-9_]*' \
    -e '\bdef fake_[A-Za-z0-9_]*' \
    -e '\bconst fake[A-Za-z0-9_]*' \
    -e '\blet fake[A-Za-z0-9_]*' \
    -e '\bfixture success\b' \
    -e '\bloginFixture\b' \
    -e '\bLoginFixture\b' \
    -e '\bfixtureData\b' \
    -e '@/lib/fixtures' \
    -e 'Fixture fallback' \
    -e '\bmocked OIDC\b' \
    -e '\bstatic-smoke\b'
  )
  local output
  local status
  set +e
  if command -v rg >/dev/null 2>&1; then
    output="$(cd "$ROOT_DIR" && rg -n "${expressions[@]}" "${paths[@]}")"
    status=$?
  else
    output="$("$(python_bin)" "$HARNESS_SOURCE_DIR/scripts/live_policy_scan.py" --root "$ROOT_DIR" "${expressions[@]}" "${paths[@]}")"
    status=$?
  fi
  set -e

  if [[ "$status" -eq 0 ]]; then
    echo "TEST-002 violation: behavioral test suites contain mock/fake/monkeypatch/test-double patterns." >&2
    echo "Refactor these tests to real configured development/test services, or move static-only hygiene checks outside behavioral test commands." >&2
    printf '%s\n' "$output" >&2
    exit 1
  fi

  if [[ "$status" -eq 1 ]]; then
    echo "ok: no obvious mock/fake/test-double patterns found in behavioral test suites"
    return 0
  fi

  echo "Source scan failed while checking TEST-002 live-only policy." >&2
  exit "$status"
}

section() {
  printf '\n== %s ==\n' "$1"
}

require_dir() {
  if [[ ! -d "$ROOT_DIR/$1" ]]; then
    echo "Missing required directory: $1" >&2
    exit 1
  fi
}

active_change_id() {
  local changelog="$ROOT_DIR/SPEC_CHANGELOG.md"
  local change_id
  if [[ ! -f "$changelog" ]]; then
    echo "Missing SPEC_CHANGELOG.md; active change cannot be determined." >&2
    exit 1
  fi
  change_id="$(awk -F'|' '
    /^\|[[:space:]]*[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9][[:space:]]*\|/ {
      value=$3
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      print value
      exit
    }
  ' "$changelog")"
  if [[ ! "$change_id" =~ ^CHG-[0-9]+$ ]]; then
    echo "SPEC_CHANGELOG.md first change row must contain a valid CHG-NNN active change ID." >&2
    exit 1
  fi
  printf '%s\n' "$change_id"
}

extract_change_section() {
  local change_id="$1"
  local file="$2"
  awk -v change_id="$change_id" '
    $0 ~ "^##[[:space:]]+" change_id "([[:space:]]|$)" {
      active=1
      found=1
    }
    active && found && $0 ~ "^##[[:space:]]+" && $0 !~ "^##[[:space:]]+" change_id "([[:space:]]|$)" {
      exit
    }
    active { print }
  ' "$file"
}

require_active_change_reference() {
  local change_id="$1"
  local file="$2"
  if ! grep -Fq "$change_id" "$file"; then
    echo "$file does not reference active change $change_id." >&2
    exit 1
  fi
}

repo_doctor() {
  section "Repository doctor"
  require_dir "frontend"
  require_dir "backend"
  require_dir "sql"

  if [[ -d "$ROOT_DIR/frontend/node_modules" ]]; then
    echo "note: frontend/node_modules exists; harness checks ignore dependency source."
  fi
  if [[ -d "$ROOT_DIR/frontend/.next" ]]; then
    echo "note: frontend/.next exists; remove it if you need a clean production build."
  fi
  if [[ -d "$ROOT_DIR/backend/venv" ]]; then
    echo "note: backend/venv exists; harness does not inspect virtualenv files."
  fi
  if [[ -d "$ROOT_DIR/backend/.venv" ]]; then
    echo "note: backend/.venv exists; harness does not inspect virtualenv files."
  fi
  if [[ -d "$ROOT_DIR/backend/tests_legacy_mocked" ]]; then
    echo "backend/tests_legacy_mocked must not be reintroduced after CLEAN-001." >&2
    exit 1
  fi
  if [[ -f "$ROOT_DIR/frontend/src/lib/fixtures.ts" ]]; then
    echo "frontend fixture fallback must not be reintroduced after CLEAN-001." >&2
    exit 1
  fi
  if [[ -d "$ROOT_DIR/output" ]]; then
    echo "Generated browser output must not be kept in the repository root." >&2
    exit 1
  fi
}

spec_doctor() {
  section "Specification doctor"
  if [[ ! -f "$ROOT_DIR/SPECIFICATION.md" ]]; then
    echo "Missing SPECIFICATION.md." >&2
    exit 1
  fi
  if [[ ! -f "$ROOT_DIR/AGENTS.md" ]]; then
    echo "Missing AGENTS.md." >&2
    exit 1
  fi
  if [[ ! -f "$ROOT_DIR/HARNESS/HARNESS.md" ]]; then
    echo "Missing HARNESS/HARNESS.md." >&2
    exit 1
  fi
  if [[ ! -f "$ROOT_DIR/TEST_PLAN.md" ]]; then
    echo "Missing TEST_PLAN.md." >&2
    exit 1
  fi
  if [[ ! -f "$ROOT_DIR/DEVELOPMENT_PLAN.md" ]]; then
    echo "Missing DEVELOPMENT_PLAN.md." >&2
    exit 1
  fi
  if [[ ! -f "$ROOT_DIR/TRACEABILITY.md" ]]; then
    echo "Missing TRACEABILITY.md." >&2
    exit 1
  fi
  if [[ ! -f "$ROOT_DIR/SPEC_CHANGELOG.md" ]]; then
    echo "Missing SPEC_CHANGELOG.md." >&2
    exit 1
  fi
  if grep -Eq '規格|specification|Specification' "$ROOT_DIR/SPECIFICATION.md"; then
    echo "ok: SPECIFICATION.md found"
  else
    echo "SPECIFICATION.md should describe the product specification baseline." >&2
    exit 1
  fi
  if grep -Eq '80%' "$ROOT_DIR/TEST_PLAN.md"; then
    echo "ok: TEST_PLAN.md includes the 80% advisory improvement target"
  else
    echo "TEST_PLAN.md must include the 80% advisory improvement target." >&2
    exit 1
  fi
  if grep -Eqi 'specification-driven|規格驅動' "$ROOT_DIR/AGENTS.md" "$ROOT_DIR/HARNESS/HARNESS.md"; then
    echo "ok: VIBECODING workflow documents mention specification-driven development"
  else
    echo "VIBECODING workflow documents must mention specification-driven development." >&2
    exit 1
  fi
  local change_id
  change_id="$(active_change_id)"
  require_active_change_reference "$change_id" "$ROOT_DIR/SPECIFICATION.md"
  echo "ok: active specification change is $change_id"
}

extract_field_value() {
  local label="$1"
  local file="$2"
  grep -E "^[[:space:]]*-[[:space:]]*$label:" "$file" | head -n 1 | sed -E "s/^[[:space:]]*-[[:space:]]*$label:[[:space:]]*//"
}

require_filled_field() {
  local label="$1"
  local file="$2"
  local value
  value="$(extract_field_value "$label" "$file")"
  if [[ -z "$value" || "$value" =~ ^(TBD|TODO|PENDING|N/A|NA|None|未定|待確認|待核准)$ ]]; then
    echo "DEVELOPMENT_PLAN.md must fill '$label' before this gate passes." >&2
    exit 1
  fi
}

plan_doctor() {
  section "Development plan doctor"
  if [[ ! -f "$ROOT_DIR/DEVELOPMENT_PLAN.md" ]]; then
    echo "Missing DEVELOPMENT_PLAN.md." >&2
    exit 1
  fi
  for required in \
    "Specification Understanding" \
    "Discussion and Confirmation Items" \
    "Human Confirmation" \
    "Development Plan" \
    "Plan Approval" \
    "Verification Results"; do
    if ! grep -Eq "$required" "$ROOT_DIR/DEVELOPMENT_PLAN.md"; then
      echo "DEVELOPMENT_PLAN.md is missing required section: $required" >&2
      exit 1
    fi
  done
  if grep -Eqi 'must not begin|may begin only after|human' "$ROOT_DIR/DEVELOPMENT_PLAN.md"; then
    echo "ok: DEVELOPMENT_PLAN.md includes human confirmation gates"
  else
    echo "DEVELOPMENT_PLAN.md must explicitly require human confirmation before implementation." >&2
    exit 1
  fi
  local change_id
  local section_text
  change_id="$(active_change_id)"
  section_text="$(extract_change_section "$change_id" "$ROOT_DIR/DEVELOPMENT_PLAN.md")"
  if [[ -z "$section_text" ]]; then
    echo "DEVELOPMENT_PLAN.md is missing an active plan section headed by $change_id." >&2
    exit 1
  fi
  if ! grep -Eqi 'Status and Gate|Status|Gate' <<<"$section_text"; then
    echo "Active plan section $change_id must state its gate status." >&2
    exit 1
  fi
  echo "ok: active development plan section is $change_id"
}

plan_approved() {
  section "Development plan approval"
  local plan="$ROOT_DIR/DEVELOPMENT_PLAN.md"
  if [[ ! -f "$plan" ]]; then
    echo "Missing DEVELOPMENT_PLAN.md." >&2
    exit 1
  fi
  plan_doctor
  local change_id
  local section_text
  local changelog_row
  local gate4_status_line
  change_id="$(active_change_id)"
  section_text="$(extract_change_section "$change_id" "$plan")"
  changelog_row="$(grep -Fm1 "| $change_id |" "$ROOT_DIR/SPEC_CHANGELOG.md")"
  gate4_status_line="$(
    grep -Eim1 \
      'Gate 4([[:space:]]+implementation)?[[:space:]]+approval:|Gate 4 (is|was|remains)' \
      <<<"$section_text" || true
  )"

  if [[ -z "$gate4_status_line" ]]; then
    echo "Active plan $change_id must include a canonical Gate 4 status line." >&2
    exit 1
  fi
  if grep -Eqi '(pending|待核准)' <<<"$gate4_status_line"; then
    echo "Active plan $change_id still marks Gate 4 as pending." >&2
    exit 1
  fi
  if ! grep -Eqi 'Gate 2.*(complete|confirmed|approved)' <<<"$section_text"; then
    echo "Active plan $change_id must record completed human understanding confirmation." >&2
    exit 1
  fi
  if ! grep -Eqi '(complete|approved)' <<<"$gate4_status_line"; then
    echo "Active plan $change_id must record explicit Gate 4 approval." >&2
    exit 1
  fi
  if ! grep -Eqi 'approved Gate 4 on[[:space:]]+[0-9]{4}-[0-9]{2}-[0-9]{2}' <<<"$section_text"; then
    echo "Active plan $change_id must record approver and approval date in its own section." >&2
    exit 1
  fi
  if ! grep -Eqi 'Gate 4 approved' <<<"$changelog_row"; then
    echo "SPEC_CHANGELOG.md active row $change_id must record Gate 4 approval." >&2
    exit 1
  fi
  echo "ok: active development plan $change_id has explicit Gate 2 and Gate 4 approval"
}

spec_trace() {
  section "Specification traceability"
  if [[ ! -f "$ROOT_DIR/TRACEABILITY.md" ]]; then
    echo "Missing TRACEABILITY.md. Add a requirement-to-test traceability matrix during the rewrite." >&2
    exit 1
  fi
  for required in "Requirement ID" "Specification Section" "Implementation Area" "Tests" "Harness Command" "Status"; do
    if ! grep -Eiq "$required" "$ROOT_DIR/TRACEABILITY.md"; then
      echo "TRACEABILITY.md is missing required traceability field: $required" >&2
      exit 1
    fi
  done
  local change_id
  local file
  change_id="$(active_change_id)"
  for file in SPECIFICATION.md SPEC_CHANGELOG.md DEVELOPMENT_PLAN.md TEST_PLAN.md TRACEABILITY.md; do
    require_active_change_reference "$change_id" "$ROOT_DIR/$file"
  done
  if grep -F "$change_id" "$ROOT_DIR/SPEC_CHANGELOG.md" | head -n 1 | grep -Eqi 'Gate 4 approved'; then
    if grep -F "$change_id" "$ROOT_DIR/TRACEABILITY.md" | grep -Eqi 'Gate 4 pending'; then
      echo "TRACEABILITY.md contradicts the approved Gate 4 state for $change_id." >&2
      exit 1
    fi
  fi
  if grep -Fq 'API-COMPAT-001' "$ROOT_DIR/SPECIFICATION.md" && [[ ! -f "$ROOT_DIR/API_COMPATIBILITY.md" ]]; then
    echo "API_COMPATIBILITY.md is required by API-COMPAT-001." >&2
    exit 1
  fi
  run "$(python_bin)" "$HARNESS_SOURCE_DIR/scripts/spec_trace.py" "$ROOT_DIR"
  echo "ok: active change $change_id is referenced by specification, plan, test plan and traceability"
}

frontend_lint() {
  section "Frontend lint"
  cd "$ROOT_DIR/frontend"
  run npm run lint
}

frontend_build() {
  section "Frontend build"
  cd "$ROOT_DIR/frontend"
  run npm run build
}

backend_syntax() {
  section "Backend syntax"
  cd "$ROOT_DIR/backend"
  run "$(python_bin)" -m compileall -q main.py models.py connection.py migrate.py app tests scripts
}

backend_import() {
  section "Backend import"
  cd "$ROOT_DIR/backend"
  run "$(python_bin)" -c "import main; print(main.app.title)"
}

test_plan() {
  section "Test plan"
  if [[ ! -f "$ROOT_DIR/TEST_PLAN.md" ]]; then
    echo "Missing TEST_PLAN.md." >&2
    exit 1
  fi
  if grep -Eq '80%' "$ROOT_DIR/TEST_PLAN.md"; then
    echo "ok: TEST_PLAN.md defines the 80% advisory improvement target"
  else
    echo "TEST_PLAN.md must define the 80% advisory improvement target." >&2
    exit 1
  fi
  local change_id
  change_id="$(active_change_id)"
  require_active_change_reference "$change_id" "$ROOT_DIR/TEST_PLAN.md"
  echo "ok: TEST_PLAN.md covers active change $change_id"
}

frontend_test() {
  section "Frontend tests"
  live_policy_guard frontend/tests
  cd "$ROOT_DIR/frontend"
  if node -e "const scripts=require('./package.json').scripts||{}; process.exit(scripts['test:coverage'] ? 0 : 1)"; then
    local started_at
    started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    run npm run test:coverage
    run "$(python_bin)" "$HARNESS_SOURCE_DIR/scripts/coverage_evidence.py" record \
      --root "$ROOT_DIR" --suite frontend --command "npm run test:coverage" \
      --started-at "$started_at"
  elif node -e "const scripts=require('./package.json').scripts||{}; process.exit(scripts.test ? 0 : 1)"; then
    run npm run test
  else
    echo "Missing frontend npm test script. Add it before running test:frontend." >&2
    exit 1
  fi
}

i18n_hardcoded() {
  section "I18N hard-coded visible text"
  require_command rg

  local output
  local status
  set +e
  output="$(cd "$ROOT_DIR" && rg -n '[一-龥]' frontend/src/app frontend/src/components --glob '!frontend/src/i18n/**')"
  status=$?
  set -e

  if [[ "$status" -eq 0 ]]; then
    echo "Found Traditional Chinese literals outside locale files. Move user-visible text into i18n locales or document an allowlist decision." >&2
    printf '%s\n' "$output" >&2
    exit 1
  fi

  if [[ "$status" -eq 1 ]]; then
    echo "ok: no Traditional Chinese literals found in frontend app/components outside locale files"
    return 0
  fi

  echo "rg failed while scanning frontend i18n coverage." >&2
  exit "$status"
}

i18n_ast() {
  section "I18N AST visible-copy and locale guard"
  cd "$ROOT_DIR/frontend"
  run npm run i18n:ast
  run node --test tests/i18nGuard.test.mjs
}

backend_test() {
  section "Backend tests"
  live_policy_guard backend/tests
  cd "$ROOT_DIR/backend"
  if [[ ! -d tests ]]; then
    echo "Missing backend/tests. Add backend tests before running test:backend." >&2
    exit 1
  fi
  local started_at
  started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  # Preserve collection errors as failures, but still execute independent cases.
  # Missing historical evidence must not prevent every current regression running.
  local suite_command="python -m pytest --continue-on-collection-errors"
  if [[ -n "${NOMOSMART_TEST_GROUP_PLAN:-}" ]]; then
    suite_command="python scripts/run_test_groups.py"
    run "$(python_bin)" scripts/run_test_groups.py
  else
    run "$(python_bin)" -m pytest --continue-on-collection-errors
  fi
  run "$(python_bin)" "$HARNESS_SOURCE_DIR/scripts/coverage_evidence.py" record \
    --root "$ROOT_DIR" --suite backend --command "$suite_command" \
    --started-at "$started_at"
}

e2e_test() {
  section "End-to-end tests"
  live_policy_guard frontend/tests/e2eLive.mjs
  cd "$ROOT_DIR/frontend"
  if node -e "const scripts=require('./package.json').scripts||{}; process.exit(scripts['test:e2e'] ? 0 : 1)"; then
    run npm run test:e2e
  else
    echo "Missing frontend npm test:e2e script. Add it before running test:e2e." >&2
    exit 1
  fi
}

milestone7_live() {
  section "Milestone 7 live acceptance"
  cd "$ROOT_DIR/backend"
  run "$(python_bin)" scripts/milestone7_live_acceptance.py
}

milestone8b_live() {
  section "Milestone 8B live acceptance"
  cd "$ROOT_DIR/backend"
  run "$(python_bin)" scripts/milestone8b_live_acceptance.py
}

migration_live() {
  section "Flyway migration live acceptance"
  require_command docker
  cd "$ROOT_DIR/backend"
  run "$(python_bin)" scripts/migration_live_acceptance.py
}

coverage_strict() {
  section "Coverage check"
  live_policy_guard backend/tests frontend/tests
  run "$(python_bin)" "$HARNESS_SOURCE_DIR/scripts/coverage_evidence.py" verify \
    --root "$ROOT_DIR" --suite frontend
  run "$(python_bin)" "$HARNESS_SOURCE_DIR/scripts/coverage_evidence.py" verify \
    --root "$ROOT_DIR" --suite backend
  run "$(python_bin)" -c 'import json, pathlib, sys
threshold = 80.0
reports = []
frontend = pathlib.Path("frontend/coverage/coverage-summary.json")
backend = pathlib.Path("backend/coverage.json")
if frontend.exists():
    data = json.loads(frontend.read_text())
    for metric in ("lines", "statements", "functions", "branches"):
        reports.append((f"frontend {metric}", float(data["total"][metric]["pct"])))
else:
    print("Missing frontend/coverage/coverage-summary.json. Run ./HARNESS/harness.sh test:frontend first.", file=sys.stderr)
    sys.exit(1)
if backend.exists():
    data = json.loads(backend.read_text())
    totals = data.get("totals", {})
    statements = float(totals.get("num_statements", 0))
    branches = float(totals.get("num_branches", 0))
    line_pct = 100.0 * float(totals.get("covered_lines", 0)) / statements if statements else 100.0
    branch_pct = 100.0 * float(totals.get("covered_branches", 0)) / branches if branches else 100.0
    reports.extend((("backend lines", line_pct), ("backend branches", branch_pct)))
else:
    print("Missing backend/coverage.json. Run ./HARNESS/harness.sh test:backend first.", file=sys.stderr)
    sys.exit(1)
failed = False
for name, pct in reports:
    print(f"{name}: {pct:.2f}%")
    if pct < threshold:
        failed = True
if failed:
    print(f"Coverage must be at least {threshold:.0f}%.", file=sys.stderr)
    sys.exit(1)
print(f"ok: all available coverage reports meet {threshold:.0f}%")'
}

coverage_check() {
  section "Coverage measurement (80% advisory)"
  run "$(python_bin)" "$HARNESS_SOURCE_DIR/scripts/coverage_evidence.py" measurement --root "$ROOT_DIR"
}

release_readiness() {
  section "Risk-reviewed release readiness"
  run "$(python_bin)" "$HARNESS_SOURCE_DIR/scripts/release_quality.py" readiness --root "$ROOT_DIR"
}

coverage_evidence_selftest() {
  section "Coverage evidence self-test"
  run "$(python_bin)" "$HARNESS_SOURCE_DIR/tests/coverage_evidence.py"
}

security_simplification_test() {
  section "Mounted Secret, scanner-free upload, and password-only authentication"
  require_command helm
  cd "$ROOT_DIR"
  run env PYTHONPATH=backend "$(python_bin)" -m pytest -q -o addopts='' \
    backend/tests/test_chg247_contract_baseline.py \
    backend/tests/test_chg216_secure_async_ingestion_contract.py \
    backend/tests/test_chg232_keycloak_theme.py \
    backend/tests/test_chg260_mounted_secret_deployment.py
}

dependency_audit() {
  section "Production dependency audit"
  require_command npm
  require_command uv
  local requirements
  requirements="$(mktemp "${TMPDIR:-/tmp}/nomosmart-requirements.XXXXXX")"
  trap 'rm -f "$requirements"' RETURN

  cd "$ROOT_DIR/frontend"
  run npm audit --omit=dev
  cd "$ROOT_DIR"
  run uv export --quiet --project backend --frozen --no-dev --format requirements-txt --output-file "$requirements"
  run uvx pip-audit -r "$requirements" --disable-pip
  rm -f "$requirements"
  trap - RETURN
}

static_security_scan() {
  section "Backend and installer static security scan"
  require_command uvx
  cd "$ROOT_DIR"
  run uvx bandit -r backend/app deploy/installer/nomosmart_installer \
    deploy/release/nomosmart_release -lll -iii
}

container_images() {
  section "Production container image build"
  require_command docker
  cd "$ROOT_DIR"
  run docker build -t nomosmart-backend:local-security backend
  run docker build -t nomosmart-frontend:local-security frontend
}

container_security_scan() {
  section "Container vulnerability scan"
  require_command docker
  local output_dir="${NOMOSMART_SECURITY_OUTPUT_DIR:-$ROOT_DIR/test-results/security}"
  local backend_image="${NOMOSMART_SCAN_BACKEND_IMAGE:-local://nomosmart-backend:local-security}"
  local frontend_image="${NOMOSMART_SCAN_FRONTEND_IMAGE:-local://nomosmart-frontend:local-security}"
  mkdir -p "$output_dir"
  cd "$ROOT_DIR"
  run docker scout cves --exit-code --only-severity critical,high \
    --format sarif --output "$output_dir/backend.scout.sarif.json" \
    "$backend_image"
  run docker scout cves --exit-code --only-severity critical,high \
    --format sarif --output "$output_dir/frontend.scout.sarif.json" \
    "$frontend_image"
  test -s "$output_dir/backend.scout.sarif.json"
  test -s "$output_dir/frontend.scout.sarif.json"
  echo "ok: zero-High/Critical SARIF evidence written under test-results/security"
}

generate_sbom() {
  section "Container SBOM generation"
  require_command docker
  local output_dir="${NOMOSMART_SECURITY_OUTPUT_DIR:-$ROOT_DIR/test-results/security}"
  local backend_image="${NOMOSMART_SCAN_BACKEND_IMAGE:-local://nomosmart-backend:local-security}"
  local frontend_image="${NOMOSMART_SCAN_FRONTEND_IMAGE:-local://nomosmart-frontend:local-security}"
  mkdir -p "$output_dir"
  run docker scout sbom --format spdx --output "$output_dir/backend.spdx.json" "$backend_image"
  run docker scout sbom --format spdx --output "$output_dir/frontend.spdx.json" "$frontend_image"
  test -s "$output_dir/backend.spdx.json"
  test -s "$output_dir/frontend.spdx.json"
  echo "ok: SPDX SBOM files written under test-results/security"
}

deploy_doctor() {
  section "Deployment doctor"
  if [[ -f "$ROOT_DIR/docker-compose.yml" ]]; then
    echo "ok: docker-compose.yml found"
  else
    echo "missing: docker-compose.yml"
  fi

  if [[ -f "$ROOT_DIR/deploy/docker/nomosmart.env.example" ]]; then
    echo "ok: deploy/docker/nomosmart.env.example found"
  else
    echo "missing: deploy/docker/nomosmart.env.example"
  fi

  if [[ -f "$ROOT_DIR/deploy/helm/nomosmart/Chart.yaml" ]]; then
    echo "ok: deploy/helm/nomosmart/Chart.yaml found"
  else
    echo "missing: deploy/helm/nomosmart/Chart.yaml"
  fi
}

deploy_config_policy() {
  section "Deployment config policy"

  if [[ ! -f "$ROOT_DIR/deploy/docker/nomosmart.env.example" ]]; then
    echo "Missing deploy/docker/nomosmart.env.example." >&2
    exit 1
  fi

  if [[ -f "$ROOT_DIR/docker-compose.yml" ]]; then
    if grep -Eq 'env_file:' "$ROOT_DIR/docker-compose.yml"; then
      echo "ok: docker-compose.yml references env_file"
    else
      echo "docker-compose.yml must reference an independent env_file." >&2
      exit 1
    fi
  else
    echo "Missing docker-compose.yml." >&2
    exit 1
  fi

  if [[ ! -f "$ROOT_DIR/deploy/helm/nomosmart/Chart.yaml" ]]; then
    echo "Missing deploy/helm/nomosmart/Chart.yaml." >&2
    exit 1
  fi

  if find "$ROOT_DIR/deploy/helm/nomosmart/templates" -type f 2>/dev/null | xargs grep -El 'kind:[[:space:]]*ConfigMap' >/dev/null; then
    echo "ok: Helm chart includes a ConfigMap template"
  else
    echo "Helm chart must include a ConfigMap template for non-sensitive configuration." >&2
    exit 1
  fi

  if find "$ROOT_DIR/deploy/helm/nomosmart/templates" -type f 2>/dev/null | xargs grep -El 'kind:[[:space:]]*(Secret|ExternalSecret|SealedSecret)' >/dev/null; then
    echo "ok: Helm chart includes a Secret or external/encrypted secret template"
  else
    echo "Helm chart must include a Secret, ExternalSecret, or SealedSecret template for sensitive configuration." >&2
    exit 1
  fi
}

docker_workflow() {
  section "CHG-313 isolated Docker workflow"
  live_policy_guard backend/tests/test_chg313_docker_workflow.py frontend/tests/chg313DockerOidc.live.mjs
  if [[ "${CHG313_ISOLATED:-}" != "1" || -z "${CHG313_LIVE_ROOT:-}" || -z "${CHG313_LIVE_REPORT:-}" ]]; then
    echo "BLOCKED: set CHG313_ISOLATED=1, CHG313_LIVE_ROOT and CHG313_LIVE_REPORT for an owned temporary deployment." >&2
    exit 2
  fi
  run "$(python_bin)" -B "$ROOT_DIR/backend/scripts/chg313_docker_workflow_acceptance.py" --isolated-root "$CHG313_LIVE_ROOT" --report "$CHG313_LIVE_REPORT"
}

docker_config() {
  section "Docker Compose config"
  require_command docker
  if [[ ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
    echo "Missing docker-compose.yml. Add it before running docker:config." >&2
    exit 1
  fi
  cd "$ROOT_DIR"
  # Validate the committed model without resolving an operator's ignored local
  # env file into logs or allowing stale upgrade values to affect this gate.
  run docker compose config --no-env-resolution --quiet
}

helm_lint() {
  section "Helm lint"
  require_command helm
  if [[ ! -f "$ROOT_DIR/deploy/helm/nomosmart/Chart.yaml" ]]; then
    echo "Missing deploy/helm/nomosmart/Chart.yaml. Add the chart before running helm:lint." >&2
    exit 1
  fi
  cd "$ROOT_DIR"
  run helm lint deploy/helm/nomosmart
}

installer_test() {
  section "CHG-248 guided installer tests"
  cd "$ROOT_DIR"
  run "$(python_bin)" -m unittest discover -s deploy/installer/tests -v
}

release_test() {
  section "CHG-249 release package contract tests"
  cd "$ROOT_DIR"
  run "$(python_bin)" -m unittest discover -s deploy/release/tests -v
}

release_live() {
  section "CHG-249 isolated-builder Production release acceptance"
  local required=(
    NOMOSMART_RELEASE_REPO
    NOMOSMART_RELEASE_COMMIT
    NOMOSMART_RELEASE_ID
    NOMOSMART_RELEASE_IMAGE_INVENTORY
    NOMOSMART_RELEASE_OUTPUT_DIR
    NOMOSMART_RELEASE_SIGNING_FINGERPRINT
    NOMOSMART_RELEASE_PUBLIC_KEY
  )
  local name
  for name in "${required[@]}"; do
    if [[ -z "${!name:-}" ]]; then
      echo "Blocked: $name is required for isolated-builder release acceptance." >&2
      exit 2
    fi
  done
  local command=(
    "$ROOT_DIR/deploy/release/nomosmart-release"
    create
    --repo "$NOMOSMART_RELEASE_REPO"
    --commit "$NOMOSMART_RELEASE_COMMIT"
    --release-id "$NOMOSMART_RELEASE_ID"
    --image-inventory "$NOMOSMART_RELEASE_IMAGE_INVENTORY"
    --output-dir "$NOMOSMART_RELEASE_OUTPUT_DIR"
    --signing-fingerprint "$NOMOSMART_RELEASE_SIGNING_FINGERPRINT"
    --public-key "$NOMOSMART_RELEASE_PUBLIC_KEY"
  )
  if [[ -n "${NOMOSMART_RELEASE_GPG_HOME:-}" ]]; then
    command+=(--gpg-home "$NOMOSMART_RELEASE_GPG_HOME")
  fi
  run "${command[@]}"
}

installer_live() {
  section "CHG-248 real installer acceptance"
  cd "$ROOT_DIR"
  run "$(python_bin)" deploy/installer/tests/live_acceptance.py
}

installer_interrupt_live() {
  section "CHG-248 real interrupt/resume acceptance"
  cd "$ROOT_DIR"
  run "$(python_bin)" deploy/installer/tests/interrupt_live.py
}

all() {
  spec_doctor
  plan_doctor
  repo_doctor
  backend_syntax
}

usage() {
  cat <<'EOF'
Usage: ./HARNESS/harness.sh [command]

Commands:
  all             Run default checks (spec:doctor, plan:doctor, repo:doctor, backend:syntax)
  spec:doctor     Validate specification-driven control files
  spec:trace      Validate requirement-to-test traceability matrix
  plan:doctor     Validate development plan human-approval gates
  plan:approved   Validate active plan has human confirmation and approval
  repo:doctor     Validate expected repository shape
  frontend:lint   Run frontend ESLint
  frontend:build  Build the Next.js frontend
  backend:syntax  Compile backend Python source files
  backend:import  Import FastAPI app; requires configured local services
  test:plan       Check current risk policy and 80% advisory target
  test:frontend   Run frontend test script
  i18n:hardcoded  Fail on Traditional Chinese literals outside frontend locale files
  i18n:ast        Run the AST visible-copy/fixed-locale guard and negative fixtures
  test:backend    Run backend pytest suite
  test:installer  Run CHG-248 installer config/state/stage tests
  test:release    Run CHG-249 release source/signature/tamper contract tests
  integration:release-live
                  Run the complete release command on an approved isolated builder
  integration:installer-live
                  Run real disposable-cluster guided installer acceptance
  integration:installer-interrupt-live
                  Interrupt/resume a selected stage on an approved disposable target
  test:e2e        Run frontend E2E test script
  integration:milestone7-live
                  Run Milestone 7 live PostgreSQL/OpenSearch/Neo4j acceptance
  integration:milestone8b-live
                  Run Milestone 8B live RAG provider and validation worker acceptance
  migration:live  Run disposable Flyway fresh/upgrade/failure/checksum acceptance
  coverage:check  Verify source-bound complete measurement (80% advisory)
  coverage:strict Enforce legacy full-suite/80% evidence
  release:readiness
                  Review mandatory current scenarios and delivery evidence
  coverage:selftest
                  Run positive/negative source-bound coverage evidence fixtures
  test:security-simplification
                  Verify mounted Secrets, scanner-free ingestion and password-only login
  security:dependencies
                  Audit locked frontend/backend production dependencies
  security:static Run high-confidence/high-severity backend static analysis
  security:images Build production backend and frontend images for scanning
  security:containers
                  Fail on critical/high container image vulnerabilities
  security:sbom   Generate backend/frontend SPDX SBOM evidence
  docker:config   Validate root-level Docker Compose configuration
  docker:workflow Run CHG-313 opt-in isolated real Docker workflow
  helm:lint       Lint the Helm chart at deploy/helm/nomosmart
  deploy:doctor   Check expected deployment artifact locations
  deploy:config-policy
                  Check Docker env-file and Helm ConfigMap/Secret policy
  governance:selftest
                  Run positive and negative active-change gate fixtures
  help            Show this help
EOF
}

cmd="${1:-all}"

case "$cmd" in
  all) all ;;
  spec:doctor) spec_doctor ;;
  spec:trace) spec_trace ;;
  plan:doctor) plan_doctor ;;
  plan:approved) plan_approved ;;
  repo:doctor) repo_doctor ;;
  frontend:lint) frontend_lint ;;
  frontend:build) frontend_build ;;
  backend:syntax) backend_syntax ;;
  backend:import) backend_import ;;
  test:plan) test_plan ;;
  test:frontend) frontend_test ;;
  i18n:hardcoded) i18n_hardcoded ;;
  i18n:ast) i18n_ast ;;
  test:backend) backend_test ;;
  test:installer) installer_test ;;
  test:release) release_test ;;
  integration:release-live) release_live ;;
  integration:installer-live) installer_live ;;
  integration:installer-interrupt-live) installer_interrupt_live ;;
  test:e2e) e2e_test ;;
  integration:milestone7-live) milestone7_live ;;
  integration:milestone8b-live) milestone8b_live ;;
  migration:live) migration_live ;;
  coverage:check) coverage_check ;;
  coverage:strict) coverage_strict ;;
  release:readiness) release_readiness ;;
  coverage:selftest) coverage_evidence_selftest ;;
  test:security-simplification) security_simplification_test ;;
  security:dependencies) dependency_audit ;;
  security:static) static_security_scan ;;
  security:images) container_images ;;
  security:containers) container_security_scan ;;
  security:sbom) generate_sbom ;;
  docker:config) docker_config ;;
  docker:workflow) docker_workflow ;;
  helm:lint) helm_lint ;;
  deploy:doctor) deploy_doctor ;;
  deploy:config-policy) deploy_config_policy ;;
  governance:selftest) run "$ROOT_DIR/HARNESS/tests/governance_gates.sh" ;;
  help|-h|--help) usage ;;
  *)
    echo "Unknown harness command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
