# ADL - Automated Data Loader

## Project Overview

ADL is a Django-based platform that automates periodic observation data collection from Automatic Weather Station (AWS)
networks and dispatches it to receiving systems (WIS2Box, CDMSs, FTP, etc.). Deployed across 26+ African National
Meteorological and Hydrological Services (NMHSs). The system is plugin-driven: each vendor/data source is a separate
installable package.

## Tech Stack

- **Python 3.10+** / **Django 5.0+** — core application
- **Wagtail 7.3.1** — admin UI and CMS
- **Celery** + **Redis** — async task queue and scheduler (`django-celery-beat`)
- **Django REST Framework** + **drf-spectacular** — REST API with OpenAPI docs
- **PostgreSQL** + **TimescaleDB** + **PostGIS** — time-series and geospatial data
- **Django Channels** / **Daphne** — WebSocket support
- **Pydantic 2** — data validation in plugin interfaces
- **Pandas** — observation data processing
- **MinIO** — S3-compatible object storage (WIS2Box integration)
- **Vue.js** — monitoring dashboard and map viewer UIs

## Key Directories

```
adl/src/adl/
├── core/              # Domain models, plugin base, QC pipeline, dispatchers, Celery tasks
│   ├── models.py      # Network, Station, ObservationRecord, DispatchChannel (polymorphic)
│   ├── registries.py  # Plugin base class and PluginRegistry
│   ├── registry.py    # Generic Registry/Instance base classes
│   ├── tasks.py       # Celery tasks for ingestion and dispatch
│   ├── dispatchers/   # Data dispatch implementations (wis2box, etc.)
│   ├── qc/            # Quality control pipeline and validators
│   └── logging.py     # TaskLogger for audit trails
├── api/               # DRF REST API (views, serializers, auth)
├── monitoring/        # Activity logs, monitoring UI (Vue.js)
├── viewer/            # Map viewer (Vue.js)
├── wis2box/           # WIS2Box integration settings
└── config/            # Django settings (base/dev/production), Celery, URLs

plugin-boilerplate/    # Cookiecutter template for generating new plugins
docs/                  # Sphinx documentation source
```

## Build & Run Commands

All commands run via Docker Compose through the root `Makefile`.

**Development:**

```bash
make dev-up              # Start dev stack
make dev-down            # Stop dev stack
make dev-logs            # Stream all logs
make dev-app-logs        # Stream app logs only
make dev-shell           # Bash shell in app container
make dev-migrate         # Run Django migrations
make dev-makemigrations  # Create new migrations
make dev-createsuperuser # Create admin user
```

**Production:**

```bash
make up / make down / make restart
make build               # Rebuild Docker image
make migrate
make shell / make worker-shell / make beat-shell
```

**Inside a container** (`adl` is the Django management command entry point per `pyproject.toml`):

```bash
adl migrate
adl shell
adl test
```

**Tests** (Django test runner, run against the dev stack):

```bash
make dev-test                                        # full suite
make dev-test TEST_ARGS=adl.core.tests.test_dates    # narrow to a module/class
```

Tests are Django `TestCase` classes under `adl/src/adl/core/tests/` (factories via
`factory_boy` in `factories.py`, shared stubs in `helpers.py`). Inside the container the
equivalent is `adl test --keepdb -t /adl/app/src adl`.

## Additional Documentation

Check these files when working on the relevant areas:

| Topic                                     | File                                                                             |
|-------------------------------------------|----------------------------------------------------------------------------------|
| Architectural patterns & design decisions | [.claude/docs/architectural_patterns.md](.claude/docs/architectural_patterns.md) |