# Generated by Django 5.1.4 on 2025-01-10 20:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_networkconnection_is_daily_data_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='observationrecord',
            name='unique_station_param_obs_record',
        ),
        migrations.AddConstraint(
            model_name='observationrecord',
            constraint=models.UniqueConstraint(fields=('time', 'station', 'connection', 'parameter'), name='unique_station_conn_param_obs_record'),
        ),
    ]
