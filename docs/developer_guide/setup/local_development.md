# 🛠️ Local Development Setup

This guide walks through getting ADL running on your local machine for
development. The stack runs entirely in Docker so the only hard requirements
on your host are Docker, Docker Compose, Git, and Make.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 20.10 or later
- [Docker Compose](https://docs.docker.com/compose/install/) v2 or later
  (`docker compose`, not `docker-compose`)
- [Git](https://git-scm.com/)
- `make`

Verify your versions:

```bash
docker --version
docker compose version
make --version
```

---

## How the dev stack works

ADL uses two compose files:

| File                     | Purpose                                                                                                     |
|--------------------------|-------------------------------------------------------------------------------------------------------------|
| `docker-compose.yml`     | Base service definitions — used in production and as the foundation for dev                                 |
| `docker-compose.dev.yml` | Dev overrides — switches to the `dev` build target, bind-mounts source code, exposes ports, enables `DEBUG` |

The `Dockerfile` has three build stages:

| Stage     | Used by                  | Description                                                                             |
|-----------|--------------------------|-----------------------------------------------------------------------------------------|
| `builder` | Both                     | Installs all Python dependencies into `/adl/venv`                                       |
| `prod`    | `docker-compose.yml`     | Copies the built venv and app code into the image                                       |
| `dev`     | `docker-compose.dev.yml` | Copies only the venv — source code is bind-mounted from your host, enabling live reload |

The `Makefile` wraps common commands for both stacks. Use `make <target>` for
production and `make dev-<target>` for development.

---

## 1. Clone the Repository

```bash
git clone https://github.com/wmo-raf/adl.git
cd adl
```

---

## 2. Create the Docker Network

ADL's services communicate over a dedicated external Docker network. Create it
once:

```bash
docker network create adl
```

---

## 3. Configure Environment Variables

Copy the sample environment file and edit it:

```bash
cp .env.sample .env
```

The minimum values you must set:

| Variable          | Description                                | Example                         |
|-------------------|--------------------------------------------|---------------------------------|
| `SECRET_KEY`      | Django secret key — any long random string | `change-me-to-something-random` |
| `ADL_DB_USER`     | PostgreSQL username                        | `adl`                           |
| `ADL_DB_PASSWORD` | PostgreSQL password                        | `adl`                           |
| `ADL_DB_NAME`     | PostgreSQL database name                   | `adl`                           |
| `UID`             | Your host user ID                          | `1000`                          |
| `GID`             | Your host group ID                         | `1000`                          |

Find your `UID` and `GID`:

```bash
id -u   # UID
id -g   # GID
```

Setting these ensures files written by the container (static files, media,
backups) are owned by your host user rather than root.

---

## 4. Build the Dev Image

```bash
make dev-build
```

This builds the `dev` target from the `Dockerfile`. The builder stage installs
all Python dependencies into `/adl/venv`. The dev stage copies only the venv
— your local `./adl` directory is bind-mounted into the container at runtime
so code changes are reflected immediately without rebuilding.

If you hit a BuildKit error such as:

```
failed to solve: adl:latest: pull access denied
```

Disable BuildKit and retry:

```bash
DOCKER_BUILDKIT=0 make dev-build
```

---

## 5. Start the Dev Stack

```bash
make dev-up
```

This starts the full stack using both compose files
(`docker-compose.yml` + `docker-compose.dev.yml`). The following services
start:

| Service             | Description                                                        |
|---------------------|--------------------------------------------------------------------|
| `adl_db`            | TimescaleDB (PostgreSQL + PostGIS + TimescaleDB)                   |
| `adl_redis`         | Redis — Celery broker and Django cache                             |
| `adl`               | Django development server (`manage.py runserver`) with auto-reload |
| `adl_celery_worker` | Celery worker with `watchfiles` auto-reload on code changes        |
| `adl_celery_beat`   | Celery beat scheduler                                              |
| `adl_web_proxy`     | Nginx — serves static files and proxies to the app                 |
| `adl_pg_tileserv`   | pg_tileserv — vector tiles from PostGIS                            |

On first startup the `adl` container automatically runs migrations and
collects static files. The services wait for the database and Redis to be
ready before starting (`WAIT_TIMEOUT` defaults to 120 seconds).

Check that everything is up:

```bash
make dev-ps
```

---

## 6. Create a Superuser

```bash
make dev-createsuperuser
```

---

## 7. Access the Application

Open [http://localhost:8000](http://localhost:8000) in your browser.

The Django development server is exposed directly on port `8000` in the dev
stack (bypassing Nginx), which makes it easier to see Django debug pages and
error tracebacks.

The Wagtail admin is at `/adl-admin/` by default (configurable via
`ADL_ADMIN_URL_PATH` in `.env`).

---

## 8. Daily Development Workflow

### Viewing logs

```bash
make dev-logs                 # all services
make dev-app-logs             # Django server only
make dev-worker-logs          # Celery worker only
make dev-beat-logs            # Celery beat only
```

### Opening a shell

```bash
make dev-shell                # bash in the app container
make dev-worker-shell         # bash in the celery worker container
```

### Running management commands

```bash
make dev-migrate              # python manage.py migrate
make dev-makemigrations       # python manage.py makemigrations
```

Or run any arbitrary Django command:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  exec adl adl <command>
```

### Code changes and auto-reload

- **Django server** — reloads automatically when any Python file under
  `./adl/` changes (standard `runserver` behaviour).
- **Celery worker** — reloads automatically via `watchfiles` when any Python
  file under `/adl/app/src/` changes. No manual restart needed.
- **Celery beat** — does not auto-reload; restart it manually if you change
  task schedules:

  ```bash
  make dev-restart
  ```

---

## 9. Stopping and Cleaning Up

```bash
make dev-stop        # stop containers, preserve volumes
make dev-down        # stop and remove containers
```

To also wipe the database (use with care):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
```

---

## 10. Running the Production Stack Locally

If you need to test the production build locally (gunicorn, no bind-mount):

```bash
make build
make up
make createsuperuser
make logs
```

The production stack uses only `docker-compose.yml` and the `prod` build
target. The app is accessible via Nginx on port 80 (or `ADL_WEB_PROXY_PORT`).

---

## Project Layout

The key directories you will work in:

```
adl/
├── src/adl/
│   ├── config/          # Django settings, URLs, WSGI/ASGI
│   ├── core/            # Core models, plugin registry, QC, admin
│   ├── monitoring/      # Task and activity monitoring
│   ├── api/             # REST API
│   └── viewer/          # Data viewer
├── requirements.txt     # Python dependencies
└── pyproject.toml       # Package metadata
```

---

## Makefile Reference

| Command                    | Description                               |
|----------------------------|-------------------------------------------|
| `make dev-build`           | Build the dev image                       |
| `make dev-up`              | Start the dev stack                       |
| `make dev-down`            | Stop and remove dev containers            |
| `make dev-stop`            | Stop dev containers                       |
| `make dev-restart`         | Restart dev containers                    |
| `make dev-ps`              | List running dev containers               |
| `make dev-logs`            | Tail logs for all dev services            |
| `make dev-app-logs`        | Tail Django server logs                   |
| `make dev-worker-logs`     | Tail Celery worker logs                   |
| `make dev-beat-logs`       | Tail Celery beat logs                     |
| `make dev-shell`           | Open bash in the app container            |
| `make dev-worker-shell`    | Open bash in the worker container         |
| `make dev-migrate`         | Run database migrations                   |
| `make dev-makemigrations`  | Create new migrations                     |
| `make dev-createsuperuser` | Create an admin user                      |
| `make build`               | Build the production image                |
| `make up`                  | Start the production stack                |
| `make down`                | Stop the production stack                 |
| `make logs`                | Tail production logs                      |
| `make shell`               | Open bash in the production app container |
| `make migrate`             | Run migrations in production              |

---

## Troubleshooting

**Services not starting — waiting for database**

The `adl` container waits for `adl_db:5432` before starting. If the database
takes longer than `WAIT_TIMEOUT` (default 120 seconds), increase it in `.env`:

```bash
WAIT_TIMEOUT=300
```

**Static files returning 404**

Run collectstatic manually:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  exec adl adl collectstatic --noinput
```

**Permission errors on mounted volumes**

Confirm `UID` and `GID` in `.env` match your host user, then rebuild:

```bash
echo "UID=$(id -u)" >> .env
echo "GID=$(id -g)" >> .env
make dev-build
make dev-up
```

**Port 8000 already in use**

Another process is using port 8000. Find and stop it, or change the exposed
port in `docker-compose.dev.yml`.

---

## Developing plugins

This guide covers developing the ADL **core**. If you want to develop a
**plugin** (a data source adapter), see
[Plugin Development Setup](../plugins/plugin_dev_setup.md) — plugins have
their own isolated docker-compose environment and a separate workflow for
integration testing against the full ADL stack.
