---
hidetoc: 1
---

# Welcome to the Automated Data Loader (ADL) documentation

Automate periodic observation data collection from different Automatic Weather Station (AWS) networks and normalize it
into a common schema. Then push the data to downstream systems such
as [wis2box](https://github.com/World-Meteorological-Organization/wis2box) for international data exchange, Climate Data
Management Systems (CDMS) like [Climsoft](https://climsoft.org), or any other system that needs to consume weather
station data.

```{image} _static/images/adl-dashboard.png
:alt: ADL Dashboard
:class: screenshot
:align: center
:width: 800px
```

Below are some of the key objectives of ADL:

- Provide a tool for **automating data collection** from different weather station networks (Manual/Automatic Weather
  stations)
- Provide a flexible architecture for the development of **plugins for collecting data** from different Weather Station
  networks (Pull plugins)
- Provide a flexible architecture for the development of **plugins for sending collected data** to different receiving
  channels (Push plugins)
- Provide a **user friendly interface for managing** the data collection and pushing process.

## Index

```{toctree}
---
maxdepth: 2
titlesonly: true
---
background
architecture
technology
core_concepts
installation
plugins_list
environmental_variables
ssl-setup-nginx-proxy-manager
wis2box-adl-nginx-proxy-manager
data-flow-and-access-control
user_guide/index
developer_guide/index
```