from celery import Celery

app = Celery("wis2box_adl")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
