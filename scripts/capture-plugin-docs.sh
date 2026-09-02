#!/usr/bin/env bash
#
# Regenerate one plugin's documentation screenshots against a seeded, genuinely
# healthy dev instance of that plugin (docs/screenshots/capture/README.md).
#
#   scripts/capture-plugin-docs.sh <plugin-repo-path> [--skip-build] [--keep-up] [--no-capture]
#
# The loop: build the plugin's dev stack -> up (plus the mock FTP source) ->
# seed -> real collection cycle + on-demand source checks -> log in ->
# capture.py docs/screenshots.yml -> down. Output lands in the plugin
# repo's docs/images/, overwriting in place so git shows what changed.
#
# Per-plugin inputs, all in the plugin repo:
#   docs/screenshots.yml               declarative manifest run by docs/screenshots/capture/capture.py
#   docs/screenshots/fixture.json      connection + station links + "capture" block
#                                      (capture.present_interval, default 15, is the interval
#                                      the captured screens show — see docs_capture_prime)
#   docs/screenshots/credentials.env   OPTIONAL, git-ignored: live credentials the
#                                      fixture references as "$ENV:NAME"
# Environment: CAPTURE_PORT (host port for the admin, default 8765),
#   CAPTURE_ADMIN_USER / CAPTURE_ADMIN_PASSWORD (seeded admin login),
#   CAPTURE_LANGS (comma-separated admin languages to capture, default "en").
#
# Requires: docker compose, python3 (uv if available, for a faster bootstrap of the
# runner's virtualenv in docs/screenshots/capture/.venv — Playwright + Chromium), and an
# adl:latest image built from a core that carries the seed_docs_demo / docs_capture_prime
# management commands (make build in this repo).
# Optional per plugin: docs/screenshots/compose.mock.yml (extra mock services, merged
# into the stack) and docs/screenshots/mock-ftp/generate.py (sample files in the
# plugin's own format, generated inside the mock FTP source at start).
set -euo pipefail

usage() { sed -n '2,20p' "$0"; exit 1; }
[[ $# -ge 1 ]] || usage

SKIP_BUILD=0; KEEP_UP=0; NO_CAPTURE=0
PLUGIN_DIR=$(cd "$1" && pwd); shift
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    --keep-up) KEEP_UP=1 ;;
    --no-capture) NO_CAPTURE=1 ;;
    *) usage ;;
  esac
done

ADL_DIR=$(cd "$(dirname "$0")/.." && pwd)
CAPTURE_DIR="$ADL_DIR/docs/screenshots/capture"
SLUG=$(basename "$PLUGIN_DIR")
MODULE=$(basename "$(ls -d "$PLUGIN_DIR"/plugins/*/ | head -1)")
PROJECT="${SLUG}-docs"
MANIFEST="$PLUGIN_DIR/docs/screenshots.yml"
FIXTURE="$PLUGIN_DIR/docs/screenshots/fixture.json"
CREDENTIALS="$PLUGIN_DIR/docs/screenshots/credentials.env"
WORK=$(mktemp -d -t adl-capture-XXXXXX)
ADMIN_USER=${CAPTURE_ADMIN_USER:-admin}
ADMIN_PASSWORD=${CAPTURE_ADMIN_PASSWORD:-adl-docs-demo}
LANGS=${CAPTURE_LANGS:-en}

log() { printf '\n\033[1;34m[capture %s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { printf '\033[1;31m[capture] %s\033[0m\n' "$*" >&2; exit 1; }

# the dev compose is docker-compose.yml in most plugin repos, docker-compose.dev.yml in a few
PLUGIN_COMPOSE=""
for candidate in docker-compose.yml docker-compose.dev.yml; do
  [[ -f "$PLUGIN_DIR/$candidate" ]] && { PLUGIN_COMPOSE="$PLUGIN_DIR/$candidate"; break; }
done
[[ -n "$PLUGIN_COMPOSE" ]] || die "$PLUGIN_DIR has no docker-compose.yml / docker-compose.dev.yml"
[[ -f "$FIXTURE" ]] || die "missing $FIXTURE"
[[ -f "$MANIFEST" || $NO_CAPTURE = 1 ]] || die "missing $MANIFEST"
command -v python3 >/dev/null || die "python3 is required"

# --- plugin .env: the documented dev setup, with the build ids filled in ------
if [[ ! -f "$PLUGIN_DIR/.env" ]]; then
  cp "$PLUGIN_DIR/.env.sample" "$PLUGIN_DIR/.env"
  log "created .env from .env.sample"
fi
sed -i.bak -e "s/^PLUGIN_BUILD_UID=$/PLUGIN_BUILD_UID=$(id -u)/" \
           -e "s/^PLUGIN_BUILD_GID=$/PLUGIN_BUILD_GID=$(id -g)/" "$PLUGIN_DIR/.env"
rm -f "$PLUGIN_DIR/.env.bak"
# The admin is published on a port of the harness's own, replacing whatever the
# plugin compose maps, so a running dev stack on the usual ports is no obstacle.
PORT=${CAPTURE_PORT:-8765}
BASE_URL="http://localhost:$PORT"

# --- the capture block of the fixture -------------------------------------------
fixture_get() { python3 -c "import json,sys; c=json.load(open(sys.argv[1])).get('capture',{}); v=c.get(sys.argv[2], sys.argv[3] if len(sys.argv)>3 else ''); print(' '.join(v) if isinstance(v,list) else v)" "$FIXTURE" "$@"; }
CONNECTION=$(fixture_get connection)
[[ -n "$CONNECTION" ]] || die "fixture has no capture.connection"
INGEST=$(fixture_get ingest true)
PROBE=$(fixture_get probe true)
STATION_CHECKS=$(fixture_get station_checks)
WAIT=$(fixture_get wait 180)
PRESENT_INTERVAL=$(fixture_get present_interval 15)

# --- compose overlay: mock source, capture mounts, worker layout fixes -----------
BASE_COMPOSE=(docker compose --project-directory "$PLUGIN_DIR" -p "$PROJECT" -f "$PLUGIN_COMPOSE")
SERVICES=$("${BASE_COMPOSE[@]}" config --services)
IMAGE=$("${BASE_COMPOSE[@]}" config --format json | python3 -c "import json,sys; print(json.load(sys.stdin)['services']['adl']['image'])")

OVERLAY="$WORK/compose.capture.yml"
{
cat <<EOF
# generated by scripts/capture-plugin-docs.sh — do not edit
services:
  mock_ftp:
    build: $CAPTURE_DIR/mock-ftp
    image: adl-docs-mock-ftp
    container_name: ${PROJECT}-mock-ftp
    environment:
      SAMPLE_TZ: Africa/Nairobi
  adl:
    ports: !override
      - "$PORT:8000"
    depends_on:
      - mock_ftp
    volumes:
      - $PLUGIN_DIR/docs:/adl/docs-capture:ro
    environment:
      CAPTURE_ADMIN_USER: $ADMIN_USER
      CAPTURE_ADMIN_PASSWORD: $ADMIN_PASSWORD
EOF
if [[ -d "$PLUGIN_DIR/docs/screenshots/mock-ftp" ]]; then
cat <<EOF
  mock_ftp:
    volumes:
      # plugin-provided samples: a generate.py here runs at start (see mock-ftp/server.py)
      - $PLUGIN_DIR/docs/screenshots/mock-ftp:/srv/plugin-samples:ro
EOF
fi
if [[ -f "$CREDENTIALS" ]]; then
cat <<EOF
    env_file:
      - $PLUGIN_DIR/.env
      - $CREDENTIALS
EOF
fi
if grep -qx adl_celery_worker <<<"$SERVICES" && ! grep -qx adl_celery_worker_adl <<<"$SERVICES"; then
  log "plugin compose predates the queue-specific workers: routing its worker to the ingestion queue and adding a housekeeping worker"
cat <<EOF
  adl_celery_worker:
    command: celery-worker-adl
  capture_worker_default:
    image: $IMAGE
    command: celery-worker-default
    env_file:
      - $PLUGIN_DIR/.env
    environment:
      DATABASE_URL: timescalegis://\${ADL_DB_USER:-adl}:\${ADL_DB_PASSWORD}@adl_db:5432/\${ADL_DB_NAME:-adl}
      REDIS_URL: redis://adl_redis:6379/0
      PLUGIN_RUNTIME_SETUP_MARKER: 0
      WAIT_HOSTS: adl_db:5432,adl_redis:6379,adl:8000
      WAIT_TIMEOUT: 120
    depends_on:
      - adl
    volumes:
      - $PLUGIN_DIR/plugins/$MODULE:/adl/plugins/$MODULE
EOF
fi
} > "$OVERLAY"

COMPOSE=("${BASE_COMPOSE[@]}" -f "$OVERLAY")
# a plugin needing a mock source of its own (a database, an HTTP stub) ships it here
if [[ -f "$PLUGIN_DIR/docs/screenshots/compose.mock.yml" ]]; then
  log "adding the plugin's own mock services from docs/screenshots/compose.mock.yml"
  COMPOSE+=(-f "$PLUGIN_DIR/docs/screenshots/compose.mock.yml")
fi
cleanup() {
  if [[ $KEEP_UP = 1 ]]; then
    log "stack left running at $BASE_URL (project $PROJECT); stop it with:"
    echo "  ${COMPOSE[*]} down -v"
  else
    log "stopping the stack"
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# --- build, up, wait ----------------------------------------------------------------
log "plugin $SLUG ($MODULE) — image $IMAGE — admin at $BASE_URL"
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
if [[ $SKIP_BUILD = 0 ]]; then
  log "building"
  "${COMPOSE[@]}" build
fi
log "starting"
"${COMPOSE[@]}" up -d
log "waiting for the admin to answer"
for i in $(seq 1 120); do
  if curl -sf -o /dev/null "$BASE_URL/login/"; then break; fi
  [[ $i = 120 ]] && { "${COMPOSE[@]}" logs adl | tail -50; die "admin did not come up"; }
  sleep 5
done

# --- seed and prime ---------------------------------------------------------------------
log "seeding"
"${COMPOSE[@]}" exec -T adl adl seed_docs_demo --fixture /adl/docs-capture/screenshots/fixture.json

PRIME=(adl docs_capture_prime --connection "$CONNECTION" --wait "$WAIT" \
       --present-interval "$PRESENT_INTERVAL" --evaluate)
[[ $INGEST = true || $INGEST = True ]] && PRIME+=(--ingest)
[[ $PROBE = true || $PROBE = True ]] && PRIME+=(--probe)
for s in $STATION_CHECKS; do PRIME+=(--station-check "$s"); done
log "priming: ${PRIME[*]}"
"${COMPOSE[@]}" exec -T adl "${PRIME[@]}"

[[ $NO_CAPTURE = 1 ]] && exit 0

# --- capture ---------------------------------------------------------------------------------
VENV="$CAPTURE_DIR/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  log "bootstrapping the runner's virtualenv in $VENV"
  if command -v uv >/dev/null; then
    uv venv -q --clear "$VENV" && uv pip install -q --python "$VENV/bin/python" -r "$CAPTURE_DIR/requirements.txt"
  else
    python3 -m venv "$VENV" && "$VENV/bin/pip" install -q -r "$CAPTURE_DIR/requirements.txt"
  fi
  "$VENV/bin/python" -m playwright install chromium
fi
log "capturing (languages: $LANGS)"
"$VENV/bin/python" "$CAPTURE_DIR/capture.py" "$MANIFEST" \
  --base-url "$BASE_URL" --repo-dir "$PLUGIN_DIR" --lang "$LANGS" \
  --username "$ADMIN_USER" --password "$ADMIN_PASSWORD"
log "done — images in $PLUGIN_DIR/docs/images/"
