from wagtail.admin.ui.tables import TitleColumn


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
