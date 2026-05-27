# Plugin Development Setup

This guide explains how to develop an ADL plugin locally and test it against
the ADL stack. There are two approaches — pick the one that fits your situation.

---

## Flow A — Plugin's own isolated dev stack (recommended for day-to-day development)

Every plugin scaffolded from the boilerplate includes its own
`docker-compose.yml` and `dev.Dockerfile`. This gives you a self-contained
development environment with hot-reload, without needing to touch the main ADL
repository.

### How it works

The `dev.Dockerfile` builds on top of the `adl:latest` base image and installs
your plugin in **editable mode** (`pip install -e`):

```dockerfile
RUN /adl/plugins/install_plugin.sh --folder $ADL_PLUGIN_DIR/adl_my_plugin --dev
```

The `docker-compose.yml` **bind-mounts** the plugin source directory into the
container so any file change is immediately visible to Python — no rebuild
needed:

```yaml
volumes:
  - ./plugins/adl_my_plugin:/adl/plugins/adl_my_plugin
```

### Step-by-step setup

```bash
# 1. Scaffold (if you haven't already)
pip install cookiecutter
cookiecutter gh:wmo-raf/adl --directory plugin-boilerplate
cd adl-my-plugin

# 2. Configure
cp .env.sample .env
# Edit .env — set at minimum:
#   PLUGIN_BUILD_UID=$(id -u)
#   PLUGIN_BUILD_GID=$(id -g)

# 3. Build
docker compose build

# 4. Start
docker compose up -d

# 5. Run migrations (first time and whenever you add new models)
docker compose exec adl adl makemigrations adl_my_plugin
docker compose exec adl adl migrate

# 6. Create an admin user
docker compose exec adl adl createsuperuser
```

Open [http://localhost:8080](http://localhost:8080) (or whatever `PORT` you set in `.env`).

### Development loop

- **Edit** any file under `plugins/adl_my_plugin/src/` on your host.
- **Django** reloads automatically (standard `runserver` behaviour).
- **Celery worker** reloads automatically via `watchfiles`.
- **New models?** Run `makemigrations` + `migrate` in the container.

```bash
# Useful commands during development
docker compose logs -f adl              # watch Django logs
docker compose exec adl adl shell       # Django shell
docker compose exec adl bash            # shell in container
docker compose exec adl adl makemigrations adl_my_plugin
docker compose exec adl adl migrate
```

### When to use this approach

- Building a new plugin from scratch
- Day-to-day iterative development on a single plugin
- You want a clean, isolated database just for this plugin

---

## Flow B — Plugin mounted into the main ADL stack (integration testing)

When you need to test your plugin alongside other **real** plugins running in
the main ADL deployment — for example, to verify it doesn't conflict with
another plugin or to test against production-like data — you can mount your
plugin source directly into the main ADL containers.

This uses `plugins.toml` with the `folder` source type and `dev = true` for
editable install.

### Prerequisites

- The main ADL stack is checked out and working (`adl/`)
- Your plugin lives in a sibling directory (e.g. `adl-plugins/adl-my-plugin/`)

### Step 1 — Create a `docker-compose.override.yml` in the `adl/` directory

This mounts both the `plugins.toml` manifest and your plugin source into all
three backend containers:

```yaml
# adl/docker-compose.override.yml
services:
  adl:
    volumes:
      - ./plugins.toml:/adl/plugins.toml:ro
      - ../adl-plugins/adl-my-plugin/plugins/adl_my_plugin:/adl/dev-plugins/adl_my_plugin
  adl_celery_worker:
    volumes:
      - ./plugins.toml:/adl/plugins.toml:ro
      - ../adl-plugins/adl-my-plugin/plugins/adl_my_plugin:/adl/dev-plugins/adl_my_plugin
  adl_celery_beat:
    volumes:
      - ./plugins.toml:/adl/plugins.toml:ro
      - ../adl-plugins/adl-my-plugin/plugins/adl_my_plugin:/adl/dev-plugins/adl_my_plugin
```

### Step 2 — Create `plugins.toml` in the `adl/` directory

```toml
# plugins.toml

# Your plugin under development (editable install — source changes are live)
[[plugins]]
name = "My Plugin (dev)"
folder = "/adl/dev-plugins/adl_my_plugin"
dev = true

# Other real plugins running alongside (optional)
[[plugins]]
name = "FTP Plugin"
git = "https://github.com/wmo-raf/adl-ftp-plugin.git"
tag = "0.8.9"
```

### Step 3 — Start the stack

```yaml
docker compose up
```

On first startup, ADL reads `plugins.toml`, installs your plugin with
`pip install -e` (because `dev = true`), and installs any other plugins listed.

```{note}
`docker-compose.override.yml` is automatically loaded by Docker Compose when
present alongside `docker-compose.yml` — no extra flags needed.
```

### How hot-reload works

- `dev = true` → `pip install -e` → Python resolves the plugin from the
  bind-mounted directory, not from site-packages.
- Edit any `.py` file in your plugin source on the host.
- If using the **dev stack** (`make dev-up`), Django and the Celery worker
  reload automatically.
- If using the **production stack** (`make up`), gunicorn does not auto-reload;
  restart the container after changes:
  ```bash
  docker compose restart adl adl_celery_worker
  ```

### Run migrations for your plugin

```bash
docker compose exec adl adl makemigrations adl_my_plugin
docker compose exec adl adl migrate
```

### When to use this approach

- Integration testing — verifying your plugin works alongside other plugins
- Testing against the shared ADL database with real data
- Debugging an issue that only appears in the full stack

---

## Comparison

|                   | Flow A (plugin's own compose)                    | Flow B (mounted in main ADL)                                  |
|-------------------|--------------------------------------------------|---------------------------------------------------------------|
| **Setup effort**  | Low — `cp .env.sample .env && docker compose up` | Medium — override file + plugins.toml                         |
| **Hot-reload**    | ✅ Always                                         | ✅ With `dev = true` (dev stack) / manual restart (prod stack) |
| **Other plugins** | ❌ Isolated                                       | ✅ Run alongside real plugins                                  |
| **Database**      | Fresh, plugin-specific                           | Shared ADL database                                           |
| **Best for**      | Day-to-day plugin development                    | Integration testing                                           |

---

## Verifying the editable install

To confirm your plugin is installed in editable mode (pointing to your source):

```bash
docker compose exec adl /adl/venv/bin/pip show adl_my_plugin
```

The `Location` field should point to the mounted path (e.g.
`/adl/dev-plugins/adl_my_plugin`), not to a `site-packages` directory.
