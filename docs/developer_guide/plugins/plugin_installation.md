# Plugin Installation

ADL ships no plugins — each data source is a separate installable package.
There are three ways to install plugins, depending on your use case.

---

## Method 1 — `plugins.toml` manifest (recommended for multiple plugins)

For deployments with two or more plugins, use a `plugins.toml` manifest file.
It lists one plugin per `[[plugins]]` section, supports comments, and is easy
to version-control alongside your `docker-compose.yml`.

### Create the manifest

```bash
cp plugins.toml.sample plugins.toml
```

Edit `plugins.toml` and uncomment the plugins you need:

```toml
# ADL Plugins Manifest

[[plugins]]
name = "FTP Plugin"
git  = "https://github.com/wmo-raf/adl-ftp-plugin.git"
tag  = "0.8.9"

[[plugins]]
name = "TAHMO Plugin"
git  = "https://github.com/wmo-raf/adl-tahmo-plugin.git"
tag  = "0.1.0"

[[plugins]]
name = "Polaris Web Plugin"
git  = "https://github.com/wmo-raf/adl-siapmicros-polarisweb-plugin.git"
tag  = "0.3.0"
enabled = false   # set to false to skip without removing the entry
```

### Available fields

| Field | Description |
|---|---|
| `git = "..."` | GitHub or git repository URL |
| `url = "..."` | Direct `.tar.gz` download URL (alternative to `git`) |
| `folder = "..."` | Absolute path **inside the container** to a local plugin directory |
| `tag = "..."` | Git release tag (e.g. `"0.8.9"`); omit to use the default branch |
| `hash = "..."` | Optional SHA-1 hash for integrity verification |
| `name = "..."` | Display label shown in installation logs |
| `enabled = false` | Skip this entry without deleting it (default: `true`) |
| `dev = true` | Install with `pip install -e` for hot-reload; `folder` only |

### Build-time baking (recommended for production)

Place `plugins.toml` alongside `docker-compose.yml` and rebuild. The file is
copied into the image at build time and each enabled plugin is pip-installed:

```bash
make build
make up
```

### Runtime install via manifest (no rebuild)

To load `plugins.toml` at container startup without rebuilding, mount it via
a `docker-compose.override.yml`:

```yaml
# docker-compose.override.yml
services:
  adl:
    volumes:
      - ./plugins.toml:/adl/plugins.toml:ro
  adl_celery_worker:
    volumes:
      - ./plugins.toml:/adl/plugins.toml:ro
  adl_celery_beat:
    volumes:
      - ./plugins.toml:/adl/plugins.toml:ro
```

Then `docker compose up` — plugins are installed on first container startup.

```{note}
Runtime-installed plugins are stored in the `ADL_PLUGIN_DIR` volume
(`/adl/plugins` by default) and persist across container restarts as long as
the volume exists. If you recreate the container from scratch without the
volume, the plugins will re-install themselves automatically on next startup.
Build-time installation avoids this by baking plugins directly into the image.
```

---

## Method 2 — `ADL_PLUGIN_GIT_REPOS` environment variable (quick, single plugin)

For a single plugin, set `ADL_PLUGIN_GIT_REPOS` in your `.env` before building:

```bash
ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git#0.8.9
```

Then rebuild:

```bash
make build
make up
```

For multiple plugins, separate URLs with commas — but for readability prefer
`plugins.toml` once you have more than one:

```bash
ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git#0.8.9,https://github.com/wmo-raf/adl-tahmo-plugin.git#0.1.0
```

---

## Method 3 — `install-plugin` command (ad-hoc, running container)

Install a plugin into an already-running stack without rebuilding:

```bash
# From a git repo
docker compose exec adl install-plugin --git https://github.com/wmo-raf/adl-ftp-plugin.git

# With a release tag
docker compose exec adl install-plugin --git https://github.com/wmo-raf/adl-ftp-plugin.git#0.8.9

# From a tarball URL
docker compose exec adl install-plugin --url https://example.com/my-plugin.tar.gz

# From a local folder already inside the container
docker compose exec adl install-plugin --folder /adl/plugins/adl_my_plugin
```

---

## Checking installed plugins

```bash
docker compose exec adl list-plugins
```

---

## Uninstalling a plugin

It is highly recommended to back up your data before uninstalling.

1. Remove the plugin from `plugins.toml` (or from `ADL_PLUGIN_GIT_REPOS`)
2. Delete and recreate the container:
   ```bash
   make down
   make build
   make up
   ```

If you uninstall via `exec` without removing the plugin from your configuration,
the plugin will be re-installed on the next container restart because the
configuration still references it.

---

## Pinning to a release tag (recommended for production)

Always pin to a specific release tag in production so that rebuilds are
reproducible and a future breaking change in the plugin does not affect your
deployment until you explicitly upgrade.

In `plugins.toml`:
```toml
[[plugins]]
git = "https://github.com/wmo-raf/adl-ftp-plugin.git"
tag = "0.8.9"
```

Release tags are listed on each plugin's GitHub Releases page.

To upgrade a plugin, update the `tag` value and rebuild:

```bash
make build
make up
```

---

## Local plugin development

See [Plugin Development Setup](plugin_dev_setup.md) for how to develop and
test a plugin from source against the ADL stack.
