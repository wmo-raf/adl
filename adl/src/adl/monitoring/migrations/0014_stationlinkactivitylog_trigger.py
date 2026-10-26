from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0013_availabilitycheck_parameter'),
    ]

    operations = [
        migrations.AddField(
            model_name='stationlinkactivitylog',
            name='trigger',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
    ]
