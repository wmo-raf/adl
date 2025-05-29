# 📚 Background

One of the challenges confronting NMHSs in Africa in observation data management is the disparities between the
different station types managed by the institutions or provided through projects. This has given rise to barriers in
using the data collected by Automated Weather Stations in a harmonized way.

These disparities include major differences in the way the data from various AWS vendors are formatted and stored, which
result in poorly coordinated, fragmented, and un-harmonized datasets coming from different AWS networks.

Given the broad category of AWS vendors and types that share similar purpose of collecting weather observation data,
with different storage structure, having a monolithic application would be too large and complex to accommodate all the
possible AWS vendor types in Africa NMHSs.

A solution for unifying this data collection would be to have a core application that only knows about the high-level
information of the AWS network, and then develop small units (plugins) on demand, to handle the complexities of each AWS
vendor type. Similar case for pushing data to different receiving systems. For each receiving channel (could be an FTP,
Database, API, Webhook, S3 Storage etc), a plugin can be developed to handle the complexities of periodically pushing
data to these systems.

This project is an implementation of such a solution.

The initial idea for this project was to create a tool that would automate the collection of data from different AWS and
ingest into a [WIS2Box node](https://github.com/wmo-im/wis2box). However, this has been expanded to include the ability
to develop plugins to send to other receiving storages and systems

[WIS2 in a box](https://github.com/wmo-im/wis2box) (wis2box) is a Free and Open Source (FOSS) Reference Implementation
of a WMO WIS2 Node. The project provides a plug and play toolset to ingest, process, and publish weather/climate/water
data using standards-based approaches in alignment with the WIS2 principles. WIS2 in a box enables World Meteorological
Organization (WMO) members to publish and download data through the WIS2 network.

One of the critical steps in the WIS2 data flow is the ingestion of realtime data from observation stations (either
Manual or Automatic Weather Stations) into a WIS2 node. Setting up wis2box is one thing, ensuring that the data from
stations is periodically ingested into the node in a timely way is another. Countries can develop their own tools and
scripts to automate this process, but this can be time-consuming and costly especially for developing countries that
have a 'cocktail' of different AWS vendors.

![ADL Data Flow](_static/images/adl-wis2box-data-flow-adl.png)
