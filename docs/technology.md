# ⚗️ Technology Stack

To support its plugin-based architecture and automated data workflows, the Automated Data Loader (ADL) is built on a
robust and extensible open-source technology stack.

This stack enables seamless integration of vendor-specific plugins,
efficient background processing of observation data, and scalable deployment across diverse environments. The selected
tools ensure reliability, performance, and flexibility for handling real-time and historical data from various weather
observation networks.

Below is an overview of the core technologies and their roles:

| Component                   | Technology                                                                                        | Purpose                                       |
|-----------------------------|---------------------------------------------------------------------------------------------------|-----------------------------------------------|
| **Web Framework**           | [Django](https://www.djangoproject.com/), [Wagtail](https://wagtail.org/)                         | Core backend and customizable admin interface |
| **Database**                | [PostgreSQL](https://www.postgresql.org/), [TimescaleDB](https://www.timescale.com/)              | Relational DB with time-series support        |
| **Tasks & Background Jobs** | [Celery](https://docs.celeryq.dev/), [Redis](https://redis.io/)                                   | Asynchronous task queue and message broker    |
| **Plugins**                 | Django/Wagtail apps with [Wagtail Hooks](https://docs.wagtail.org/en/stable/reference/hooks.html) | Modular extension system                      |
| **Web Server**              | [Nginx](https://nginx.org)                                                                        | Static file serving and reverse proxy         | |                                               |
| **Containerization**        | [Docker](https://www.docker.com/), [Docker Compose](https://docs.docker.com/compose/)             | Environment setup and service orchestration   |