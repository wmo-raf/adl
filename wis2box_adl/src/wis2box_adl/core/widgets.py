from django.forms import widgets

from wis2box_adl.core.registries import plugin_registry


class PluginSelectWidget(widgets.Select):
    def __init__(self, attrs=None, choices=()):
        blank_choice = [("", "---------")]

        plugin_choices = [(plugin.type, plugin.label) for plugin in plugin_registry.registry.values()]

        super().__init__(attrs, blank_choice + plugin_choices)
