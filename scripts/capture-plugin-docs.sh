#!/usr/bin/env bash
#
# Regenerate one plugin's documentation screenshots against a seeded, genuinely
# healthy dev instance of that plugin (docs/screenshots/capture/README.md).
#
#   scripts/capture-plugin-docs.sh <plugin-repo-path> [--skip-build] [--keep-up]
#                                  [--no-capture] [--core] [--only <entry name>]...
#
# --core runs the ADL CORE manifest (docs/screenshots/screenshots.yml) against
# the given plugin's stack, writing into the core's docs/_static/images. The
# core's own user-guide screenshots need a real connection with a real source,
# which core alone has not got; the FTP plugin's stack — mock FTP source, a
# genuine collection cycle — is exactly that instance, and the core manifest's
# URLs (/ftpstationlink/...) already assume it. See `make docs-screenshots`.
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
#   docs/screenshots/seed.py           OPTIONAL: extra seeding the fixture JSON cannot
#                                      express -- rows behind an API (a paired agent
#                                      device), uploads, or state a plugin only reaches
#                                      through its own code. Runs inside the web
#                                      container after seed_docs_demo and before
#                                      priming, via `adl shell <`.
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

usage() { sed -n '2,28p' "$0"; exit 1; }
[[ $# -ge 1 ]] || usage

SKIP_BUILD=0; KEEP_UP=0; NO_CAPTURE=0; CORE=0; ONLY=()
PLUGIN_DIR=$(cd "$1" && pwd); shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1 ;;
    --keep-up) KEEP_UP=1 ;;
    --no-capture) NO_CAPTURE=1 ;;
    --core) CORE=1 ;;
    # Re-shoot named entries only. A full run re-renders every image, and the
    # diagnostic shots carry live timestamps, so fixing one crop otherwise
    # shows up as a diff in unrelated images.
    --only) shift; [[ $# -gt 0 ]] || usage; ONLY+=(--only "$1") ;;
    *) usage ;;
  esac
  shift
done

ADL_DIR=$(cd "$(dirname "$0")/.." && pwd)
CAPTURE_DIR="$ADL_DIR/docs/screenshots/capture"
SLUG=$(basename "$PLUGIN_DIR")
MODULE=$(basename "$(ls -d "$PLUGIN_DIR"/plugins/*/ | head -1)")
PROJECT="${SLUG}-docs"
MANIFEST="$PLUGIN_DIR/docs/screenshots.yml"
CAPTURE_REPO="$PLUGIN_DIR"
FIXTURE="$PLUGIN_DIR/docs/screenshots/fixture.json"
CREDENTIALS="$PLUGIN_DIR/docs/screenshots/credentials.env"
WORK=$(mktemp -d -t adl-capture-XXXXXX)
# Run from the plugin directory, the way its README tells an operator to: several
# plugin composes mount "$PWD/nginx.conf", which compose interpolates from the
# invoking shell's cwd, not from --project-directory. Every path above is already
# absolute, so nothing else is affected.
cd "$PLUGIN_DIR"
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
if [[ $CORE = 1 ]]; then
  # capture.py picks docs/_static/images under a repo-dir that has it (the core)
  # and docs/images otherwise (a plugin), so the output path follows from this.
  MANIFEST="$ADL_DIR/docs/screenshots/screenshots.yml"
  CAPTURE_REPO="$ADL_DIR"
fi
[[ -f "$FIXTURE" ]] || die "missing $FIXTURE"
[[ -f "$MANIFEST" || $NO_CAPTURE = 1 ]] || die "missing $MANIFEST"
command -v python3 >/dev/null || die "python3 is required"

# --- plugin .env: the documented dev setup, with the build ids filled in ------
if [[ ! -f "$PLUGIN_DIR/.env" ]]; then
  cp "$PLUGIN_DIR/.env.sample" "$PLUGIN_DIR/.env"
  log "created .env from .env.sample"
fi
sed -i.bak -e "s/^PLUGIN_BUILD_UID=$/PLUGIN_BUILD_UID=$(id -u)/" \
           -e "s/^PLUGIN_BUILD_GID=$/PLUGIN_BUILD_GID=$(id -g)/" \
           -e "s/^ADL_DB_PASSWORD=$/ADL_DB_PASSWORD=adl-docs-capture/" "$PLUGIN_DIR/.env"
rm -f "$PLUGIN_DIR/.env.bak"
# An empty ADL_DB_PASSWORD leaves the web container dying on "fe_sendauth: no
# password supplied", which reaches the operator only as "admin did not come up".
grep -q "^ADL_DB_PASSWORD=." "$PLUGIN_DIR/.env" || die "$PLUGIN_DIR/.env has no ADL_DB_PASSWORD"
# The admin is published on a port of the harness's own, replacing whatever the
# plugin compose maps, so a running dev stack on the usual ports is no obstacle.
PORT=${CAPTURE_PORT:-8765}
BASE_URL="http://localhost:$PORT"
# The capture talks to the web container directly, so the plugin's nginx proxy
# has no reason to claim the developer's port 80 -- and if anything else on the
# machine holds it, the whole stack fails to start. Compose interpolation takes
# the shell's value over the project .env, and 0 asks Docker for an ephemeral one.
export ADL_WEB_PROXY_PORT=0

# --- the capture block of the fixture -------------------------------------------
fixture_get() { python3 -c "import json,sys; c=json.load(open(sys.argv[1])).get('capture',{}); v=c.get(sys.argv[2], sys.argv[3] if len(sys.argv)>3 else ''); print(' '.join(v) if isinstance(v,list) else v)" "$FIXTURE" "$@"; }
CONNECTION=$(fixture_get connection)
[[ -n "$CONNECTION" ]] || die "fixture has no capture.connection"
INGEST=$(fixture_get ingest true)
PROBE=$(fixture_get probe true)
STATION_CHECKS=$(fixture_get station_checks)
# Newline-separated, unlike the space-joined lists above: a dispatch channel is
# named the way the admin shows it ("Demo MinIO Upload"), so splitting on spaces
# would turn one channel into three that do not exist.
fixture_get_lines() { python3 -c "import json,sys; c=json.load(open(sys.argv[1])).get('capture',{}); v=c.get(sys.argv[2], []); print('\n'.join(v if isinstance(v,list) else [v]))" "$FIXTURE" "$@"; }
DISPATCH_CHANNELS=$(fixture_get_lines dispatch)
WAIT=$(fixture_get wait 180)
PRESENT_INTERVAL=$(fixture_get present_interval 15)
# The mock source writes its samples in local wall-clock time, and the plugin
# reads them back in the connection's stations timezone. If the two disagree the
# newest sample lands hours in the future (or the past) and the data-freshness
# layer reports something no operator would ever see, so take the sample clock
# from the fixture's own connection.
SAMPLE_TZ=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('connection',{}).get('fields',{}).get('stations_timezone') or 'Africa/Nairobi')" "$FIXTURE")

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
      SAMPLE_TZ: $SAMPLE_TZ
EOF
# Each service is emitted exactly once: a second "mock_ftp:" key here would be a
# duplicate mapping key, which docker compose rejects outright. So this block has
# to be written while mock_ftp is still the open service — emitting it after the
# next "mock_wis2box:" key would silently attach the mount to *that* service, and
# the plugin's generator would never run.
if [[ -d "$PLUGIN_DIR/docs/screenshots/mock-ftp" ]]; then
cat <<EOF
    volumes:
      # plugin-provided samples: a generate.py here runs at start (see mock-ftp/server.py)
      - $PLUGIN_DIR/docs/screenshots/mock-ftp:/srv/plugin-samples:ro
EOF
fi
cat <<EOF
  # Stands in for a wis2box instance's station catalogue, so the WIS2Box
  # Stations comparison page has all three of its tables populated.
  mock_wis2box:
    build: $CAPTURE_DIR/mock-wis2box
    image: adl-docs-mock-wis2box
    container_name: ${PROJECT}-mock-wis2box
  adl:
    ports: !override
      - "$PORT:8000"
    depends_on:
      - mock_ftp
      - mock_wis2box
    volumes:
      - $PLUGIN_DIR/docs:/adl/docs-capture:ro
    environment:
      CAPTURE_ADMIN_USER: $ADMIN_USER
      CAPTURE_ADMIN_PASSWORD: $ADMIN_PASSWORD
EOF
# Credentials belong to the web container, which is where seed_docs_demo resolves
# the fixture's \$ENV: references — so this block must stay attached to "adl:".
if [[ -f "$CREDENTIALS" ]]; then
cat <<EOF
    env_file:
      - $PLUGIN_DIR/.env
      - $CREDENTIALS
EOF
fi
LEGACY_WORKER=0
if grep -qx adl_celery_worker <<<"$SERVICES" && ! grep -qx adl_celery_worker_adl <<<"$SERVICES"; then
  LEGACY_WORKER=1
  log "plugin compose predates the queue-specific workers: routing its worker to the ingestion queue and adding a housekeeping worker"
fi

# The plugin composes wait on adl:8000 with the image's default 30s budget, which
# the web container's first boot (migrations + collectstatic) routinely overruns.
# The celery services then exit, nothing restarts them, and no scheduled run ever
# fires — the scheduler layer of the diagnostic is red for a reason that is purely
# an artefact of capture. Give them room, and restart them if they still lose the race.
while read -r svc; do
  [[ -n "$svc" && "$svc" == *celery* ]] || continue
  echo "  $svc:"
  echo "    restart: on-failure"
  [[ $LEGACY_WORKER = 1 && "$svc" = adl_celery_worker ]] && echo "    command: celery-worker-adl"
  echo "    environment:"
  echo "      WAIT_TIMEOUT: 300"
done <<<"$SERVICES"

if [[ $LEGACY_WORKER = 1 ]]; then
cat <<EOF
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
      WAIT_TIMEOUT: 300
    restart: on-failure
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

# The Vue viewer builds its API URLs from the Wagtail Site record, which is
# localhost:80 out of the box. The capture stack is published on $PORT, so every
# viewer API call would be cross-origin, the browser would block it, and the
# connection/station pickers would sit empty at "No available options" — the
# table and chart shots then capture a blank panel and look plausible. Point the
# site at the port the instance is actually served on.
log "pointing the Wagtail site at localhost:$PORT (the viewer reads its API base from it)"
"${COMPOSE[@]}" exec -T adl adl shell -c "
from wagtail.models import Site
Site.objects.filter(is_default_site=True).update(hostname='localhost', port=$PORT)
" >/dev/null

# Point the WIS2Box settings at the mock catalogue above; without a URL the
# comparison page renders only its "configure me" state.
log "pointing WIS2Box settings at the mock catalogue"
"${COMPOSE[@]}" exec -T adl adl shell -c "
from django.core.cache import cache
from wagtail.models import Site
from adl.wis2box.models import Wis2BoxSettings
site = Site.objects.get(is_default_site=True)
s, _ = Wis2BoxSettings.objects.get_or_create(site=site)
s.wis2box_url = 'http://mock_wis2box'
s.save()
cache.delete('wis2box_stations')
" >/dev/null

# Extra seeding the declarative fixture cannot express (see seed.py above).
# It runs after seed_docs_demo so it can build on the seeded rows, and before
# priming so anything it creates is part of the cycle the screens show.
if [[ -f "$PLUGIN_DIR/docs/screenshots/seed.py" ]]; then
  log "running the plugin's post-seed script"
  "${COMPOSE[@]}" exec -T adl adl shell < "$PLUGIN_DIR/docs/screenshots/seed.py"
fi

PRIME=(adl docs_capture_prime --connection "$CONNECTION" --wait "$WAIT" \
       --present-interval "$PRESENT_INTERVAL" --evaluate)
[[ $INGEST = true || $INGEST = True ]] && PRIME+=(--ingest)
[[ $PROBE = true || $PROBE = True ]] && PRIME+=(--probe)
for s in $STATION_CHECKS; do PRIME+=(--station-check "$s"); done
while IFS= read -r c; do [[ -n $c ]] && PRIME+=(--dispatch "$c"); done <<< "$DISPATCH_CHANNELS"
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
  --base-url "$BASE_URL" --repo-dir "$CAPTURE_REPO" --lang "$LANGS" \
  --username "$ADMIN_USER" --password "$ADMIN_PASSWORD" "${ONLY[@]+"${ONLY[@]}"}"
if [[ $CORE = 1 ]]; then
  log "done — images in $ADL_DIR/docs/_static/images/"
else
  log "done — images in $PLUGIN_DIR/docs/images/"
fi
