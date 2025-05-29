# Plugin Structure

An ADL Plugin is fundamentally a folder named after the plugin. The folder should be
a [Django/Wagtail App](https://docs.djangoproject.com/en/5.1/ref/applications/)

## Initialize your plugin from the plugin template

The plugin template is a [cookiecutter](https://cookiecutter.readthedocs.io/en/stable/installation.html) template that
generates a plugin with the required structure and files. This ensures that the plugin follows the expected structure
and can be easily installed into the adl core application.

To instantiate the template, execute the following commands from the directory where you want to create the plugin:

```sh
pip install cookiecutter
cookiecutter gh:wmo-raf/adl --directory plugin-boilerplate
```

For more details on using the plugin boilerplate, you can check * :doc:`plugins/plugin_boilerplate` on
creating a plugin using the plugin boilerplate.

## Plugin Installation API

A adl docker image contains the following bash scripts that are used to install plugins. They can be used
to install a plugin into an existing adl container at runtime. `install_plugin.sh` can be used to install a
plugin from an url, a git repo or a local folder on the filesystem.

You can find these scripts in the following locations in the built images:

1. `/adl/plugins/install_plugin.sh`

On this repo, you can find the scripts in the `deploy/plugins` folder.

These scripts expect an adl plugin to follow the conventions described below:

## Plugin File Structure

The `install_plugin.sh` script expect your plugin to have a specific structure as follows:

```
├── plugin_name
│  ├── adl_plugin_info.json (A simple json file containing info about your plugin)
|  ├── setup.py
|  ├── build.sh (Called when installing the plugin in a Dockerfile/container)
|  ├── runtime_setup.sh (Called on first runtime startup of the plugin)
|  ├── uninstall.sh (Called when uninstalling the plugin in a container)
|  ├── src/plugin_name/src/config/settings/settings.py (Optional Django setting file)
```

The folder contains three bash files which will be automatically called by adl's plugin scripts during
installation and uninstallation of the plugin. You can use these scripts to perform extra build steps, installation of
packages and other docker container build steps required by your plugin.

1. `build.sh`: Called on container startup if a runtime installation is occurring.
2. `runtime_setup.sh`: Called the first time a container starts up after the plugin has been installed, useful for
   running superuser commands on the container.
3. `uninstall.sh`: Called on uninstall, the database will be available and so any backwards migrations should be run
   here.

## The plugin info file

The `adl_plugin_info.json` file is a json file, in your root plugin folder, containing metadata about your
plugin. It should have the following JSON structure:

```json
{
  "name": "TODO",
  "version": "TODO",
  "description": "TODO",
  "author": "TODO",
  "author_url": "TODO",
  "url": "TODO",
  "license": "TODO",
  "contact": "TODO"
}
```

## Expected plugin structure when installing from a git repository

When installing a plugin from git,the repo should contain a single plugins folder, inside which there should a single
plugin folder following the structure above and has the same name as your plugin.

By default, the `plugin boilerplate` generates a repository with this structure.

For example a conforming git repo should contain something like:

```
├─ * (an outermost wrapper directory named anything is allowed but not required) 
│  ├── plugins/ 
│  │  ├── plugin_name
│  |  |  ├── adl_plugin_info.json
|  |  |  ├── setup.py
|  |  |  ├── build.sh
|  |  |  ├── runtime_setup.sh
|  |  |  ├── uninstall.sh
|  |  |  ├── src/plugin_name/src/config/settings/settings.py (Optional Django setting file)
```

## Plugin Boilerplate

With the plugin boilerplate you can easily create a new plugin and setup a docker development environment that installs
adl as a dependency. This can easily be installed via cookiecutter.

### Creating a plugin

To use the plugin boilerplate you must first install
the [Cookiecutter](https://cookiecutter.readthedocs.io/en/stable/installation.html) tool (`pip install cookiecutter`).

Once you have installed Cookiecutter you can execute the following command to create a new ADL plugin from our
template. In this guide we will name our plugin “My ADL Plugin”, however you can choose your own plugin name
when prompted to by Cookiecutter.

```{note}
The python module depends on your chosen plugin name. If we for example go with “My ADL Plugin” the Django app 
name should be my_adl_plugin
```

```sh
cookiecutter gh:wmo-raf/adl --directory plugin-boilerplate
project_name [My ADL Plugin]: 
project_slug [my-adl-plugin]: 
project_module [my_adl_plugin]:
```

If you do not see any errors it means that your plugin has been created.

### Starting the development environment

Now to start your development environment please run the following commands:

```sh
cd my-adl-plugin
# Enable Docker buildkit
export COMPOSE_DOCKER_CLI_BUILD=1
export DOCKER_BUILDKIT=1
# Set these variables so the images are built and run with the same uid/gid as your 
# user. This prevents permission issues when mounting your local source into
# the images.
export PLUGIN_BUILD_UID=$(id -u)
export PLUGIN_BUILD_GID=$(id -g)
# You can optionally `export COMPOSE_FILE=docker-compose.dev.yml` so you don't need to 
# use the `-f docker-compose.dev.yml` flag each time.
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml logs -f