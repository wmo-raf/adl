from wagtail.admin.forms import WagtailAdminModelForm


class DispatchChannelForm(WagtailAdminModelForm):
    """
    Admin form for dispatch channels.

    modelcluster attaches child rows (parameter mappings) to their channel only
    when the form is saved, so while the form validates, a mapping has no
    channel and ``DispatchChannel.clean_parameter_mapping`` cannot run. This
    form attaches every child row to the channel being edited up front — the
    same object the channel's own fields are cleaned into, so the checks see
    the submitted values, and a new channel without an id is covered too.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # every formset here is a child relation of the channel (its ParentalKeys),
        # so each one's foreign key points at this instance
        for formset in self.formsets.values():
            for form in formset.forms:
                setattr(form.instance, formset.fk.name, self.instance)
