from adl.core.registries import Plugin


class PluginNamePlugin(Plugin):
    type = "{{ cookiecutter.project_module }}"
    label = "{{ cookiecutter.project_name }}"

    def get_urls(self):
        return []

    def get_data(self):
        return []
