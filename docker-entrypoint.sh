#!/bin/bash
# Bash strict mode: http://redsymbol.net/articles/unofficial-bash-strict-mode/
set -euo pipefail

show_help() {
    echo """
The available WIS2Box ADL related commands and services are shown below:

ADMIN COMMANDS:
manage          : Manage WIS2Box ADL and its database
shell           : Start a Django Python shell
install-plugin  : Installs a plugin (append --help for more info).
uninstall-plugin: Un-installs a plugin (append --help for more info).
list-plugins    : Lists currently installed plugins.
help            : Show this message

SERVICE COMMANDS:
gunicorn            : Start WIS2Box ADL django using a prod ready gunicorn server:
                         * Waits for the postgres database to be available first.
                         * Automatically migrates the database on startup.
                         * Binds to 0.0.0.0
celery-worker       : Start the celery worker queue which runs important async tasks
celery-beat         : Start the celery beat service used to schedule periodic jobs
"""
}

run_setup_commands_if_configured(){
  startup_plugin_setup
  if [ "$MIGRATE_ON_STARTUP" = "true" ] ; then
    echo "python /wis2box_adl/app/src/wis2box_adl/manage.py migrate"
    /wis2box_adl/app/src/wis2box_adl/manage.py migrate
  fi

  # collect staticfiles
  if [ "$COLLECT_STATICFILES_ON_STARTUP" = "true" ] ; then
    echo "python /wis2box_adl/app/src/wis2box_adl/manage.py collectstatic --noinput"
    /wis2box_adl/app/src/wis2box_adl/manage.py collectstatic --noinput
  fi
}

start_celery_worker() {
    startup_plugin_setup

    EXTRA_CELERY_ARGS=()

    if [[ -n "$WIS2BOX_ADL_GUNICORN_NUM_OF_WORKERS" ]]; then
        EXTRA_CELERY_ARGS+=(--concurrency "$WIS2BOX_ADL_GUNICORN_NUM_OF_WORKERS")
    fi
    exec celery -A wis2box_adl worker "${EXTRA_CELERY_ARGS[@]}" -l INFO "$@"
}

run_server() {
    run_setup_commands_if_configured

    if [[ "$1" = "wsgi" ]]; then
        STARTUP_ARGS=(wis2box_adl.config.wsgi:application)
    elif [[ "$1" = "asgi" ]]; then
        STARTUP_ARGS=(-k uvicorn.workers.UvicornWorker wis2box_adl.config.asgi:application)
    else
        echo -e "\e[31mUnknown run_server argument $1 \e[0m" >&2
        exit 1
    fi


    # Gunicorn args explained in order:
    #
    # 1. See https://docs.gunicorn.org/en/stable/faq.html#blocking-os-fchmod for
    #    why we set worker-tmp-dir to /dev/shm by default.
    # 2. Log to stdout
    # 3. Log requests to stdout
    exec gunicorn --workers="$WIS2BOX_ADL_GUNICORN_NUM_OF_WORKERS" \
        --worker-tmp-dir "${TMPDIR:-/dev/shm}" \
        --log-file=- \
        --access-logfile=- \
        --capture-output \
        -b "0.0.0.0:8000" \
        --log-level="${WIS2BOX_ADL_LOG_LEVEL}" \
        "${STARTUP_ARGS[@]}" \
        "${@:2}"
}

# ======================================================
# COMMANDS
# ======================================================

if [[ -z "${1:-}" ]]; then
    echo "Must provide arguments to docker-entrypoint.sh"
    show_help
    exit 1
fi

source /wis2box_adl/venv/bin/activate
source /wis2box_adl/plugins/utils.sh

case "$1" in
gunicorn)
    run_server asgi "${@:2}"
    ;;
gunicorn-wsgi)
    run_server wsgi "${@:2}"
    ;;
manage)
    exec python3 /wis2box_adl/app/src/wis2box_adl/manage.py "${@:2}"
    ;;
shell)
    exec python3 /wisbox_adl/app/src/wisbox_adl/manage.py shell
    ;;
celery-worker)
    start_celery_worker -Q celery -n default-worker@%h "${@:2}"
    ;;
celery-beat)
    exec celery -A wis2box_adl beat -l "${WIS2BOX_ADL_CELERY_BEAT_DEBUG_LEVEL}" -S django_celery_beat.schedulers:DatabaseScheduler "${@:2}"
    ;;
install-plugin)
    exec /wis2box_adl/plugins/install_plugin.sh --runtime "${@:2}"
    ;;
uninstall-plugin)
    exec /wis2box_adl/plugins/uninstall_plugin.sh "${@:2}"
    ;;
list-plugins)
    exec /wis2box_adl/plugins/list_plugins.sh "${@:2}"
    ;;
*)
    echo "Command given was $*"
    show_help
    exit 1
    ;;
esac