# Generated by Django 5.0.6 on 2024-11-28 19:22

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_networkconnection_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='dispatchchannel',
            name='network_connection',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, related_name='dispatch_channels', to='core.networkconnection', verbose_name='Network Connection'),
            preserve_default=False,
        ),
        migrations.DeleteModel(
            name='NetworkDispatchChannel',
        ),
    ]