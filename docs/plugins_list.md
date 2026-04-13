# 🧩 Available Plugins

ADL is a plugin-based system. The core application handles scheduling,
storage, unit conversion, QC, and dispatch — but it collects no observation
data on its own. You install one or more plugins depending on which AWS
vendor or data source your NMHS uses.

This page lists all currently available plugins. If none of these match your
data source, see [Developing Plugins](developer_guide/plugins/index.md) to
build your own.

---

## How to Read This Page

Each plugin entry shows:

- **What it connects to** — the upstream data source or vendor
- **Install URL** — the GitHub repository URL to use with `ADL_PLUGIN_GIT_REPOS`
  or the `install-plugin` command
- **Releases** — link to the GitHub Releases page where you can find version
  tags for pinned installs

For installation instructions see [Installation](installation.md#6-install-plugins).

---

## General Plugins

These plugins work across multiple countries and vendor deployments.

| Plugin                       | Connects to                                                                                                                           | Install URL                                               | Releases                                                                 |
|------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------|--------------------------------------------------------------------------|
| **ADL FTP Plugin**           | FTP/SFTP storage endpoints — supports multiple decoder formats (Campbell TOA5, Siap+Micros, Vaisala, ADCON, Pulsonic, Seba, and more) | `https://github.com/wmo-raf/adl-ftp-plugin.git`           | [Releases](https://github.com/wmo-raf/adl-ftp-plugin/releases)           |
| **ADL ADCON DB Plugin**      | ADCON Postgres database                                                                                                               | `https://github.com/wmo-raf/adl-adcon-db-plugin.git`      | [Releases](https://github.com/wmo-raf/adl-adcon-db-plugin/releases)      |
| **ADL TAHMO Plugin**         | [TAHMO](https://tahmo.org) API                                                                                                        | `https://github.com/wmo-raf/adl-tahmo-plugin.git`         | [Releases](https://github.com/wmo-raf/adl-tahmo-plugin/releases)         |
| **ADL PulsoWeb Plugin**      | Pulsonic's PulsoWeb API                                                                                                               | `https://github.com/wmo-raf/adl-pulsoweb-plugin.git`      | [Releases](https://github.com/wmo-raf/adl-pulsoweb-plugin/releases)      |
| **ADL WeatherLink Plugin**   | Davis Instruments WeatherLink API                                                                                                     | `https://github.com/wmo-raf/adl-weatherlink-plugin.git`   | [Releases](https://github.com/wmo-raf/adl-weatherlink-plugin/releases)   |
| **ADL CIMAWebDrops Plugin**  | CIMA WebDrops API                                                                                                                     | `https://github.com/wmo-raf/adl-cimawebdrops-plugin.git`  | [Releases](https://github.com/wmo-raf/adl-cimawebdrops-plugin/releases)  |
| **ADL EarthNetworks Plugin** | EarthNetworks API                                                                                                                     | `https://github.com/wmo-raf/adl-earthnetworks-plugin.git` | [Releases](https://github.com/wmo-raf/adl-earthnetworks-plugin/releases) |

---

## Country-Specific FTP Decoders

These plugins extend the ADL FTP Plugin with custom decoders for specific
national deployments. They are maintained by individual NMHSs and are not
part of the core ADL project.

```{note}
Country-specific decoders are used **alongside** the ADL FTP Plugin, not
instead of it. Install the FTP Plugin first, then install the relevant
decoder for your country.
```

| Plugin                         | Country           | Description                        | Install URL                                                        |
|--------------------------------|-------------------|------------------------------------|--------------------------------------------------------------------|
| **ADL ADCON BF Decoder**       | 🇧🇫 Burkina Faso | FTP decoder for ADCON stations     | `https://github.com/anam-bf/adl-ftp-adcon-bf-plugin.git`           |
| **ADL Vaisala SC FTP Decoder** | 🇸🇨 Seychelles   | FTP decoder for Vaisala Avimet AWS | `https://github.com/seychelles-met/adl-vaisala-sc-ftp-decoder.git` |
| **ADL ADCON SOM Decoder**      | 🇸🇴 Somalia      | FTP decoder for ADCON stations     | `https://github.com/wmo-raf/adl-ftp-adcon-som-plugin.git`          |
| **ADL NESA MZ Decoder**        | 🇲🇿 Mozambique   | FTP decoder for NESA stations      | `https://github.com/inam-mz/adl-mz-nesa-decoder.git`               |

---

## Choosing the Right Plugin

Not sure which plugin you need? Use this guide:

**Your stations send data to an FTP or SFTP server**
→ Start with the [ADL FTP Plugin](https://github.com/wmo-raf/adl-ftp-plugin).
It supports multiple file formats. Check whether a country-specific decoder
exists for your vendor.

**Your stations use ADCON hardware with a Postgres database**
→ Use the [ADL ADCON DB Plugin](https://github.com/wmo-raf/adl-adcon-db-plugin).

**Your stations are part of the TAHMO network**
→ Use the [ADL TAHMO Plugin](https://github.com/wmo-raf/adl-tahmo-plugin).

**Your stations use Pulsonic / PulsoWeb**
→ Use the [ADL PulsoWeb Plugin](https://github.com/wmo-raf/adl-pulsoweb-plugin).

**Your stations use Davis Instruments WeatherLink**
→ Use the [ADL WeatherLink Plugin](https://github.com/wmo-raf/adl-weatherlink-plugin).

**None of the above match your data source**
→ See [Developing Plugins](developer_guide/plugins/index.md) to build a
custom plugin for your vendor.

---

## Installing a Plugin

**Build-time (recommended for production)** — pin to a release tag for
reproducible deployments:

```bash
# In your .env file
ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git#v1.2.0
```

Then rebuild:

```bash
make build
make up
```

**Runtime** — install into a running stack without rebuilding:

```bash
docker compose exec adl install-plugin --git https://github.com/wmo-raf/adl-ftp-plugin.git#v1.2.0
```

For full installation details and all available options see
[Installation](installation.md#6-install-plugins).

---

## NMHSs Currently Using ADL

For a full list of NMHSs currently using ADL see the
[project README](https://github.com/wmo-raf/adl#nmhss-using-adl).