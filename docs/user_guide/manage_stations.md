# Manage Stations

After creating a network, you can add stations to the network. Stations are the actual AWS stations or manual stations.

![Load Stations from OSCAR Surface](../_static/images/user/stations_loading_options.png)

There are two ways to add stations to a network as shown in the image above:

## Manual Entry

You can manually add stations to a network by clicking on the `Stations` link on the left sidebar
and then clicking on the `Add Station` button.

You will be required to fill in the station details, WIGOS information, and station metadata.

**Station Base Info**
![Add Station Base Info](../_static/images/user/add_station_manually_base_info.png)

**Station WIGOS Info**
![Add Station WIGOS Info](../_static/images/user/add_station_manually_wigos_info.png)

**Station Metadata**
![Add Station Medata](../_static/images/user/add_station_manually_metadata.png)

## Importing from WMO OSCAR Surface

The quickest way to load stations is by importing from the [WMO OSCAR Surface](https://oscar.wmo.int/surface/#/)
database.

You can do so by clicking on the `Stations` link on the left sidebar and then clicking on
the `Load Stations from OSCAR Surface` button.

This will load stations from the OSCAR Surface database, and you can select the stations to add to the network.

![Load Stations from OSCAR Surface](../_static/images/user/oscar_stations_list.png)

### Using a local CSV Copy of stations data downloaded from OSCAR Surface

If you face network issues when connecting to the WMO OSCAR Surface API, you can import a pre-downloaded CSV file of
stations data for your country. The data should be downloaded from the
official [WMO OSCAR Surface](https://oscar.wmo.int/surface) website.

![Load Stations from OSCAR Surface CSV](../_static/images/user/load_stations_from_local_csv_button.png)

This will open a form where you can upload the CSV file. The CSV file should be in the structure as downloaded from WMO
OSCAR Surface.

![Load Stations from OSCAR Surface CSV Form](../_static/images/user/upload_local_oscar_csv.png)

If the CSV file is successfully uploaded, you will be redirected to a page where you can select the stations to import.

![OSCAR Surface Local CSV Stations List](../_static/images/user/oscar_stations_local_list.png)

Irrespective of the method used to load stations from OSCAR Surface database, the importing process of the loaded
stations into the system will be the same.

![OSCAR Surface Stations Import](../_static/images/user/import_oscar_station.png)

After clicking on the `Import Station` button, a form with the station to import will be displayed. Here you will be
required to set the `Staton ID` and assign the station to a network and select if the station is an AWS station or
manual.

![OSCAR Surface Stations Import Form](../_static/images/user/import_oscar_station_form.png)

Then click on the `Import` button to import the station.