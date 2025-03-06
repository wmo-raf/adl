from django.apps import AppConfig
from django.db.models.signals import post_save


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'adl.core'
    
    def ready(self):
        from .models import NetworkConnection, DispatchChannel
        from .tasks import update_network_plugin_periodic_task, update_dispatch_channel_periodic_tasks
        
        # update plugin periodic task when a network connection plugin is saved
        network_connection_models = NetworkConnection.__subclasses__()
        for model in network_connection_models:
            post_save.connect(update_network_plugin_periodic_task, sender=model)
        
        # update dispatch channel period tasks when DispatchChannel is saved
        dispatch_channel_models = DispatchChannel.__subclasses__()
        
        for model in dispatch_channel_models:
            post_save.connect(update_dispatch_channel_periodic_tasks, sender=model)
