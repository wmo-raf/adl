# Generated by Django 5.1.4 on 2025-01-16 09:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_alter_dailyaggregatedobservationrecord_connection_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='adlsettings',
            name='aggregate_from_date',
        ),
        migrations.AddField(
            model_name='stationlink',
            name='aggregate_from_date',
            field=models.DateTimeField(blank=True, help_text='Date to start aggregation from. Leave empty to use the current date and time', null=True, verbose_name='Aggregate Start Date'),
        ),
    ]
