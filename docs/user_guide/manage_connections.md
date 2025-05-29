# Manage Connections

A `Connection` contains the configuration required for a plugin to communicate and get data from a specific source.

Depending on the plugin, the connection can include information like the host URL or IP, port etc for communication
protocols like FTP,HTTP, Database connections etc

![Add Network Connection](../_static/images/user/add_connection.png)

![Connection Types](../_static/images/user/connection_types_list.png)

![Connection Form](../_static/images/user/add_connection_form.png)

```{note}
A network connection must be associated with a plugin, that implements the actual data fetching. You can select the
plugin to associate with the network connection by selecting from the `Plugin` dropdown. This will be a list of plugins
that have been installed.
```
