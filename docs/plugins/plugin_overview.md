# Plugin Overview

ADL Plugins are custom Wagtail apps that extend the functionality of ADL to implement vendor-specific logic for
collecting observations for ingestion into ADL or pushing received data to external systems. Different AWS vendors or
observation data sources have their own way of collecting and transmitting data. A plugin is a way to implement this
logic in ADL.

There are two types of plugins in ADL:

- **Data Ingestion Plugins**: These plugins are responsible for collecting data from a specific source, such as an AWS
  vendor or a specific data source. They implement the logic for connecting to the data source, fetching the data, and
  transforming it into a format that ADL can store. This can include parsing data from files, connecting to APIs etc.
- **Data Dispatch Plugins**: These plugins are responsible for dispatching data to a specific destination, such as a
  database, an API, or a file system. They implement the logic for connecting to the destination, transforming the data
  into the required format, and sending it to the destination.

## Important Notes on Plugins

- You should always make backups of your ADL data before installing and using any plugin.
- You should only ever install plugins from a trusted source
- Ensure that you fully understand the plugins you are installing and using, as this entirely at your own risk.

In this guide we dive into how to create a ADL plugin, discuss the plugin architecture and give you sample
plugins to get inspiration from.