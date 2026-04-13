# 🛠️ Installation

This guide covers installing ADL on a server or local machine for production
use. If you want to set up a development environment, see
[Local Development Setup](developer_guide/setup/local_development.md) instead.

---

## Prerequisites

- [Docker Engine](https://docs.docker.com/engine/install/) 20.10 or later
- [Docker Compose](https://docs.docker.com/compose/install/) v2 or later
  (`docker compose`, not `docker-compose`)
- [Git](https://git-scm.com/)
- `make`

Verify your versions before proceeding:

```bash
docker --version
docker compose version
make --version
```

---

## 1. Clone the Repository

```bash
git clone https://github.com/wmo-raf/adl.git
cd adl
```

---

## 2. Configure Environment Variables

Copy the sample environment file:

```bash
cp .env.sample .env
```

Open it in your editor and set the required values:

```bash
nano .env
```

**Required variables — the system will not start without these:**

| Variable           | Description                                                   | How to get it                                       |
|--------------------|---------------------------------------------------------------|-----------------------------------------------------|
| `SECRET_KEY`       | Django cryptographic signing key                              | Generate one at [djecrety.ir](https://djecrety.ir/) |
| `ALLOWED_HOSTS`    | Comma-separated list of hostnames/IPs this server responds to | Your server's domain or IP, e.g. `adl.example.org`  |
| `ADL_DB_USER`      | PostgreSQL username                                           | Choose any value, e.g. `adl`                        |
| `ADL_DB_PASSWORD`  | PostgreSQL password                                           | Choose a strong password                            |
| `ADL_DB_NAME`      | PostgreSQL database name                                      | Choose any value, e.g. `adl`                        |
| `UID`              | User ID to run the containers as                              | Run `id -u` in your terminal                        |
| `GID`              | Group ID to run the containers as                             | Run `id -g` in your terminal                        |
| `ADL_NETWORK_NAME` | Docker network name                                           | Use `adl` (matches step 3)                          |

**Commonly changed optional variables:**

| Variable               | Default | Description                                            |
|------------------------|---------|--------------------------------------------------------|
| `ADL_WEB_PROXY_PORT`   | `80`    | Port Nginx listens on. Change if port 80 is taken.     |
| `ADL_PLUGIN_GIT_REPOS` | —       | Plugin repo URLs to install at build time (see step 6) |
| `LANGUAGE_CODE`        | `en`    | Interface language: `en`, `fr`, `ar`, `es`, `sw`, `am` |
| `TIME_ZONE`            | `UTC`   | Server timezone                                        |
| `WAGTAIL_SITE_NAME`    | `ADL`   | Site name shown in the admin header                    |

For the full list of variables see [Environmental Variables](environmental_variables.md).

---

## 3. Create the Docker Network

ADL's services communicate over a dedicated Docker network. Create it once:

```bash
docker network create adl
```

Ensure `ADL_NETWORK_NAME=adl` is set in your `.env`.

---

## 4. Create Volume Directories and Set Permissions

Create the directories Docker will mount:

```bash
mkdir -p ./docker/static ./docker/media ./docker/db_data ./docker/backup
```

Set ownership to match the `UID` and `GID` values in your `.env`:

```bash
sudo chown <UID>:<GID> ./docker/static ./docker/media ./docker/backup
```

The database volume requires UID `1000` (fixed by the TimescaleDB image):

```bash
sudo chown 1000:1000 ./docker/db_data
```

---

## 5. Build and Start

Build the production image:

```bash
make build
```

Start all services in the background:

```bash
make up
```

Check that all containers are running:

```bash
make ps
```

You should see `adl`, `adl_db`, `adl_redis`, `adl_celery_worker`,
`adl_celery_beat`, `adl_web_proxy`, and `adl_pg_tileserv` all running.

On first startup, ADL automatically runs database migrations and collects
static files. Watch the logs until the startup completes:

```bash
make app-logs
```

---

## 6. Install Plugins

```{important}
ADL collects no observation data without at least one plugin installed.
However, **you can skip this step** if you just want to explore the interface
or test the core system first — the application runs fine without plugins and
you can install them later at any time.
```

### Choose which plugins you need

ADL does not bundle any plugins — each data source has its own plugin that
you install separately. Before installing, check the
[Available Plugins](plugins_list.md) page to find the right plugin for your
weather station network or data source.

```{warning}
Checking the available plugins page to identify the correct plugin that you need to install. 
Each NMHS deployment uses different plugins depending on their AWS vendor. 
Installing the wrong plugin wastes time and does nothing harmful, but it won't collect any data.
```

### Build-time installation (recommended for production)

The cleanest approach is to bake plugins into the image at build time. Set
`ADL_PLUGIN_GIT_REPOS` in your `.env` before building:

```bash
# Single plugin — replace with the URL for your plugin
ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git
```

For multiple plugins, separate URLs with commas:

```bash
ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git,https://github.com/wmo-raf/adl-tahmo-plugin.git
```

**Pinning to a release tag (recommended)**

By default, the latest commit on the default branch is installed. For
production it is better to pin to a specific release tag so that rebuilds
are reproducible. Append `#TAG` to the URL:

```bash
ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git#v1.2.0
```

Release tags are listed on each plugin's GitHub Releases page. Using a tag
means a future breaking change in the plugin will not affect your deployment
until you explicitly upgrade.

Then rebuild and restart:

```bash
make build
make up
```

### Runtime installation

To install a plugin into a running stack without rebuilding:

```bash
docker compose exec adl install-plugin --git https://github.com/wmo-raf/adl-ftp-plugin.git
```

With a release tag:

```bash
docker compose exec adl install-plugin --git https://github.com/wmo-raf/adl-ftp-plugin.git#v1.2.0
```

From a tarball URL:

```bash
docker compose exec adl install-plugin --url https://example.com/my-plugin.tar.gz
```

```{note}
Runtime-installed plugins are stored in the `ADL_PLUGIN_DIR` volume
(`/adl/plugins` by default). They persist across container restarts as long
as the volume exists. If you recreate the container from scratch without the
volume, you will need to reinstall them. Build-time installation avoids this
by baking the plugin directly into the image.
```

List installed plugins at any time:

```bash
docker compose exec adl list-plugins
```

For full details on plugin installation options see
[Plugin Installation](developer_guide/plugins/plugin_installation.md).

---

## 7. Create a Superuser

```bash
make createsuperuser
```

Follow the prompts to set a username, email, and password.

---

## 8. Verify the Installation

Open your browser and navigate to:

```
http://<your-server-address>/adl-admin/
```

Log in with the superuser credentials you just created. You should see the
ADL Wagtail admin dashboard.

The admin URL path defaults to `adl-admin/`. If you changed
`ADL_ADMIN_URL_PATH` in `.env`, use that path instead.

---

## Useful Commands

```bash
make up               # Start all services
make down             # Stop and remove containers
make stop             # Stop containers (preserve state)
make restart          # Restart all services
make logs             # Tail logs for all services
make app-logs         # Tail Django application logs
make worker-logs      # Tail Celery worker logs
make ps               # List running containers
make shell            # Open a bash shell in the app container
make migrate          # Run database migrations manually
make createsuperuser  # Create an admin user
```

---

## Upgrading

To upgrade to a newer version of ADL:

```bash
git pull
make build
make up
```

Migrations run automatically on startup. If you have plugins installed via
`ADL_PLUGIN_GIT_REPOS`, they are re-installed during the build and their
migrations also run on startup.

To upgrade a plugin to a newer release tag, update the tag in `.env` and
rebuild:

```bash
# Before: ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git#v1.2.0
# After:
ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git#v1.3.0
make build
make up
```

---

## Troubleshooting

**Containers not starting**

Check which service is failing:

```bash
make logs
```

The most common causes are a missing `SECRET_KEY`, incorrect database
credentials, or the Docker network not existing. Confirm the network exists:

```bash
docker network ls | grep adl
```

**Permission errors on volumes**

Confirm `UID` and `GID` in `.env` match your host user and re-apply
ownership:

```bash
sudo chown $(id -u):$(id -g) ./docker/static ./docker/media ./docker/backup
```

**Port 80 already in use**

Change `ADL_WEB_PROXY_PORT` in `.env` and restart:

```bash
make down
make up
```

**Static files not loading**

Run collectstatic manually:

```bash
make shell
adl collectstatic --noinput
```
