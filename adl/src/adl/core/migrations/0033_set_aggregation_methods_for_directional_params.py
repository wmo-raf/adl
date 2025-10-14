from django.db import migrations


def set_aggregation_methods(apps, schema_editor):
    """Automatically set aggregation method for known directional parameters"""
    DataParameter = apps.get_model("core", "DataParameter")
    
    # List any parameters with 'degree' unit
    Unit = apps.get_model("core", "Unit")
    try:
        degree_unit = Unit.objects.get(symbol='degree')
        params_with_degrees = DataParameter.objects.filter(
            unit=degree_unit,
            aggregation_method='standard'
        )
        
        if params_with_degrees.exists():
            count = params_with_degrees.count()
            params_with_degrees.update(aggregation_method='circular')
            print(f"Updated {count} parameter(s) to 'circular' aggregation method.")
    
    except Unit.DoesNotExist:
        pass


def reverse_aggregation_methods(apps, schema_editor):
    """Reset all to standard"""
    DataParameter = apps.get_model("core", "DataParameter")
    DataParameter.objects.filter(
        aggregation_method='circular'
    ).update(aggregation_method='standard')


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_dataparameter_aggregation_method"),
    ]
    
    operations = [
        migrations.RunPython(set_aggregation_methods, reverse_aggregation_methods),
    ]
