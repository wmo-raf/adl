# 🛠️ Installation

## Pre-requisites

Before following the steps below, make sure you have the following set up:

- **Docker Engine & Docker Compose Plugin** : Ensure that Docker Engine is installed and running on the machine where
  you plan to execute the docker compose
  command [https://docs.docker.com/engine/install](https://docs.docker.com/engine/install). Docker Engine is the runtime
  environment for containers.

## Installation

### 1. Clone the repository

```sh
git clone https://github.com/wmo-raf/adl.git
cd adl
```

### 2. Setup Environment Variables

Copy the `.env.sample` file to `.env` and update the environment variables as needed.

```sh
cp .env.sample .env
```

Edit and replace variables appropriately using your text editor. Here is an example using `nano` text editor.

```sh
nano .env
```

See environmental variables' section below for more details on the required variables

### 3. Create Wagtail static and media directories on the host machine and set correct permissions

Ensure you are using the correct paths as set in the `.env` file for the `ADL_STATIC_VOLUME`
and `ADL_MEDIA_VOLUME` variables.

```sh
mkdir -p ./docker/static
```

```sh
mkdir -p ./docker/media
```

#### Update the permissions for the directories

```sh
sudo chown <UID>:<GID> ./docker/static
```

```sh
sudo chown <UID>:<GID> ./docker/media
```

Replace `<UID>` and `<GID>` with the values set in the `.env` file for the `UID` and `GID` variables

`NOTE:` The database volume uses UID `1000` and GID `1000` by default. Set the correct permissions for the volume as
below:

```sh
sudo chown 1000:1000 ./docker/db_data
```

### 4. Build and Run the Docker Containers

```sh
docker compose build
```

```sh
docker compose up
```

To run the containers in the background, use the `-d` flag

```sh
docker compose up -d
```

### 5. Create Superuser

```sh
docker compose exec adl /bin/bash

adl createsuperuser
```

```{note}
`adl` is a shortcut cli command that is available in the container that calls Django's `manage.py`. 
So instead of typing `python manage.py <command>`, you can simply type `adl <command>`.
```