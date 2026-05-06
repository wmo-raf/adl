# ⚙️ADL Data Flow & Access Control

## Overview

Once ADL (Automated Data Loader) is installed on your infrastructure, it becomes **your system**. WMO or anyone else has
no ongoing access to your instance, and you have full control over who can access it, what data it collects, and where
that data is sent.

This document explains how data moves through ADL — from ingestion through to dispatch — and clarifies common questions
around data routing, station selection, and integration with external systems such as WIS2box or third-party servers.

---

## ADL is Your System

When ADL is deployed on your server, ownership and access control rest entirely with your organisation. This means:

- You manage user accounts and permissions within the ADL admin interface.
- No data is shared with any external system unless you have explicitly configured a dispatch channel to do so.
- Your ADL instance operates independently of other NMHSs running ADL. Each installation is isolated.

This is an important point when thinking about data sensitivity: **data does not leave ADL by default**. Every outbound
connection is the result of a deliberate configuration choice made by your team.

---

## How Data Flows Through ADL

ADL is built around a plugin architecture. Data enters the system through **source plugins** and leaves through *
*dispatch channel plugins**. These two sides of the pipeline are independent of each other.

```
[ Data Sources ]        [ ADL Core ]        [ Dispatch Channels ]
                                                
  FTP / SFTP   ──┐                        ┌── WIS2box
  Mobile App   ──┼──►  Ingestion &  ──────┼── S3 / MinIO
  Online Portal──┤     Storage            ├── External API
  Other vendors──┘                        └── Custom FTP
```

### Source Plugins (Data In)

Source plugins define how ADL fetches or receives raw data. Common source types include:

- **FTP / SFTP plugin** — ADL polls a remote FTP folder on a configured schedule and retrieves new data files.
- **Mobile Collector** — Field observers submit manual station readings via the ADL Collector mobile app. Submissions
  are received and stored by ADL directly.
- **Other vendor plugins** — ADL supports a growing range of AWS vendor-specific storages and retrieval.

Regardless of source, all ingested data is normalised and stored within ADL before anything else happens. **Ingestion
and dispatch are decoupled** — data coming in does not automatically go anywhere.

### Dispatch Channel Plugins (Data Out)

A dispatch channel defines a destination and the rules for what gets sent there. Each channel is configured
independently and has its own:

- **Station selection** — You choose, station by station, which stations are included in a given channel. A station
  included in one channel does not have to appear in another.
- **Parameter selection** — You choose which observed parameters (e.g. rainfall, temperature, wind speed) are forwarded
  through the channel.
- **Destination** — The endpoint the data is sent to (e.g. a WIS2box instance, an S3 bucket, an FTP folder).
- **Schedule** — How frequently the channel dispatches data.

Because channels are independent, there is no coupling between them. Sending data to WIS2box through one channel has no
effect on what another channel sends to a different destination.

---

## Common Scenarios

### Scenario 1: GBON Stations to WIS2, Other Stations Kept Internal

You have a set of stations designated as GBON stations that should report to WIS2, and additional stations whose data
should remain within your organisation.

**How to configure this in ADL:**

- Create a WIS2box dispatch channel and add only your GBON stations to it.
- Data from non-GBON stations is stored in ADL but not included in that channel — it goes nowhere unless you explicitly
  route it.
- If you want non-GBON data available in a separate internal system, create a second dispatch channel pointing to an
  internal FTP folder or S3 bucket and add those stations to it.

No data from non-GBON stations will appear in WIS2 because they are simply not part of that channel's station selection.

### Scenario 2: Sending Data to a Third-Party System

A partner organisation needs access to rainfall data from a broader set of stations than what is published to WIS2.

**How to configure this in ADL:**

- Install the specific dispatch plugin and configure it with the partner's details. Could be an FTP channel, an S3
  channel, or other supported destination.
- Add whichever stations should contribute to this channel — this can include stations not in the WIS2 channel.
- The two channels operate entirely independently. There is no requirement for the station sets to match.

The data sent to the partner is drawn from ADL's internal store, not from WIS2. WIS2 publication status has no bearing
on what other channels can access.

### Scenario 3: Mobile Collector & WIS2box

A common misconception is that the Mobile Collector app pushes data directly to WIS2box. This is not the case.

**Actual flow:**

1. A field observer submits a reading in the Mobile Collector app.
2. The submission is received and stored in ADL.
3. If the station is part of a WIS2box dispatch channel, ADL will forward that data to WIS2box on the next dispatch
   cycle.
4. If the station is not included in any dispatch channel, the data remains in ADL only.

This means you can use the Mobile Collector for stations that should never appear in WIS2 or any other channel — simply
do not add those stations to the WIS2box channel.

---

## Summary: Key Principles

| Principle                                         | What it means in practice                                                                        |
|---------------------------------------------------|--------------------------------------------------------------------------------------------------|
| ADL is your system                                | You control access, configuration, and data routing. Nothing leaves without your explicit setup. |
| Ingestion and dispatch are decoupled              | Data coming in from any source does not automatically go anywhere.                               |
| Each dispatch channel is independent              | Station selection, parameters, destination, and schedule are configured per channel.             |
| Station selection is per channel                  | A station can appear in multiple channels, one channel, or none.                                 |
| WIS2 publication has no bearing on other channels | Data can be sent to internal or partner systems regardless of whether it is published to WIS2.   |

