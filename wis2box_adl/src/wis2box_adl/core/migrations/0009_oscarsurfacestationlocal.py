# Generated by Django 5.0.6 on 2024-10-28 09:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_alter_station_wmo_station_number'),
    ]

    operations = [
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
    ]