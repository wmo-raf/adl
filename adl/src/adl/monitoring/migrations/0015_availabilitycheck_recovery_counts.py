from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0014_stationlinkactivitylog_trigger'),
    ]

    operations = [
        migrations.AddField(
            model_name='availabilitycheck',
            name='recovery_fetched',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Recovery Fetched'),
        ),
        migrations.AddField(
            model_name='availabilitycheck',
            name='recovery_saved',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Recovery Saved'),
        ),
    ]
