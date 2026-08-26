# {{ cookiecutter.project_name }}

{{ cookiecutter.project_description }}

## Getting started

### Prerequisites

- Docker and Docker Compose installed on your machine.
- Git installed on your machine.

### Install and build the ADL Core Image

The {{ cookiecutter.project_name }} is a module intended to be installed in an [ADL](https://github.com/wmo-raf/adl)
instance. This means that you need to first get the core ADL system and build it on your local development environment.

You can follow the instructions on the [ADL core repository](https://github.com/wmo-raf/adl) to install and build the
ADL core image

### Install {{ cookiecutter.project_name }}

The `dev.Dockerfile` file uses the `adl` image as a base image. The `{{ cookiecutter.project_name }}` is
installed during the build process. Using docker mounted volumes, the plugin is editable such that any changes made to
the code trigger Django to reload the development server, allowing you to see the changes as you develop

1. Clone the plugin repository:

```bash
git clone https://github.com/wmo-raf/{{cookiecutter.project_slug}}.git
cd {{cookiecutter.project_slug}}
```

2. Create a `.env` file using the provided `.env.sample` file:

```bash
cp .env.sample .env
```

3. Edit the `.env` file to set the required environment variables

```bash
nano .env
```

You can use the default values provided in the `.env.sample` file, but be sure to set the following correctly:

- `PLUGIN_BUILD_UID`: The UID of the user that will run the plugin inside the container
- `PLUGIN_BUILD_GID`: The GID of the user that will run the plugin inside the container

You can find the UID and GID of your user by running the following command:

```bash
id -u
id -g
```

4. Build the plugin image:

```bash
docker compose build
```

If you are getting errors like
`failed to solve: adl:latest: failed to resolve source metadata for docker.io/library/adl:latest: pull access denied`,
you might need to disable `DOCKER_BUILDKIT` when building the image.

You can do this by running the following

```bash
DOCKER_BUILDKIT=0  docker compose build
```

5. Start the plugin:

```bash
docker compose up
```

If everything is set up correctly, you should see the plugin starting up and listening for incoming requests. You can
access the plugin at `http://localhost:8000`. The port number can be changed using the `PORT` environment variable in
the `.env`. The default port is `8000`.

6. Create superuser

```bash
docker compose exec adl adl createsuperuser
```

The `adl`command is shorthand for `python manage.py` command. You can use it to run any Django management command
inside the container.



## Releasing

Tag releases with a **bare version number** — `0.2.0`, never `v0.2.0`.

An ADL deployment installs this plugin by pinning the tag verbatim in its
`plugins.toml`:

```toml
[[plugins]]
name = "{{ cookiecutter.project_name }}"
git  = "https://github.com/wmo-raf/{{ cookiecutter.project_slug }}.git"
tag  = "0.2.0"
```

Every ADL plugin tags this way, so the field reads the same everywhere and
there is no stray `v` to drop or add by mistake. (ADL core and `adl-agent`
tag with a `v`; they are not installed through `plugins.toml`, and the
agent's CI depends on the prefix. Don't copy their style here.)

Cut the release with `gh`, which creates the tag server-side from the same
field as the release name:

```bash
gh release create 0.2.0 --title "{{ cookiecutter.project_name }} 0.2.0" --notes "..."
```

Prefer this over `git tag -a v0.2.0 && git push origin v0.2.0` — tagging
locally is where a stray `v` gets typed from muscle memory.

Before tagging, make sure `VERSION` in `plugins/{{ cookiecutter.project_module }}/setup.py`
matches the tag.
