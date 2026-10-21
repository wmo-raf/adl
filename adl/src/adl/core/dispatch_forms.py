from django.forms.formsets import DELETION_FIELD_NAME
from wagtail.admin.forms import WagtailAdminModelForm


class ParameterMappingRowForm(WagtailAdminModelForm):
    """
    One row of the parameter matching panel: a fixed destination column, with
    the ADL parameter chosen for it, if any.

    Every column is always submitted, so the row's parameter is what decides
    whether a mapping exists. A new row with no parameter is an empty row and
    saves nothing; an existing row whose parameter is cleared is deleted.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parameter"].required = False

    def has_parameter(self):
        return bool(self["parameter"].value())

    def has_changed(self):
        if self.instance.pk is None and not self.has_parameter():
            return False
        return super().has_changed()

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.pk and not cleaned_data.get("parameter"):
            cleaned_data[DELETION_FIELD_NAME] = True
        return cleaned_data


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
