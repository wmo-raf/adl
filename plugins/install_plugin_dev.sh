#!/bin/bash
# Bash strict mode: http://redsymbol.net/articles/unofficial-bash-strict-mode/
set -eo pipefail

show_help() {
  echo """
Usage: install_plugin.sh -f <plugin folder>
  -f, --folder <plugin folder>        The folder where the plugin to install is located.
  -h, --help                          Show this help message and exit.

A WIS2Box plugin is a folder named after the plugin. This must be a valid Python package.
"""
}

PWD="$(dirname "$(realpath "$0")")"

source "$PWD/utils.sh"

# First parse the args using getopt
VALID_ARGS=$(getopt -o hf: --long help,folder: -- "$@")
if [[ $? -ne 0 ]]; then
  error "Incorrect options provided."
  show_help
  exit 1
fi
eval set -- "$VALID_ARGS"

if [[ "$*" == "--" ]]; then
  error "No arguments provided."
  show_help
  exit 1
fi

# Next loop over the user provided args and set flags accordingly.
folder=

while [ : ]; do
  case "$1" in
  -f | --folder)
    folder="$2"
    shift 2
    ;;
  -h | --help)
    show_help
    exit 0
    ;;
  --)
    shift
    break
    ;;
  esac
done

if [[ -z "$folder" ]]; then
  error "You must provide the --folder flag."
  show_help
  exit 1
fi

plugin_name="$(basename -- "$folder")"

check_and_run_script() {
  if [[ -f "$1/$2" ]]; then
    log "Running ${plugin_name}'s custom $2 script"
    bash "$1/$2"
  fi
}

log "Building ${plugin_name}."

pip3 install -e "$folder"

check_and_run_script "$folder" build.sh

check_and_run_script "$folder" runtime_setup.sh

log_success "Finished setting up ${plugin_name} successfully."
