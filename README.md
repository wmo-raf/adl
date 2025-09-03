# ⚙ Automated Data Loader

Automate periodic observation data collection from different Automatic Weather Station (AWS) networks, and pushing to
different receiving systems.

![ADL Dashboard](docs/_static/images/adl-dashboard.png)

## NMHSs using ADL

| No. | Country                                             | AWS/Plugins                                                              | Push Channels                                               | Status        |
|-----|-----------------------------------------------------|--------------------------------------------------------------------------|-------------------------------------------------------------|---------------|
| 1   | 🇹🇩 [Chad](https://www.meteotchad.org)             | ADL ADCON DB Plugin                                                      | [Chad Wis2box](https://wis2.meteotchad.org/)                | ✅ Operational |
| 2   | 🇸🇸 [South Sudan](http://meteosouthsudan.com.ss)   | ADL FTP Plugin, using inbuilt Siap + Micros Decoder                      | [South Sudan Wis2box](https://wis2.meteosouthsudan.com.ss/) | ✅ Operational |
| 3   | 🇧🇫 [Burkina Faso](https://meteosouthsudan.com.ss) | ADL FTP Plugin with custom ADCON Decoder FTP BF Adcon Decoder            | [Burkina Faso Wis2box](https://wis2.meteoburkina.bf/)       | ✅ Operational |
| 4   | 🇸🇨 [Seychelles](https://www.meteo.sc)             | ADL WeatherLink Plugin                                                   | [Seychelles Wis2box](https://wis2.meteo.sc)                 | ✅ Operational |
| 5   | 🇬🇭 [Ghana](https://www.meteo.gov.gh)              | ADL ADCON DB Plugin                                                      | [Ghana Wis2box](https://wis2.meteo.gov.gh)                  | ✅ Operational |
| 6   | 🇲🇼 [Malawi](https://www.metmalawi.gov.mw)         | [ADL FTP Plugin, using inbuilt Campbell TOA5 Decoder                     | [Malawi Wis2box](https://wis2.metmalawi.gov.mw)             | ✅ Operational |
| 7   | 🇲🇱 [Mali](https://malimeteo.ml)                   | ADL PulsoWeb Plugin                                                      | [Mali wis2box](http://wis2.malimeteo.ml)                    | ✅ Operational |  |
| 8   | 🇹🇬 [Togo](https://www.anamet-togo.com)            | ADL PulsoWeb Plugin                                                      | [Togo Wis2box](https://wis2.anamet-togo.com)                | ✅ Operational |
| 9   | 🇳🇬 [Nigeria](https://www.nimet.gov.ng)            | TAHMO Plugin                                                             | [Nimet Wis2box](https://wis2.nimet.gov.ng)                  | ✅ Operational |
| 10  | 🇿🇼 [Zimbabwe](https://www.weatherzw.org.zw)       | ADL FTP Plugin, with Campbell TOA5 Decoder                               | [MSD wis2box](https://wis2.weatherzw.org.zw)                | ✅ Operational |
| 11  | 🇧🇮 [Burundi](https://www.igebu.bi)                | ADL ADCON Plugin, ADL EarthNetworks plugin                               | [Igebu Wis2box](https://wis2.igebu.bi)                      | ✅ Operational |     |                                                     |                                                                          |                                                             |               |
| 12  | 🇳🇪 [Niger](https://www.niger-meteo.ne)            | ADL PulsoWeb Plugin                                                      | Niger Wis2box                                               | ⏳ In Progress |
| 13  | 🇧🇯 [Benin](https://www.meteobenin.bj)             | ADL PulsoWeb Plugin                                                      | Benin Wis2box                                               | ⏳ In Progress |
| 14  | 🇬🇳 [Guinea](https://anmeteo.gov.gn)               | Siap + Micros, ADCON                                                     | Guinea Wis2box                                              | ⏳ In Progress |
| 15  | 🇪🇹 [Ethiopia](https://www.ethiomet.gov.et)        | ADL ADCON DB Plugin                                                      | Ethiomet Wis2box                                            | ⏳ In Progress |
| 16  | 🇸🇳 [Senegal](https://anacim.sn)                   | ADCON, ADL PulsoWeb Plugin                                               | Senegal Wis2box                                             | ⏳ In Progress |
| 17  | 🇰🇪 [Kenya](https://meteo.go.ke)                   | ADL FTP Plugin, Sutron, Microstep, ADCON, Vaisala, Pulsonic, Seba, TAHMO | Kenya wis2box                                               | ⏳ In Progress |
| 18  | 🇨🇮 Côte d'Ivoire                                  | ADL PulsoWeb Plugin                                                      |                                                             | ⏳ In Progress |
| 19  | 🇸🇩 [Sudan](https://meteosudan.sd)                 | ADL CIMAWebDrops Plugin                                                  |                                                             | ⏳ In Progress |

## List of Plugins

Below is a list of currently available plugins for the Automated Data Loader (ADL). Each plugin is designed to collect
data from specific data sources or systems.

| No. | Plugin Name              | Description                                              | Link                                                                                |
|-----|--------------------------|----------------------------------------------------------|-------------------------------------------------------------------------------------|
| 1   | ADL FTP Plugin           | Collecting data from FTP storages                        | [adl-ftp-plugin](https://github.com/wmo-raf/adl-ftp-plugin)                         |
| 2   | ADL ADCON DB Plugin      | Collecting data from ADCON Postgres database             | [adl-adcon-db-plugin](https://github.com/wmo-raf/adl-adcon-db-plugin)               |
| 3   | ADL TAHMO Plugin         | Collecting data from TAHMO API                           | [adl-tahmo-plugin](https://github.com/wmo-raf/adl-tahmo-plugin)                     |
| 4   | ADL PulsoWeb Plugin      | Collecting data from Pulsonic's Pulsoweb API             | [adl-pulsoweb-plugin](https://github.com/wmo-raf/adl-pulsoweb-plugin)               |
| 5   | ADL WeatherLink Plugin   | Collecting data from Davis Instruments's WeatherLink API | [adl-weatherlink-plugin](https://github.com/wmo-raf/adl-weatherlink-plugin)         |
| 6   | ADL CIMAWebDrops Plugin  | Collecting data from CIMA's WebDrops API                 | [adl-cimawebdrops-plugin](https://github.com/wmo-raf/adl-cimawebdrops-plugin)       |
| 7   | ADL EarthNetworks Plugin | Collecting data from EarthNetworks                       | [adl-earthnetworks-plugin](    https://github.com/wmo-raf/adl-earthnetworks-plugin) |

### Country Specific FTP Decoders

| No. | Plugin Name                | Description                                        | Link                                                                                       |
|:----|----------------------------|----------------------------------------------------|--------------------------------------------------------------------------------------------|
| 1   | ADL ADCON BF Decoder       | FTP Decoder for Burkina Faso ADCON                 | [adl-ftp-adcon-bf-plugin](https://github.com/anam-bf/adl-ftp-adcon-bf-plugin)              |
| 2   | ADL Vaisala SC FTP Decoder | FTP Decoder  for the Seychelles Vaisala Avimet AWS | [adl-vaisala-sc-ftp-decoder](https://github.com/seychelles-met/adl-vaisala-sc-ftp-decoder) |
| 3   | ADL ADCON SOM Decoder      | FTP Decoder for Somalia ADCON                      | [adl-ftp-adcon-som-plugin](https://github.com/wmo-raf/adl-ftp-adcon-som-plugin)            |

## Features

- **Data Ingestion**: Collects data from various AWS networks and manual stations, based on installed plugins.
- **Data Dispatch**: Pushes collected data to different receiving systems, based on installed plugins.
- **Plugin Architecture**: Extensible architecture allowing for custom plugins to be developed for specific AWS vendors
  or data sources.

## System Architecture

The Automated Data Loader (ADL) is a plugin based system that defines an architecture for implementing data loaders from
different observation data sources, such as Automatic Weather Stations (AWS) networks and manual stations, and pushing
the collected data to different receiving systems like wis2box, Climate Data Management Systems (CDMSs), FTP etc.

![ADL System Architecture](docs/_static/images/adl-system-architecture.png)

## Guide

You can access the user and developer guide at [https://adl-tool.readthedocs.io](https://adl-tool.readthedocs.io)