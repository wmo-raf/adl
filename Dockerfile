# syntax = docker/dockerfile:1.5

# use osgeo gdal ubuntu small 3.7 image.
# pre-installed with GDAL 3.7.0 and Python 3.10.6
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.7.0 as base

ARG UID
ENV UID=${UID:-9999}
ARG GID
ENV GID=${GID:-9999}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# We might be running as a user which already exists in this image. In that situation
# Everything is OK and we should just continue on.
RUN groupadd -g $GID wis2box_adl_docker_group || exit 0
RUN useradd --shell /bin/bash -u $UID -g $GID -o -c "" -m wis2box_adl_docker_user -l || exit 0
ENV DOCKER_USER=wis2box_adl_docker_user

ENV POSTGRES_VERSION=15

# install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    lsb-release \
    ca-certificates \
    curl \
    libgeos-dev \
    libpq-dev \
    python3-pip --fix-missing \
    gosu \
    git \
    && echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && curl --silent https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && apt-get update \
    && apt-get install -y postgresql-client-$POSTGRES_VERSION \
    python3-dev \
    python3-venv \
    && apt-get autoclean \
    && apt-get clean \
    && apt-get autoremove \
    && rm -rf /var/lib/apt/lists/*

# install docker-compose wait
ADD https://github.com/ufoscout/docker-compose-wait/releases/download/2.12.1/wait /wait
RUN chmod +x /wait

USER $UID:$GID

# Install  dependencies into a virtual env.
COPY --chown=$UID:$GID ./wis2box_adl/requirements.txt /wis2box_adl/requirements.txt
RUN python3 -m venv /wis2box_adl/venv

ENV PIP_CACHE_DIR=/tmp/wis2box_adl_pip_cache
RUN --mount=type=cache,mode=777,target=$PIP_CACHE_DIR,uid=$UID,gid=$GID . /wis2box_adl/venv/bin/activate && pip3 install  -r /wis2box_adl/requirements.txt

COPY --chown=$UID:$GID ./wis2box_adl /wis2box_adl/app

WORKDIR /wis2box_adl/app/src/wis2box_adl

# Ensure that Python outputs everything that's printed inside
# the application rather than buffering it.
ENV PYTHONUNBUFFERED 1

COPY --chown=$UID:$GID ./deploy/plugins/*.sh /wis2box_adl/plugins/

RUN /wis2box_adl/venv/bin/pip install --no-cache-dir -e /wis2box_adl/app/

COPY --chown=$UID:$GID ./docker-entrypoint.sh /wis2box_adl/docker-entrypoint.sh

ENV DJANGO_SETTINGS_MODULE='wis2box_adl.config.settings.dev'

# Add the venv to the path
ENV PATH="/wis2box_adl/venv/bin:$PATH"

ENTRYPOINT ["/wis2box_adl/docker-entrypoint.sh"]

CMD ["gunicorn-wsgi"]