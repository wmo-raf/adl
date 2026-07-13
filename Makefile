# ======================
# Compose Definitions
# ======================

PROD = -f docker-compose.yml
DEV  = -f docker-compose.yml -f docker-compose.dev.yml

DC     = docker compose $(PROD)
DEV_DC = docker compose $(DEV)

# Main services (match docker-compose.yml)
APP    ?= adl
WORKER ?= adl_celery_worker
BEAT   ?= adl_celery_beat

LOG_ARGS ?= --tail 100

.PHONY: \
	up down stop restart build ps logs \
	app-logs worker-logs beat-logs \
	shell worker-shell beat-shell \
	migrate makemigrations createsuperuser \
	dev-up dev-down dev-stop dev-restart dev-build dev-ps dev-logs \
	dev-app-logs dev-worker-logs dev-beat-logs \
	dev-shell dev-worker-shell dev-beat-shell \
	dev-migrate dev-makemigrations dev-createsuperuser

# ======================
# PROD
# ======================

up:
	$(DC) up -d

down:
	$(DC) down

stop:
	$(DC) stop

restart:
	$(DC) restart

build:
	$(DC) build

ps:
	$(DC) ps

logs:
	$(DC) logs -f $(LOG_ARGS)

app-logs:
	$(DC) logs -f $(APP) $(LOG_ARGS)

worker-logs:
	$(DC) logs -f $(WORKER) $(LOG_ARGS)

beat-logs:
	$(DC) logs -f $(BEAT) $(LOG_ARGS)

shell:
	$(DC) exec $(APP) bash

worker-shell:
	$(DC) exec $(WORKER) bash

beat-shell:
	$(DC) exec $(BEAT) bash

migrate:
	$(DC) exec $(APP) adl migrate

makemigrations:
	$(DC) exec $(APP) adl makemigrations

createsuperuser:
	$(DC) exec $(APP) adl createsuperuser


# ======================
# DEV
# ======================

dev-up:
	$(DEV_DC) up

dev-down:
	$(DEV_DC) down

dev-stop:
	$(DEV_DC) stop

dev-restart:
	$(DEV_DC) restart

dev-build:
	$(DEV_DC) build

dev-ps:
	$(DEV_DC) ps

dev-config:
	$(DEV_DC) config

dev-logs:
	$(DEV_DC) logs -f $(LOG_ARGS)

dev-app-logs:
	$(DEV_DC) logs -f $(APP) $(LOG_ARGS)

dev-worker-logs:
	$(DEV_DC) logs -f $(WORKER) $(LOG_ARGS)

dev-beat-logs:
	$(DEV_DC) logs -f $(BEAT) $(LOG_ARGS)

dev-shell:
	$(DEV_DC) exec $(APP) bash

dev-worker-shell:
	$(DEV_DC) exec $(WORKER) bash

dev-beat-shell:
	$(DEV_DC) exec $(BEAT) bash

dev-migrate:
	$(DEV_DC) exec $(APP) adl migrate

dev-makemigrations:
	$(DEV_DC) exec $(APP) adl makemigrations

dev-createsuperuser:
	$(DEV_DC) exec $(APP) adl createsuperuser

# Run the Django test suite inside the app container.
# -t pins the discovery top level so tests import as adl.*, regardless of workdir.
# Pass TEST_ARGS to narrow the run, e.g. TEST_ARGS=adl.core.tests.test_dates
TEST_ARGS ?= adl

dev-test:
	@export $$(grep -v '^[[:space:]]*#' .env | grep -v '^[[:space:]]*$$' | grep -v '^UID=' | xargs) && \
	$(DEV_DC) exec \
	  -e "DATABASE_URL=timescalegis://$$ADL_DB_USER:$$ADL_DB_PASSWORD@adl_db:5432/$$ADL_DB_NAME" \
	  $(APP) adl test --keepdb -t /adl/app/src $(TEST_ARGS)

