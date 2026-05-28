from django.db import migrations


def create_dimensionless_unit(apps, schema_editor):
    Unit = apps.get_model('core', 'Unit')
    Unit.objects.get_or_create(
        symbol='1',
        defaults={
            'name': 'Dimensionless (WMO code)',
            'description': (
                'Dimensionless unit for WMO integer lookup-table codes such as cloud cover '
                '(oktas), cloud type codes, and present weather codes. '
                'Pint recognises "1" as the dimensionless unit.'
            ),
        },
    )


def remove_dimensionless_unit(apps, schema_editor):
    Unit = apps.get_model('core', 'Unit')
    Unit.objects.filter(symbol='1').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0040_dataparameter_is_coded_wmo_code_table'),
    ]

    operations = [
        migrations.RunPython(create_dimensionless_unit, remove_dimensionless_unit),
    ]
