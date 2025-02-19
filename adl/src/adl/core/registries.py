import logging

from django.core.exceptions import ImproperlyConfigured

from .registry import Registry, Instance

logger = logging.getLogger(__name__)


class Plugin(Instance):
    label = ""
    
    network_connection = None
    
    def __init__(self):
        if not self.label:
            raise ImproperlyConfigured("The label of a plugin must be set.")
    
    def get_urls(self):
        """
        If needed root urls related to the plugin can be added here.

        Example:

            def get_urls(self):
                from . import plugin_urls

                return [
                    path('some-url/', include(plugin_urls, namespace=self.type)),
                ]

            # plugin_urls.py
            from django.urls import path

            urlpatterns = [
                path('plugin-name/some-view', SomeView.as_view(), name='some_view'),
            ]

        :return: A list containing the urls.
        :rtype: list
        """
        
        return []
    
    def get_data(self):
        raise NotImplementedError
    
    def run_process(self, network_connection):
        from .tasks import perform_hourly_aggregation
        
        self.network_connection = network_connection
        
        records_count = self.get_data()
        
        # if we have some data, run aggregate hourly task asynchronously
        if records_count is not None:
            perform_hourly_aggregation.delay(network_connection.id)
        
        return records_count


class PluginRegistry(Registry):
    """
    With the plugin registry it is possible to register new plugins. A plugin is an
    abstraction made specifically for ADL. It allows to develop specific functionalities for different data sources
    """
    
    name = "adl_plugin"
    
    @property
    def urls(self):
        """
        Returns a list of all the urls that are in the registered instances. They
        are going to be added to the root url config.

        :return: The urls of the registered instances.
        :rtype: list
        """
        
        urls = []
        for types in self.registry.values():
            urls += types.get_urls()
        return urls


plugin_registry = PluginRegistry()


class CustomUnitContextRegistry(Registry):
    name = "adl_unit_context_registry"
    
    def get_choices(self):
        """
        Returns the choices for the custom unit context.

        :return: The choices for the custom unit context.
        :rtype: List[Tuple[str, str]]
        """
        
        return [(k, v.label) for k, v in self.registry.items()]


custom_unit_context_registry = CustomUnitContextRegistry()
