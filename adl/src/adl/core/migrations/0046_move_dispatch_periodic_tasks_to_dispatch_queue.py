from django.db import migrations

OLD_QUEUE = "adl"
NEW_QUEUE = "dispatch"
DISPATCH_TASK_NAME = "adl.core.tasks.perform_channel_dispatch"


def move_to_dispatch_queue(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(task=DISPATCH_TASK_NAME, queue=OLD_QUEUE).update(queue=NEW_QUEUE)


def move_back_to_adl_queue(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(task=DISPATCH_TASK_NAME, queue=NEW_QUEUE).update(queue=OLD_QUEUE)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0045_dispatchchannelheartbeat"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(move_to_dispatch_queue, move_back_to_adl_queue),
    ]
