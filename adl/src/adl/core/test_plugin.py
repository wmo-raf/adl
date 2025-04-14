from adl.core.models import NetworkConnection
from adl.core.registries import plugin_registry


def test_plugin(conn_id):
    conn = NetworkConnection.objects.get(id=conn_id)
    
    plugin_type = conn.plugin
    plugin = plugin_registry.get(plugin_type)
    
    plugin.run_process(conn)
