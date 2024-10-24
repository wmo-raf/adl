# WIS2Box Automated Data Loader

Wagtail based tool for automating periodic Observation data ingestion into WIS2Box node, from Automatic and or Manual
Weather Stations.

## 📚 Background

[WIS2 in a box](https://github.com/wmo-im/wis2box) (wis2box) is a Free and Open Source (FOSS) Reference Implementation
of a WMO WIS2 Node. The project provides a plug and play toolset to ingest, process, and publish weather/climate/water
data using standards-based approaches in alignment with the WIS2 principles. WIS2 in a box enables World Meteorological
Organization (WMO) members to publish and download data through the WIS2 network.

One of the critical steps in the WIS2 data flow is the ingestion of realtime data from observation stations (either
Manual or Automatic Weather Stations) into a WIS2 node. Setting up wis2box is one thing, ensuring that the data from
stations is periodically ingested into the node in a timely way is another. Countries can develop their own tools and
scripts to automate this process, but this can be time-consuming and costly especially for developing countries that
have a 'cocktail' of different AWS vendors.

One of the challenges confronting NMHSs in Africa in observation data management is the disparities between the
different station types provided by different donors. This has given rise to barriers in using the data collected by
Automated Weather Stations in a harmonized way.

These disparities include major differences in the way the data from various AWS vendors are formatted and stored, which
result in poorly coordinated, fragmented, and unharmonized datasets coming from different AWS networks.

Given the broad category of AWS vendors and types that share similar purpose of collecting weather observation data,
with different storage structure, having a monolithic application would be too large and complex to accommodate all the
possible AWS vendor types in Africa NMHSs.

One solution would be to create a core application that only knows about the high-level information of the AWS network,
and then develop small units (plugins) to handle the complexities of each AWS vendor type.

This project is an implementation of such a solution.

![WIS2Box ADL Data Flow](docs/_static/images/wis2box-data-flow-adl.png)

## 📜 Introduction

WIS2Box Automated Data Loader (ADL) is a plugin based system that defines an architecture for implementing wis2box data
loaders for different AWS vendors.

The core application, which is under this repository, defines a form of contract that vendor specific plugins can extend
and provides an abstraction layer for integration of the plugins.

At a high level, this core application is made up of the following components:

- **Network component**– Table and logic with details about the AWS/Manual Stations Network. A network is a
  representation of
  a given AWS vendor type and its stations, or a collection of manual stations. When creating a network, an installed
  plugin must be associated with it to make it useful.

- **Station component** – Table and logic with details for each station, linking to different networks, including
  defining the data parameters to be used when preparing data for ingestion into WIS2Box, and a way to load stations for
  a network, from official sources like [OSCAR Surface](https://oscar.wmo.int/surface)

- **Database** – Postgres database where the system persists its data

- **Plugin Abstract** – Class that defines a contract that plugins must adhere to. This is the glue that brings diverse
  types
  of AWS vendors and sources together.

- **Background tasks** for uploading data into WIS2Box node – Each network is associated with a plugin. Since a plugin
  is standard and defines known methods of exposing its data, background tasks are created for each network that enable
  continuous checking on availability of new data and consequently the ingestion of it into a wis2box node.

On the other hand, a plugin will have the following components and features:

- **Vendor/Source specific implementation** – Depending on the vendor type, the plugin will implement the specific
  features and logic it needs to be able to communicate with its storage on a periodic basis and determine if there is
  new data to be ingested.

- **Must adhere to the plugin contract** – For the plugin to be useful and accepted by the core application, it must
  implement the plugin features as defined by the core application plugin contract.

- **Linking**- A plugin should provide a user interface for connecting its stations and data parameters to the stations
  and data parameters defined in the core application. At the implementation level, a plugin can add its own tables to
  the core application database if it requires to store information needed to link its stations with the stations
  defined in the core application.

![WIS2Box ADL Components](docs/_static/images/wis2box-adl-components.png)

### 📋 Objectives

- To provide a tool for automating ingestion of data from different AWS vendors into a WIS2Box node.
- To provide a plugin architecture that allows for the development of plugins for different AWS vendors.
- To take advantage of the Wagtail CMS Admin interface to provide a user-friendly interface that facilitates easy setup
  and management of the data loaders for different AWS vendors.
- With minimal training, users at the NMHSs should be able to set up and configure an AWS vendor plugin for their
  observation data network and start ingesting data into WIS2Box node
- Provide a repository of plugins for different AWS vendors that can be shared and reused by NMHSs in Africa.

### ⚗️ Technology Stack

- The core application is built using the [Django](https://www.djangoproject.com/) framework
  and [Wagtail](https://wagtail.org/). Wagtail is used mainly for the Admin interface since it allows for easy
  customization and extension
- [PostgreSQL](https://www.postgresql.org/) with [Timescale db](https://www.timescale.com/) extension is used as the
  database for the system.
- [Celery](https://docs.celeryq.dev/en/stable/index.html) is used for background tasks.
- [Redis](https://redis.io/) is used as the message broker for Celery.
- The system is containerized using [Docker](https://www.docker.com/)
  and [docker-compose](https://docs.docker.com/compose/).
- Plugins are developed as Django/Wagtail apps and integrated into wagtail
  using [Wagtail hooks](https://docs.wagtail.org/en/stable/reference/hooks.html).
- [Nginx](https://nginx.org) is used the static and reverse proxy server for the system.
- Bash scripts are used for installing the plugins and their dependencies at runtime.

## 🧩 Plugins List

The following are the plugins that have been developed and are available for integration with the WIS2Box ADL core:

- [Adcon Telemetry Plugin](https://github.com/wmo-raf/wis2box-adl-adcon-plugin)
- [Davis Instruments Weatherlink Plugin](https://github.com/wmo-raf/wis2box-adl-weatherlink-v2-plugin)

## 🏁 Getting Started

### Pre-requisites

Before following the steps below, make sure you have the following set up:

- Docker Engine & Docker Compose Plugin : Ensure that Docker Engine is installed and running on the machine where you
  plan to execute the docker-compose command https://docs.docker.com/engine/install/. Docker Engine is the runtime
  environment for containers.

### Installation

#### 1. Clone the repository

```sh
git clone https://github.com/wmo-raf/wis2box-adl.git
cd wis2box-adl
```

#### 2. Setup Environment Variables

Copy the `.env.sample` file to `.env` and update the environment variables as needed.

```sh
cp .env.sample .env
```

Edit and replace variables appropriately using your text editor. Here is an example using `nano` text editor.

```sh
nano .env
```

See [environmental variables' section](#environmental-variables) below for more details on the required variables

#### 3. Create Wagtail static and media directories on the host machine and set correct permissions

Ensure you are using the correct paths as set in the `.env` file for the `WIS2BOX_ADL_STATIC_VOLUME`
and `WIS2BOX_ADL_MEDIA_VOLUME` variables.

```sh
mkdir -p ./docker/static
```

```sh
mkdir -p ./docker/media
```

##### Update the permissions for the directories

```sh
sudo chown <UID>:<GID> ./docker/static
```

```sh
sudo chown <UID>:<GID> ./docker/media
```

Replace `<UID>` and `<GID>` with the values set in the `.env` file for the `UID` and `GID` variables

#### 4. Build and Run the Docker Containers

```sh
docker-compose build
```

```sh
docker-compose up
```

To run the containers in the background, use the `-d` flag

```sh
docker-compose up -d
```

#### 5. Create Superuser

```sh
docker-compose exec wis2box_adl /bin/bash
source /wis2box_adl/venv/bin/activate

manage createsuperuser
```

`manage` is a script that is available in the container that calls Django's `manage.py`

### Environmental Variables

The following environmental variables are required to be set in the `.env` file:

| Variable Name                       | Description                                                                                                                                                                                                                                                                                                       | Required | Default Value    | Details                                                                                                            |
|-------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|------------------|--------------------------------------------------------------------------------------------------------------------|
| SECRET_KEY                          | A secret key for a particular Django installation. This is used to provide cryptographic signing, and should be set to a unique, unpredictable value. Django will refuse to start if SECRET_KEY is not set.You can use this online tool [https://djecrety.ir](https://djecrety.ir/) to generate the key and paste | YES      |                  |                                                                                                                    |
| ALLOWED_HOSTS                       | A list of strings representing the host/domain names that this Django site can serve. This is a security measure to prevent HTTP Host header attacks, which are possible even under many seemingly-safe web server.                                                                                               | YES      |                  | [Django Allowed Hosts](https://docs.djangoproject.com/en/4.2/ref/settings/#std-setting-ALLOWED_HOSTS)              |
| CSRF_TRUSTED_ORIGINS                | A list of trusted origins for unsafe requests                                                                                                                                                                                                                                                                     | NO       |                  | [Django CSRF Trusted Origins](https://docs.djangoproject.com/en/5.1/ref/settings/#csrf-trusted-origins)            |
| WIS2BOX_ADL_DEBUG                   | A boolean that turns on/off debug mode. Never deploy a site into production with DEBUG turned on                                                                                                                                                                                                                  | NO       | False            |                                                                                                                    |
| WAGTAIL_SITE_NAME                   | The human-readable name of your Wagtail installation which welcomes users upon login to the Wagtail admin.                                                                                                                                                                                                        | NO       | WIS2BOX ADL      |                                                                                                                    |
| LANGUAGE_CODE                       | The language code for the CMS. Available codes are `en` for English. Default is en if not set. More translations to be added                                                                                                                                                                                      | NO       | en               |                                                                                                                    |
| WIS2BOX_ADL_LOG_LEVEL               | The severity of the messages that the wis2box_adl service logger will handle. Allowed values are: `DEBUG`, `INFO`, `WARNING`, `ERROR` and `CRITICAL`                                                                                                                                                              | NO       | WARN             |                                                                                                                    |
| WIS2BOX_ADL_GUNICORN_NUM_OF_WORKERS | Number of Gunicorn workers                                                                                                                                                                                                                                                                                        | YES      | 4                |                                                                                                                    |
| WIS2BOX_ADL_GUNICORN_TIMEOUT        | Gunicorn timeout in seconds                                                                                                                                                                                                                                                                                       | YES      | 300              |                                                                                                                    |
| WIS2BOX_ADL_CELERY_BEAT_DEBUG_LEVEL | The severity of the messages that the wis2box_adl_celery_beat service logger will handle. Allowed values are: `DEBUG`, `INFO`, `WARNING`, `ERROR` and `CRITICAL`                                                                                                                                                  | NO       | INFO             |                                                                                                                    |
| WIS2BOX_ADL_DB_USER                 | ADL Database user                                                                                                                                                                                                                                                                                                 | YES      |                  |                                                                                                                    |
| WIS2BOX_ADL_DB_PASSWORD             | ADL Database password                                                                                                                                                                                                                                                                                             | YES      |                  |                                                                                                                    |
| WIS2BOX_ADL_DB_NAME                 | ADL Database name                                                                                                                                                                                                                                                                                                 | YES      |                  |                                                                                                                    |
| WIS2BOX_ADL_DB_VOLUME               | Mounted docker volume path for persisting database data                                                                                                                                                                                                                                                           | YES      | ./docker/db_data |                                                                                                                    |
| WIS2BOX_ADL_STATIC_VOLUME           | Mounted docker volume path for persisting django static files                                                                                                                                                                                                                                                     | YES      | ./docker/static  |                                                                                                                    |
| WIS2BOX_ADL_MEDIA_VOLUME            | Mounted docker volume path for persisting django media files                                                                                                                                                                                                                                                      | YES      | ./docker/media   |                                                                                                                    |
| WIS2BOX_ADL_BACKUP_VOLUME           | Mounted docker volume path for persisting db backups and media files                                                                                                                                                                                                                                              | YES      | ./docker/backup  |                                                                                                                    |
| WIS2BOX_ADL_WEB_PROXY_PORT          | Port Nginx will be available on the host                                                                                                                                                                                                                                                                          | YES      | 80               |                                                                                                                    |
| WIS2BOX_CENTRE_ID                   | wis2box centre id                                                                                                                                                                                                                                                                                                 | YES      |                  |                                                                                                                    |
| WIS2BOX_STORAGE_ENDPOINT            | wis2box storage endpoint                                                                                                                                                                                                                                                                                          | YES      |                  |                                                                                                                    |
| WIS2BOX_STORAGE_USERNAME            | wis2box storage username                                                                                                                                                                                                                                                                                          | YES      |                  |                                                                                                                    |
| WIS2BOX_STORAGE_PASSWORD            | wis2box storage password                                                                                                                                                                                                                                                                                          | YES      |                  |                                                                                                                    |
| UID                                 | The id of the user to run adl docker services                                                                                                                                                                                                                                                                     |          |                  |                                                                                                                    |
| GID                                 | The id of the group to run adl docker services                                                                                                                                                                                                                                                                    |          |                  |                                                                                                                    |
| WIS2BOX_ADL_PLUGIN_GIT_REPOS        | A comma separated list of github repos, where ald plugins to install are located                                                                                                                                                                                                                                  | NO       |                  | If no repo is added, no plugin is installed. A plugin must follow a given structure as described in sections below |

`Note`: On linux, you can type `id` in the terminal to get the `UID` and `GID` of the current user.









