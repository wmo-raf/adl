from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0039_adlsettings_logo_adlsettings_organisation_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='dataparameter',
            name='is_coded',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Check if values are WMO integer lookup-table codes rather than physical measurements '
                    '(e.g. cloud cover in oktas, cloud type, present weather code). '
                    'Pint unit conversion is skipped for coded parameters. '
                    'The manual entry form renders a dropdown instead of a number input.'
                ),
                verbose_name='Is Coded Value',
            ),
        ),
        migrations.AddField(
            model_name='dataparameter',
            name='wmo_code_table',
            field=models.CharField(
                blank=True,
                default='',
                help_text=(
                    'WMO code table identifier used to render dropdown choices in the entry form '
                    "(e.g. '2700' for cloud cover in oktas, '0513' for low cloud type CL). "
                    'Leave blank for physical-quantity parameters.'
                ),
                max_length=10,
                verbose_name='WMO Code Table',
            ),
        ),
    ]
