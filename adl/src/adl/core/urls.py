from adl.core.registries import plugin_registry

app_name = "adl.core"

urlpatterns = []

if plugin_registry.urls:
    urlpatterns += plugin_registry.urls
