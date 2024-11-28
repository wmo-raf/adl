from django.apps import AppConfig

from adl.core.registries import plugin_registry


class PluginNameConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = "{{ cookiecutter.project_module }}"

    def ready(self):
        from .plugins import PluginNamePlugin

        plugin_registry.register(PluginNamePlugin())
