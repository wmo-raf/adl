from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'adl.core'

    def ready(self):
        from .models import NetworkConnection, DispatchChannel
        from .tasks import (
            delete_dispatch_channel_periodic_tasks,
            delete_network_plugin_periodic_tasks,
            update_dispatch_channel_periodic_tasks,
            update_network_plugin_periodic_task,
        )

        # update plugin periodic task when a network connection plugin is saved
        network_connection_models = NetworkConnection.__subclasses__()
        for model in network_connection_models:
            post_save.connect(update_network_plugin_periodic_task, sender=model)

        # update dispatch channel period tasks when DispatchChannel is saved
        dispatch_channel_models = DispatchChannel.__subclasses__()

        for model in dispatch_channel_models:
            post_save.connect(update_dispatch_channel_periodic_tasks, sender=model)

        # A deleted connection or channel must take its beat schedule entry
        # with it — otherwise the entry stays enabled and keeps firing against
        # an id that no longer exists. The base models are connected alongside
        # the subclasses so a delete issued through the base manager is covered
        # too; the receivers are idempotent, so being called twice is a no-op.
        for model in [NetworkConnection, *network_connection_models]:
            post_delete.connect(delete_network_plugin_periodic_tasks, sender=model)

        for model in [DispatchChannel, *dispatch_channel_models]:
            post_delete.connect(delete_dispatch_channel_periodic_tasks, sender=model)
