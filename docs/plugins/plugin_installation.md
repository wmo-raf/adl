# Plugin Installation

There are a few ways to install a plugin:

## Using environment variable

This method assumes you already have the ADL docker compose services running.

You can use the `ADL_PLUGIN_GIT_REPOS` env variables when using the ADL docker images to install
plugins on startup.

- The `ADL_PLUGIN_GIT_REPOS` should be a comma separated list of `https git repo` urls which will be used to
  download and install plugins on startup.

After setting the environment variable, you can start the docker container using the following command:

```sh
docker compose up 
```

These variables will only trigger and installation when found on startup of the container. To uninstall a plugin you
must still manually follow the instructions below.

### Caveats when installing into an existing container

If you ever delete the container you’ve installed plugins into at runtime and re-create it, the new container is created
from the base adl docker image which does not have any plugins installed.

However, when a plugin is installed at runtime or build time it is stored in the `ADL_PLUGIN_DIR`which by default is
`/adl/plugins` container folder which should be mounted inside a docker volume. On startup if a plugin is found in
this directory which has not yet been installed into the current container it will be re-installed.

As long as you re-use the same data volume, you should not lose any plugin data even if you remove and re-create the
containers. The only effect is on initial container startup you might see the plugins re-installing themselves if you
re-created the container from scratch.

### Uninstalling a plugin installed using an environment variable

- It is highly recommended that you backup your data before uninstalling a plugin.

- To uninstall a plugin you installed using one of `ADL_PLUGIN_GIT_REPOS`  you need to make sure
  that you delete and recreate the container with the plugin removed from the corresponding environment variable. If you
  fail to do so and just uninstall-plugin using exec and restart, the plugin will be re-installed after the restart as
  the environment variable will still contain the old plugin

### Checking which plugins are already installed

Use the `list-plugins` command or built in /adl/plugins/list_plugins.sh script to check what plugins are currently
installed.
