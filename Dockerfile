# syntax=docker/dockerfile:1.5

ARG UID=9999
ARG GID=9999

# =============================================================================
# Builder — install dependencies and compile everything
# =============================================================================
FROM erickotenyo/adl-base:3.12.0 AS builder

ARG UID
ARG GID

ENV DOCKER_USER=adl_docker_user

# Create group and user
RUN if getent group $GID > /dev/null; then \
        existing_group=$(getent group $GID | cut -d: -f1); \
        if [ "$existing_group" != "adl_docker_group" ]; then \
            groupmod -n adl_docker_group "$existing_group"; \
        fi; \
    else \
        groupadd -g $GID adl_docker_group; \
    fi && \
    useradd --shell /bin/bash -u $UID -g $GID -o -c "" -m adl_docker_user -l || exit 0

# Install docker-compose wait
ARG DOCKER_COMPOSE_WAIT_VERSION=2.12.1
ARG DOCKER_COMPOSE_WAIT_PLATFORM_SUFFIX=""

ADD https://github.com/ufoscout/docker-compose-wait/releases/download/$DOCKER_COMPOSE_WAIT_VERSION/wait${DOCKER_COMPOSE_WAIT_PLATFORM_SUFFIX} /wait
RUN chmod +x /wait

USER $UID:$GID

# Create venv and install Python dependencies
COPY --chown=$UID:$GID ./adl/requirements.txt /adl/requirements.txt
RUN python3 -m venv /adl/venv \
    && /adl/venv/bin/pip install --upgrade pip setuptools wheel

ENV PIP_CACHE_DIR=/tmp/adl_pip_cache
RUN --mount=type=cache,mode=777,target=$PIP_CACHE_DIR,uid=$UID,gid=$GID \
    /adl/venv/bin/pip install -r /adl/requirements.txt

# Copy app code and install the package
COPY --chown=$UID:$GID ./adl /adl/app
RUN /adl/venv/bin/pip install --no-cache-dir /adl/app/

# Copy plugin scripts and TOML manifest parser
COPY --chown=$UID:$GID ./deploy/plugins/*.sh /adl/plugins/
COPY --chown=$UID:$GID ./deploy/plugins/parse_plugins_toml.py /adl/plugins/

# Optionally bake in a plugins.toml manifest (glob trick: no-op if file absent in build context)
COPY --chown=$UID:$GID plugins.tom[l] /adl/

# Drop back to root so install_plugin.sh can chown + gosu
USER root

# Install any plugins specified at build time via ADL_PLUGIN_GIT_REPOS (legacy)
ARG ADL_PLUGIN_GIT_REPOS=""
RUN --mount=type=cache,mode=777,target=$PIP_CACHE_DIR,uid=$UID,gid=$GID \
    if [ -n "$ADL_PLUGIN_GIT_REPOS" ]; then \
        echo "Baking in plugins: $ADL_PLUGIN_GIT_REPOS"; \
        plugin_list=$(echo "$ADL_PLUGIN_GIT_REPOS" | tr ',' ' '); \
        for repo in $plugin_list; do \
            echo "Processing: $repo"; \
            /bin/bash /adl/plugins/install_plugin.sh --git "$repo" || exit 1; \
        done \
    else \
        echo "No plugins specified via ADL_PLUGIN_GIT_REPOS."; \
    fi

# Install any plugins declared in plugins.toml
ARG ADL_PLUGIN_LIST_FILE=""
RUN --mount=type=cache,mode=777,target=$PIP_CACHE_DIR,uid=$UID,gid=$GID \
    manifest="${ADL_PLUGIN_LIST_FILE:-/adl/plugins.toml}"; \
    if [ -f "$manifest" ]; then \
        echo "Installing plugins from manifest: $manifest"; \
        tmpfile=$(mktemp); \
        /adl/venv/bin/python3 /adl/plugins/parse_plugins_toml.py "$manifest" > "$tmpfile" || { rm -f "$tmpfile"; exit 1; }; \
        while IFS= read -r args_line; do \
            [ -z "$args_line" ] && continue; \
            echo "Processing: $args_line"; \
            /bin/bash -c "/adl/plugins/install_plugin.sh $args_line" || { rm -f "$tmpfile"; exit 1; }; \
        done < "$tmpfile"; \
        rm -f "$tmpfile"; \
    else \
        echo "No plugins manifest found at $manifest, skipping."; \
    fi

# Restore non-root user for the remainder of the builder stage
USER $UID:$GID

# =============================================================================
# Runtime base — shared between prod and dev
# =============================================================================
FROM erickotenyo/adl-base:3.12.0 AS runtime-base

ARG UID
ARG GID

ENV DOCKER_USER=adl_docker_user

# Create matching group and user
RUN if getent group $GID > /dev/null; then \
        existing_group=$(getent group $GID | cut -d: -f1); \
        if [ "$existing_group" != "adl_docker_group" ]; then \
            groupmod -n adl_docker_group "$existing_group"; \
        fi; \
    else \
        groupadd -g $GID adl_docker_group; \
    fi && \
    useradd --shell /bin/bash -u $UID -g $GID -o -c "" -m adl_docker_user -l || exit 0

# Install docker-compose wait
ARG DOCKER_COMPOSE_WAIT_VERSION=2.12.1
ARG DOCKER_COMPOSE_WAIT_PLATFORM_SUFFIX=""

ADD https://github.com/ufoscout/docker-compose-wait/releases/download/$DOCKER_COMPOSE_WAIT_VERSION/wait${DOCKER_COMPOSE_WAIT_PLATFORM_SUFFIX} /wait
RUN chmod +x /wait

ENV PATH="/adl/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1


# =============================================================================
# Production target
# =============================================================================
FROM runtime-base AS prod

ARG UID
ARG GID

USER $UID:$GID

# Copy the fully built venv, app code, and plugin scripts from the builder
COPY --from=builder --chown=$UID:$GID /adl/venv /adl/venv
COPY --from=builder --chown=$UID:$GID /adl/app /adl/app
COPY --from=builder --chown=$UID:$GID /adl/plugins /adl/plugins

WORKDIR /adl/app/src/adl

COPY --chown=$UID:$GID ./docker-entrypoint.sh /adl/docker-entrypoint.sh

ENV DJANGO_SETTINGS_MODULE='adl.config.settings.production'

ENTRYPOINT ["/adl/docker-entrypoint.sh"]
CMD ["gunicorn-wsgi"]


# =============================================================================
# Development target
# Expects source code to be bind-mounted at /adl/app.
# Includes dev tools and auto-reload support.
# =============================================================================
FROM runtime-base AS dev

ARG UID
ARG GID

USER $UID:$GID

# Copy venv and plugin scripts from builder — source code is bind-mounted
COPY --from=builder --chown=$UID:$GID /adl/venv /adl/venv
COPY --from=builder --chown=$UID:$GID /adl/plugins /adl/plugins

# Install watchfiles for Celery auto-reload in dev
ENV PIP_CACHE_DIR=/tmp/adl_pip_cache
RUN --mount=type=cache,mode=777,target=$PIP_CACHE_DIR,uid=$UID,gid=$GID \
    /adl/venv/bin/pip install --no-cache-dir watchfiles

# Source is bind-mounted — add it to PYTHONPATH directly
ENV PYTHONPATH="/adl/app/src:$PYTHONPATH"

WORKDIR /adl/app/src/adl

COPY --chown=$UID:$GID ./docker-entrypoint.sh /adl/docker-entrypoint.sh

ENV DJANGO_SETTINGS_MODULE='adl.config.settings.dev'

ENTRYPOINT ["/adl/docker-entrypoint.sh"]
CMD ["django-dev"]