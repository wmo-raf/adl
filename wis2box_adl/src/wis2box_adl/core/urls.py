from wis2box_adl.core.registries import plugin_registry

app_name = "wis2box_adl.core"

urlpatterns = []

if plugin_registry.urls:
    urlpatterns += plugin_registry.urls
