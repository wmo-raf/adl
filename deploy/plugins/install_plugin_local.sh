#!/bin/bash
# Bash strict mode: http://redsymbol.net/articles/unofficial-bash-strict-mode/
set -eo pipefail

show_help() {
  echo """
Usage: install_plugin.sh [-d] [-f <plugin folder>]
  -f, --folder <plugin folder>        The folder where the plugin to install is located.
  -g, --git <https git repo url>      An url to a git repo containing the plugin to install.
  -u, --url <plugin url>              An url to a .tar.gz file containing the plugin to install.
  -d, --dev                           Install the plugin for development.
  -h, --help                          Show this help message and exit.
  
A WIS2Box plugin is a folder named after the plugin. This must be a valid Python package.
"""
}

PWD="$(dirname "$(realpath "$0")")"

source "$PWD/utils.sh"

# First parse the args using getopt
VALID_ARGS=$(getopt -o u:dhf:rg:o --long hash:,url:,git:,help,dev,folder: -- "$@")
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
dev=false
url=
folder=
git=
exclusive_flag_count=0

while [ : ]; do
  case "$1" in
  -d | --dev)
    log "Installing plugin in dev mode."
    dev=true
    shift
    ;;
  -f | --folder)
    folder="$2"
    shift 2
    exclusive_flag_count=$((exclusive_flag_count + 1))
    ;;
  -u | --url)
    url="$2"
    shift 2
    exclusive_flag_count=$((exclusive_flag_count + 1))
    ;;
  -g | --git)
    git="$2"
    shift 2
    exclusive_flag_count=$((exclusive_flag_count + 1))
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

if [[ "$exclusive_flag_count" -eq "0" ]]; then
  error "You must provide one of the following flags: --folder, --url or --git"
  show_help
  exit 1
fi

if [[ "$exclusive_flag_count" -gt "1" ]]; then
  error "You must provide only one of the following flags: --folder, --url or --git"
  show_help
  exit 1
fi

# --git was provided, download the plugin using git..
if [[ -n "$git" ]]; then
  log "Downloading plugin from git repo at $git."
  temp_work_dir=$(mktemp -d)
  cd "$temp_work_dir"
  git clone "$git" .

  dirs=("$temp_work_dir"/plugins/*/)
  num_dirs=${#dirs[@]}
  if [[ "$num_dirs" -ne 1 ]]; then
    error "$git does not look like a valid WISBox ADL plugin. The plugins/ subdirectory in the repo must contain exactly one sub-directory."
    exit 1
  fi
  folder=${dirs[0]}
fi

# --url was set, download the url, untar it to a temp dir, and verify it only has one
# sub dir.
if [[ -n "$url" ]]; then
  log "Downloading and extracting plugin from $url."
  temp_work_dir=$(mktemp -d)
  curl -Ls "$url" | tar xz -C "$temp_work_dir"

  dirs=("$temp_work_dir"/*/plugins/*/)
  num_dirs=${#dirs[@]}
  if [[ "$num_dirs" -ne 1 ]]; then
    error "$url does not look like a valid WISBox ADL plugin. The plugin archive must contain a plugins/ sub-directory itself containing exactly one sub-directory for the plugin."
    exit 1
  fi
  folder=${dirs[0]}
fi
# copy the plugin at the folder location into the plugin dir if it has not been already.
plugin_name="$(basename -- "$folder")"
plugin_install_dir="$WIS2BOX_ADL_PLUGIN_DIR/$plugin_name"
if [[ ! "$folder" -ef "$plugin_install_dir" ]]; then
  log "Copying plugin $plugin_name into plugins folder at $plugin_install_dir."
  mkdir -p "$WIS2BOX_ADL_PLUGIN_DIR"
  rm -rf "$plugin_install_dir"
  cp -r "$folder" "$plugin_install_dir"
  folder="$WIS2BOX_ADL_PLUGIN_DIR/$plugin_name"
fi

# Now we've copied the plugin into the plugin dir we can delete the tmp download dir
# if we used it.
if [[ -n "${temp_work_dir:-}" ]]; then
  rm -rf "$temp_work_dir"
fi

check_and_run_script() {
  if [[ -f "$1/$2" ]]; then
    log "Running ${plugin_name}'s custom $2 script"
    bash "$1/$2"
  fi
}

log "Building ${plugin_name}."

if [[ "$dev" == true ]]; then
  pip3 install -e "$folder"
else
  pip3 install "$folder"
fi

check_and_run_script "$folder" build.sh

check_and_run_script "$folder" runtime_setup.sh

log_success "Finished setting up ${plugin_name} successfully."
