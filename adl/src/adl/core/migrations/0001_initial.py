# Generated by Django 5.0.6 on 2025-01-09 11:13

import adl.core.units
import adl.core.utils
import django.contrib.gis.db.models.fields
import django.core.validators
import django.db.models.deletion
import django_countries.fields
import modelcluster.fields
import timescale.db.models.fields
import timezone_field.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('wagtailcore', '0094_alter_page_locale'),
    ]

    operations = [
        migrations.CreateModel(
            name='DataParameter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Name of the variable', max_length=255, verbose_name='Name')),
                ('description', models.TextField(blank=True, help_text='Description of the variable', null=True, verbose_name='Description')),
                ('custom_unit_context', models.CharField(blank=True, choices=adl.core.utils.get_custom_unit_context_entries, help_text='Context of the unit', max_length=255, null=True, verbose_name='Custom Unit Conversion Context')),
            ],
        ),
        migrations.CreateModel(
            name='DispatchChannel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Name')),
                ('enabled', models.BooleanField(default=True, verbose_name='Enabled')),
                ('data_check_interval', models.PositiveIntegerField(default=10, help_text='How often the channel should check the database for new data, in minutes', validators=[django.core.validators.MaxValueValidator(30), django.core.validators.MinValueValidator(1)], verbose_name='Data Check Interval in Minutes')),
                ('last_upload_obs_time', models.DateTimeField(blank=True, null=True, verbose_name="Last Upload's Observation Time")),
                ('send_aggregated_data', models.BooleanField(default=False, verbose_name='Send Aggregated Data')),
                ('aggregation_period', models.CharField(blank=True, choices=[('hourly', 'Hourly'), ('daily', 'Daily')], default='hourly', max_length=255, null=True, verbose_name='Aggregation Period')),
                ('polymorphic_ctype', models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='polymorphic_%(app_label)s.%(class)s_set+', to='contenttypes.contenttype')),
            ],
            options={
                'abstract': False,
                'base_manager_name': 'objects',
            },
        ),
        migrations.CreateModel(
            name='Network',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Name of the network', max_length=255, verbose_name='Name')),
                ('type', models.CharField(choices=[('automatic', 'Automatic Weather Stations'), ('manual', 'Manual Weather Stations')], help_text='Weather station type', max_length=255, verbose_name='Weather Stations Type')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Network',
                'verbose_name_plural': 'Networks',
            },
        ),
        migrations.CreateModel(
            name='OscarSurfaceStationLocal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Name of the station', max_length=255, verbose_name='Name')),
                ('wigos_id', models.CharField(help_text='WIGOS ID of the station', max_length=255, unique=True, verbose_name='WIGOS ID')),
                ('latitude', models.FloatField(help_text='Latitude of the station', verbose_name='Latitude')),
                ('longitude', models.FloatField(help_text='Longitude of the station', verbose_name='Longitude')),
                ('elevation', models.FloatField(help_text='Elevation of the station', verbose_name='Elevation')),
            ],
        ),
        migrations.CreateModel(
            name='Unit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Name of the unit', max_length=255, unique=True, verbose_name='Name')),
                ('symbol', models.CharField(help_text='Symbol of the unit', max_length=255, unique=True, validators=[adl.core.units.validate_unit], verbose_name='Symbol')),
                ('description', models.TextField(blank=True, help_text='Description of the unit', null=True, verbose_name='Description')),
            ],
            options={
                'verbose_name': 'Unit',
                'verbose_name_plural': 'Units',
            },
        ),
        migrations.CreateModel(
            name='AdlSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('country', django_countries.fields.CountryField(max_length=2, verbose_name='Country')),
                ('hourly_aggregation_interval', models.PositiveIntegerField(default=10, verbose_name='Hourly Aggregation Interval in Minutes')),
                ('daily_aggregation_time', models.TimeField(default='00:00', verbose_name='Daily Aggregation Time')),
                ('site', models.OneToOneField(editable=False, on_delete=django.db.models.deletion.CASCADE, to='wagtailcore.site')),
            ],
            options={
                'verbose_name': 'ADL Settings',
                'verbose_name_plural': 'ADL Settings',
            },
        ),
        migrations.CreateModel(
            name='Wis2BoxUpload',
            fields=[
                ('dispatchchannel_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='core.dispatchchannel')),
                ('storage_endpoint', models.CharField(max_length=255, verbose_name='Storage Endpoint')),
                ('storage_username', models.CharField(max_length=255, verbose_name='Storage Username')),
                ('storage_password', models.CharField(max_length=255, verbose_name='Storage Password')),
                ('secure', models.BooleanField(default=False, help_text='If checked, HTTPS connection will be used,otherwise HTTP', verbose_name='Use Secure Connection')),
                ('dataset_id', models.CharField(max_length=255, verbose_name='Dataset ID')),
            ],
            options={
                'verbose_name': 'WIS2BOX Upload',
                'verbose_name_plural': 'WIS2BOX Uploads',
            },
            bases=('core.dispatchchannel',),
        ),
        migrations.CreateModel(
            name='NetworkConnection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True, verbose_name='Name')),
                ('plugin', models.CharField(help_text='Plugin to use for this network', max_length=255, verbose_name='Plugin')),
                ('plugin_processing_enabled', models.BooleanField(default=True, help_text='If unchecked, the plugin will not run automatically', verbose_name='Plugin Auto Processing Enabled')),
                ('plugin_processing_interval', models.PositiveIntegerField(default=15, help_text='How often the plugin should run, in minutes', validators=[django.core.validators.MaxValueValidator(30), django.core.validators.MinValueValidator(1)], verbose_name='Plugin Auto Processing Interval in Minutes')),
                ('network', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.network', verbose_name='Network')),
                ('polymorphic_ctype', models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='polymorphic_%(app_label)s.%(class)s_set+', to='contenttypes.contenttype')),
            ],
            options={
                'verbose_name': 'Network Connection',
                'verbose_name_plural': 'Network Connections',
            },
        ),
        migrations.AddField(
            model_name='dispatchchannel',
            name='network_connection',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dispatch_channels', to='core.networkconnection', verbose_name='Network Connection'),
        ),
        migrations.CreateModel(
            name='Station',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('station_id', models.CharField(help_text='Unique Station Identifier', max_length=255, verbose_name='Station ID')),
                ('name', models.CharField(help_text='Name of the station', max_length=255, verbose_name='Name')),
                ('wsi_series', models.PositiveIntegerField(help_text='WIGOS identifier series', verbose_name='WSI Series')),
                ('wsi_issuer', models.PositiveIntegerField(help_text='WIGOS issuer of identifier', verbose_name='WSI Issuer')),
                ('wsi_issue_number', models.PositiveIntegerField(help_text='WIGOS issue number', verbose_name='WSI Issue Number')),
                ('wsi_local', models.CharField(help_text='WIGOS local identifier', max_length=255, verbose_name='WSI Local')),
                ('wmo_block_number', models.PositiveIntegerField(blank=True, default=None, help_text='WMO block number', null=True, verbose_name='WMO Block Number')),
                ('wmo_station_number', models.CharField(blank=True, help_text='WMO station number', max_length=255, null=True, validators=[adl.core.utils.validate_as_integer], verbose_name='WMO Station Number')),
                ('station_type', models.PositiveIntegerField(choices=[(0, 'Automatic'), (1, 'Manned'), (2, 'Hybrid: both automatic and manned')], help_text='Type of observing station, encoding using code table 0 02 001 (set to 0, automatic)', verbose_name='Station Type')),
                ('location', django.contrib.gis.db.models.fields.PointField(help_text='Location of the station', srid=4326, verbose_name='Location')),
                ('station_height_above_msl', models.FloatField(blank=True, help_text='Height of the station ground above mean sea level (to 1 decimal place)', null=True, verbose_name='Station Height Above MSL')),
                ('thermometer_height', models.FloatField(blank=True, help_text='Height of thermometer or temperature sensor above the local ground to 2 decimal places', null=True, verbose_name='Thermometer Height')),
                ('barometer_height_above_msl', models.FloatField(blank=True, help_text='Height of the barometer above mean sea level (to 1 decimal place), typically height of station ground plus the height of the sensor above local ground', null=True, verbose_name='Barometer Height Above MSL')),
                ('anemometer_height', models.FloatField(blank=True, help_text='Height of the anemometer above local ground to 2 decimal places', null=True, verbose_name='Anemometer Height')),
                ('rain_sensor_height', models.FloatField(blank=True, help_text='Height of the rain gauge above local ground to 2 decimal place', null=True, verbose_name='Rain Sensor Height')),
                ('method_of_ground_state_measurement', models.PositiveIntegerField(blank=True, choices=[(0, 'Manual observation'), (1, 'Video camera method'), (2, 'Infrared method'), (3, 'Laser method'), (14, 'Others'), (15, 'Missing value')], help_text='Method of observing the snow depth encoded using code table 0 02 177', null=True, verbose_name='Method of Ground State Measurement')),
                ('method_of_snow_depth_measurement', models.PositiveIntegerField(blank=True, help_text='Method of observing the snow depth encoded using code table 0 02 177', null=True, verbose_name='Method of Snow Depth Measurement')),
                ('time_period_of_wind', models.PositiveIntegerField(blank=True, help_text='Time period over which the wind speed and direction have been averaged. 10 minutes in normal cases or the number of minutes since a significant change occuring in the preceeding 10 minutes.', null=True, verbose_name='Time Period of Wind')),
                ('timezone', timezone_field.fields.TimeZoneField(default='UTC', help_text='Timezone used by the station for recording observations', verbose_name='Station Timezone')),
                ('network', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.network', verbose_name='Network')),
            ],
            options={
                'verbose_name': 'Station',
                'verbose_name_plural': 'Stations',
            },
        ),
        migrations.CreateModel(
            name='ObservationRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('time', timescale.db.models.fields.TimescaleDateTimeField(interval='1 day')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('value', models.FloatField(verbose_name='Value')),
                ('is_daily', models.BooleanField(default=False, verbose_name='Is Daily')),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.networkconnection', verbose_name='Network Connection')),
                ('parameter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.dataparameter', verbose_name='Parameter')),
                ('station', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.station', verbose_name='Station')),
            ],
            options={
                'verbose_name': 'Observation Record',
                'verbose_name_plural': 'Observation Records',
                'ordering': ['-time'],
            },
        ),
        migrations.CreateModel(
            name='HourlyAggregatedObservationRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('time', timescale.db.models.fields.TimescaleDateTimeField(interval='1 day')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('min_value', models.FloatField(verbose_name='Min Value')),
                ('max_value', models.FloatField(verbose_name='Max Value')),
                ('avg_value', models.FloatField(verbose_name='Avg Value')),
                ('sum_value', models.FloatField(verbose_name='Sum Value')),
                ('records_count', models.PositiveIntegerField(verbose_name='Records Count')),
                ('parameter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.dataparameter', verbose_name='Parameter')),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.networkconnection', verbose_name='Network Connection')),
                ('station', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.station', verbose_name='Station')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='DailyAggregatedObservationRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('time', timescale.db.models.fields.TimescaleDateTimeField(interval='1 day')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('min_value', models.FloatField(verbose_name='Min Value')),
                ('max_value', models.FloatField(verbose_name='Max Value')),
                ('avg_value', models.FloatField(verbose_name='Avg Value')),
                ('sum_value', models.FloatField(verbose_name='Sum Value')),
                ('records_count', models.PositiveIntegerField(verbose_name='Records Count')),
                ('parameter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.dataparameter', verbose_name='Parameter')),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.networkconnection', verbose_name='Network Connection')),
                ('station', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.station', verbose_name='Station')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='StationLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('network_connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='station_links', to='core.networkconnection', verbose_name='Network Connection')),
                ('polymorphic_ctype', models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='polymorphic_%(app_label)s.%(class)s_set+', to='contenttypes.contenttype')),
                ('station', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.station', verbose_name='Station')),
            ],
        ),
        migrations.CreateModel(
            name='DispatchChannelParameterMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sort_order', models.IntegerField(blank=True, editable=False, null=True)),
                ('channel_parameter', models.CharField(help_text='Parameter name in the channel', max_length=255, verbose_name='Channel Parameter')),
                ('aggregation_measure', models.CharField(choices=[('avg_value', 'Average Value'), ('sum_value', 'Sum Value'), ('min_value', 'Minimum Value'), ('max_value', 'Maximum Value')], default='avg_value', max_length=255, verbose_name='Aggregation Measure')),
                ('dispatch_channel', modelcluster.fields.ParentalKey(on_delete=django.db.models.deletion.CASCADE, related_name='parameter_mappings', to='core.dispatchchannel')),
                ('parameter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.dataparameter', verbose_name='Parameter')),
                ('channel_unit', models.ForeignKey(blank=True, help_text='Unit of the parameter in the channel', null=True, on_delete=django.db.models.deletion.CASCADE, to='core.unit', verbose_name='Channel Unit')),
            ],
        ),
        migrations.AddField(
            model_name='dataparameter',
            name='unit',
            field=models.ForeignKey(help_text='Unit of the variable', on_delete=django.db.models.deletion.CASCADE, to='core.unit', verbose_name='Unit'),
        ),
        migrations.AddConstraint(
            model_name='station',
            constraint=models.UniqueConstraint(fields=('station_id', 'network'), name='unique_station_id_network'),
        ),
        migrations.AddConstraint(
            model_name='observationrecord',
            constraint=models.UniqueConstraint(fields=('time', 'station', 'parameter'), name='unique_station_param_obs_record'),
        ),
        migrations.AlterUniqueTogether(
            name='stationlink',
            unique_together={('network_connection', 'station')},
        ),
        migrations.AlterUniqueTogether(
            name='dispatchchannelparametermapping',
            unique_together={('dispatch_channel', 'parameter')},
        ),
    ]
