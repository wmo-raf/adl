# This a dev image for testing your plugin when installed into the wis2box-adl image
FROM wis2box_adl:latest AS base

FROM wis2box_adl:latest

USER root

ARG PLUGIN_BUILD_UID
ENV PLUGIN_BUILD_UID=${PLUGIN_BUILD_UID:-9999}
ARG PLUGIN_BUILD_GID
ENV PLUGIN_BUILD_GID=${PLUGIN_BUILD_GID:-9999}

# If we aren't building as the same user that owns all the files in the base
# image/installed plugins we need to chown everything first.
COPY --from=base --chown=$PLUGIN_BUILD_UID:$PLUGIN_BUILD_GID /wis2box_adl /wis2box_adl
RUN usermod -u $PLUGIN_BUILD_UID $DOCKER_USER

# Install your dev dependencies manually.
COPY --chown=$PLUGIN_BUILD_UID:$PLUGIN_BUILD_GID ./plugins/adl_siapmicros_plugin/requirements/dev.txt /tmp/plugin-dev-requirements.txt
RUN . /wis2box_adl/venv/bin/activate && pip3 install -r /tmp/plugin-dev-requirements.txt

COPY --chown=$PLUGIN_BUILD_UID:$PLUGIN_BUILD_GID ./plugins/adl_siapmicros_plugin/ $WIS2BOX_ADL_PLUGIN_DIR/adl_siapmicros_plugin/
RUN . /wis2box_adl/venv/bin/activate && /wis2box_adl/plugins/install_plugin.sh --folder $WIS2BOX_ADL_PLUGIN_DIR/adl_siapmicros_plugin --dev

USER $PLUGIN_BUILD_UID:$PLUGIN_BUILD_GID
ENV DJANGO_SETTINGS_MODULE='wis2box_adl.config.settings.dev'
CMD ["django-dev"]