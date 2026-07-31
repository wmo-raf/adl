from django.urls import reverse
from wagtail.admin.ui.tables import TitleColumn, Column


class LinkColumnWithIcon(TitleColumn):
    cell_template_name = "wagtailadmin/tables/icon_link_cell.html"
    
    def __init__(
            self,
            name,
            icon_name=None,
            **kwargs
    ):
        super().__init__(name, **kwargs)
        self.icon_name = icon_name
    
    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        
        context.update({
            "icon_name": self.icon_name,
        })
        
        return context


class ConnectionHealthColumn(Column):
    """
    The connection's stored ingestion-diagnostic verdict, as a badge linking
    to the diagnostic page. Reads only the row the periodic sweep persisted
    (the ``health`` reverse relation) — a listing read must never trigger a
    per-connection evaluation cascade.
    """

    cell_template_name = "core/tables/connection_health_cell.html"

    def get_value(self, instance):
        # Reverse one-to-one access raises a DoesNotExist that is also an
        # AttributeError, so getattr covers the no-verdict-yet state
        return getattr(instance, "health", None)

    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        context["diagnostic_url"] = reverse("connection_health", args=[instance.pk])
        return context


class LinkColumn(Column):
    cell_template_name = "wagtailadmin/tables/link_cell.html"
    
    def __init__(
            self,
            name,
            get_url,
            link_attrs=None,
            link_classname=None,
            **kwargs
    ):
        super().__init__(name, **kwargs)
        self._get_url_func = get_url
        self.link_attrs = link_attrs or {}
        self.link_classname = link_classname
    
    def get_link_url(self, instance, parent_context):
        if self._get_url_func:
            return self._get_url_func(instance)
    
    def get_link_attrs(self, instance, parent_context):
        return self.link_attrs.copy()
    
    def get_cell_context_data(self, instance, parent_context):
        context = super().get_cell_context_data(instance, parent_context)
        
        context["link_attrs"] = self.get_link_attrs(instance, parent_context)
        context["link_attrs"]["href"] = context["link_url"] = self.get_link_url(
            instance, parent_context
        )
        if self.link_classname is not None:
            context["link_attrs"]["class"] = self.link_classname
        
        print(context)
        
        return context
