from django.core.exceptions import ImproperlyConfigured

from .registry import Registry, Instance


class Plugin(Instance):
    label = ""

    def __init__(self):
        if not self.label:
            raise ImproperlyConfigured("The label of a plugin must be set.")

    def get_data(self):
        raise NotImplementedError

    def parse_data(self):
        raise NotImplementedError

    def load_data(self):
        raise NotImplementedError


class PluginRegistry(Registry):
    """
    With the plugin registry it is possible to register new plugins. A plugin is an
    abstraction made specifically for ADL. It allows to develop specific functionalities for different data sources
    """

    name = "adl_plugin"


plugin_registry = PluginRegistry()
