# Generated by Django 5.1.4 on 2025-01-12 15:56

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_adlsettings_aggregate_from_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='station',
            name='network',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stations', to='core.network', verbose_name='Network'),
        ),
    ]
