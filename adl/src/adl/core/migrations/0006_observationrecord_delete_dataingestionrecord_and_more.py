# Generated by Django 5.0.6 on 2024-11-28 21:03

import django.db.models.deletion
import timescale.db.models.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_auto_20241128_1952'),
    ]

    operations = [
        migrations.CreateModel(
            name='ObservationRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('time', timescale.db.models.fields.TimescaleDateTimeField(interval='1 day')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('value', models.FloatField(verbose_name='Value')),
                ('parameter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.dataparameter', verbose_name='Parameter')),
                ('station', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.station', verbose_name='Station')),
            ],
            options={
                'verbose_name': 'Observation Record',
                'verbose_name_plural': 'Observation Records',
                'ordering': ['-time'],
            },
        ),
        migrations.DeleteModel(
            name='DataIngestionRecord',
        ),
        migrations.AddConstraint(
            model_name='observationrecord',
            constraint=models.UniqueConstraint(fields=('time', 'station', 'parameter'), name='unique_station_param_obs_record'),
        ),
    ]
