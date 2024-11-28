# Ensure looping over globs doesn't match nothing
shopt -s nullglob

if [ -t 0 ]; then
  TPUTTERM=()
else
  # if we are in a non-interactive environment set a default -T for tput so it doesn't
  # crash
  TPUTTERM=(-T xterm-256color)
fi

safe_tput(){
  if [[ -z "${NO_COLOR:-}" ]]; then
    tput "${TPUTTERM[@]}" "$@"
  fi
}

# shellcheck disable=SC2034
RED=$(safe_tput setaf 1)
# shellcheck disable=SC2034
GREEN=$(safe_tput setaf 2)
# shellcheck disable=SC2034
YELLOW=$(safe_tput setaf 3)
# shellcheck disable=SC2034
BLUE=$(safe_tput setaf 4)
# shellcheck disable=SC2034
PURPLE=$(safe_tput setaf 5)
# shellcheck disable=SC2034
CYAN=$(safe_tput setaf 6)
# shellcheck disable=SC2034
BOLD="$(safe_tput bold)"

NC=$(safe_tput sgr0) # No Color

ADL_PLUGIN_DIR=${ADL_PLUGIN_DIR:-/adl/plugins}

simple_log(){
  echo -e "${BLUE}[PLUGIN] $*${NC}"
}
log(){
  echo -e "${BLUE}[PLUGIN][${plugin_name:-SETUP}] $*${NC}"
}
log_success(){
  echo -e "${GREEN}[PLUGIN][${plugin_name:-SETUP}] $*${NC}"
}
error(){
  echo -e "${RED}[PLUGIN][${plugin_name:-SETUP}] ERROR: $*${NC}"
}


startup_plugin_setup(){
  if [[ -z "${ADL_PLUGIN_SETUP_ALREADY_RUN:-}" ]]; then
    if [[ -z "${ADL_DISABLE_PLUGIN_INSTALL_ON_STARTUP:-}" ]]; then
      # Make sure any plugins found in the data dir are installed in this container if not
      # already.
      for plugin_dir in "$ADL_PLUGIN_DIR"/*/; do
        log "Found a plugin in $plugin_dir, ensuring it is installed..."
        if [[ -d "$plugin_dir" ]]; then
          /adl/plugins/install_plugin.sh --runtime --folder "$plugin_dir"
        fi
      done

      # Make sure any plugins configured via the environment variable are installed.
      for url in $(echo "${ADL_PLUGIN_URLS:-}" | tr "," "\n")
      do
        log "Downloading and installing the plugin found at $url"
        /adl/plugins/install_plugin.sh --runtime --url "$url"
      done

      for repo in $(echo "${ADL_PLUGIN_GIT_REPOS:-}" | tr "," "\n")
      do
        log "Downloading and installing the plugin found at $repo"
        /adl/plugins/install_plugin.sh --runtime --git "$repo"
      done

      # Ensure we don't run this function multiple times in the same shell.
      export ADL_PLUGIN_SETUP_ALREADY_RUN="yes"
    else
      log "Not installing any plugins found in ADL_PLUGIN_DIR or set in the
      ADL_PLUGIN_URLS or ADL_PLUGIN_GIT_REPOS env variables as
      ADL_DISABLE_PLUGIN_INSTALL_ON_STARTUP is set."
    fi
  fi
}