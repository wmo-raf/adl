from django.urls import path
from wagtail.admin.viewsets import ViewSetGroup
from wagtail.admin.viewsets.base import ViewSet
from .views import task_monitor


class TaskMonitorViewSet(ViewSet):
    menu_label = "Task Monitor"
    icon = "hourglass-start"
    name = "task-monitor"
    
    def get_urlpatterns(self):
        return [
            path('', task_monitor, name='task_monitor'),
        ]


class MonitoringViewSetGroup(ViewSetGroup):
    menu_label = "Monitoring"
    menu_icon = "desktop"
    add_to_admin_menu = True
    
    items = [
        TaskMonitorViewSet(),
    ]
