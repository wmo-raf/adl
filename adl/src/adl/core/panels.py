from types import SimpleNamespace

from django import forms
from django.forms.formsets import DELETION_FIELD_NAME, ORDERING_FIELD_NAME, ManagementForm
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import InlinePanel, Panel

from .dispatch_forms import ParameterMappingFormSet, ParameterMappingRowForm, is_live_mapping_form


class IngestTimeoutBudgetPanel(Panel):
    """
    Shows the per-station ingestion timeout an operator actually gets, once the
    batch soft limit is clamped to the connection's beat interval.

    Three fields — ``ingest_timeout_seconds``, ``batch_size`` and
    ``plugin_processing_interval`` — combine into one effective figure that
    matches none of them, and at stock defaults the configured 300s is really
    90s. Decision #153 settled that the admin displays the computed number
    rather than leaving operators to derive it.

    The figure is computed from the *saved* instance, so it lags the form until
    the next save; the template says so rather than implying it is live.
    """

    class BoundPanel(Panel.BoundPanel):
        template_name = "core/panels/ingest_timeout_budget.html"

        def is_shown(self):
            # Nothing meaningful to compute before the first save, and an
            # unsaved instance would show numbers the operator never chose.
            return self.instance is not None and self.instance.pk is not None

        def get_context_data(self, parent_context=None):
            context = super().get_context_data(parent_context)

            from adl.core.tasks import (
                effective_ingest_batch_size,
                effective_ingest_station_seconds,
                ingest_batch_soft_limit_seconds,
            )

            connection = self.instance
            batch_size = effective_ingest_batch_size(connection)
            configured = connection.ingest_timeout_seconds
            effective = effective_ingest_station_seconds(connection)

            context.update({
                "batch_size": batch_size,
                "interval_minutes": connection.plugin_processing_interval,
                "configured_seconds": configured,
                "effective_seconds": effective,
                "batch_limit_seconds": ingest_batch_soft_limit_seconds(connection, batch_size),
                # Only a full batch that would outrun the interval gets cut back
                "is_clamped": effective < configured,
            })

            return context


def group_by_section(columns):
    """Columns grouped by section, sections in the order the spec first reaches them."""
    sections = []
    for column in columns:
        if column.section not in sections:
            sections.append(column.section)
    return sorted(columns, key=lambda column: sections.index(column.section))


class ParameterMappingPanel(InlinePanel):
    """
    A dispatch channel's parameter mappings as a side-by-side matching table:
    one fixed row per destination column, each with a dropdown of the ADL
    parameters whose unit fits it.

    For channels whose ``get_parameter_mapping_spec()`` returns their
    destination columns; channels without a spec use the plain inline panel
    (``DispatchChannel.parameter_panels``) instead.

    The rows are the ``parameter_mappings`` child formset, so mappings save in
    the same submission as the channel. Every column is submitted on every
    save; :class:`~adl.core.dispatch_forms.ParameterMappingRowForm` decides
    from each row's parameter whether a mapping is created, kept or deleted.
    Mappings that fit no row are listed under the table, with their errors,
    so the form never refuses to save for a reason the page does not show.
    """

    def get_form_options(self):
        options = super().get_form_options()
        options["formsets"][self.relation_name]["form"] = ParameterMappingRowForm
        options["formsets"][self.relation_name]["formset"] = ParameterMappingFormSet
        return options

    class BoundPanel(Panel.BoundPanel):
        template_name = "core/panels/parameter_matching.html"

        class Media:
            css = {"all": ["adl/css/parameter_matching.css"]}
            js = ["adl/js/parameter_matching.js"]

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.label = self.panel.label
            if self.form is None:
                return

            from adl.core.models import DataParameter

            self.formset = self.form.formsets[self.panel.relation_name]
            self.columns = self.form.instance.get_parameter_mapping_spec()
            self.parameters = list(DataParameter.objects.select_related("unit").order_by("name"))
            self.aggregating = bool(self.form["send_aggregated_data"].value())
            self.aggregation_choices = self.formset.empty_form.fields["aggregation_measure"].choices
            self.fits = {}

            instance = self.form.instance
            # switching the spec leaves some mappings without a column: they are removed on save,
            # so they are listed, and not shown as unrecognised
            self.dropped = [
                subform for subform in self.formset.forms
                if subform.instance.pk and instance.is_parameter_mapping_dropped(subform["channel_parameter"].value())
            ]
            forms_by_column, self.unrecognised = instance.match_parameter_mappings(
                [subform for subform in self.formset.forms if subform not in self.dropped],
                lambda subform: subform["channel_parameter"].value(),
                is_live_mapping_form,
            )

            total = len(self.formset.forms)
            self.row_forms = []
            for column in self.ordered_columns():
                subform = forms_by_column.get(column.name)
                if subform is None:
                    subform = self.new_row_form(total, column)
                    total += 1
                self.row_forms.append((column, subform))

            self.management_form = ManagementForm(
                auto_id=self.formset.auto_id,
                prefix=self.formset.prefix,
                initial={
                    "TOTAL_FORMS": total,
                    "INITIAL_FORMS": self.formset.initial_form_count(),
                    "MIN_NUM_FORMS": self.formset.min_num,
                    "MAX_NUM_FORMS": self.formset.max_num,
                },
                renderer=self.formset.renderer,
            )

            for position, (column, subform) in enumerate(self.row_forms, start=1):
                self.hide_bookkeeping_fields(subform, position)
            for subform in self.dropped:
                self.hide_bookkeeping_fields(subform, 0)
            saved_columns = {column.name: column for column in instance.get_saved_parameter_mapping_spec() or []}
            self.parked = [
                self.row_context(saved_columns[subform["channel_parameter"].value()], subform, {})
                for subform in self.dropped
            ]
            for position, (subform, reason) in enumerate(self.unrecognised, start=len(self.row_forms) + 1):
                self.hide_bookkeeping_fields(subform, position)
                subform.fields[DELETION_FIELD_NAME].widget = forms.CheckboxInput(attrs={"data-role": "delete"})
                self.offer_reassignment(subform, forms_by_column)

        def offer_reassignment(self, subform, forms_by_column):
            """
            Let an unrecognised mapping be moved to a column: the columns without a live mapping
            whose unit fits its parameter. The first choice keeps the stored name, so a form posted
            unchanged is still refused rather than silently reassigned.
            """
            current = subform["channel_parameter"].value() or ""
            parameter = subform.instance.parameter if subform.instance.parameter_id else None
            choices = [(current, _("Choose a column…"))]
            for column in self.ordered_columns():
                taken = column.name in forms_by_column and is_live_mapping_form(forms_by_column[column.name])
                if column.name == current or taken:
                    continue
                if parameter is not None and not self.column_fits(column, parameter):
                    continue
                choices.append((column.name, column.name))
            subform.fields["channel_parameter"].widget = forms.Select(
                choices=choices, attrs={"data-role": "reassign", "aria-label": _("Reassign to a column")},
            )

        def ordered_columns(self):
            return group_by_section(self.columns)

        def new_row_form(self, index, column):
            """An empty row for a column with no mapping yet, numbered after the formset's own forms."""
            subform = self.formset.form(
                prefix=self.formset.add_prefix(index),
                auto_id=self.formset.auto_id,
                initial={"channel_parameter": column.name, "aggregation_measure": column.default_aggregation},
                empty_permitted=True,
                use_required_attribute=False,
                renderer=self.formset.renderer,
                **self.formset.get_form_kwargs(index),
            )
            self.formset.add_fields(subform, index)
            return subform

        def hide_bookkeeping_fields(self, subform, position):
            subform.fields["channel_parameter"].widget = forms.HiddenInput()
            subform.fields[DELETION_FIELD_NAME].widget = forms.HiddenInput()
            if self.formset.can_order:
                # rows save in table order; a submitted form keeps the order it was posted with
                subform.fields[ORDERING_FIELD_NAME].widget = forms.HiddenInput()
                subform.fields[ORDERING_FIELD_NAME].initial = position

        def column_fits(self, column, parameter):
            # the same unit checks repeat for every row, so remember them per unit and context
            key = (column.name, column.unit, column.unit_context, parameter.unit.symbol, parameter.custom_unit_context)
            if key not in self.fits:
                self.fits[key] = column.accepts_unit_of(parameter)
            return self.fits[key]

        def selected_parameters(self):
            """ADL parameter id -> the column it is chosen for, across every row."""
            selected = {}
            for column, subform in self.row_forms:
                value = subform["parameter"].value()
                if value:
                    selected[str(value)] = column.name
            return selected

        def parameter_options(self, column, subform, selected):
            current = str(subform["parameter"].value() or "")
            options = []
            for parameter in self.parameters:
                value = str(parameter.pk)
                fits = self.column_fits(column, parameter)
                if not fits and value != current:
                    continue
                used_in = selected.get(value)
                taken = used_in is not None and used_in != column.name
                if not fits:
                    # keep a mapping that no longer fits on the page, so saving reports it
                    # instead of dropping it from the dropdown and deleting it
                    label = _("%(name)s (in %(unit)s, which does not fit)") % {
                        "name": parameter.name, "unit": parameter.unit.symbol,
                    }
                elif taken:
                    label = _("%(name)s (used in %(column)s)") % {"name": parameter.name, "column": used_in}
                else:
                    label = parameter.name
                options.append({
                    "value": value,
                    "label": label,
                    "name": parameter.name,
                    "selected": value == current,
                    "disabled": taken,
                })
            return options

        def aggregation_options(self, subform):
            current = subform["aggregation_measure"].value()
            return [
                {"value": value, "label": label, "selected": value == current}
                for value, label in self.aggregation_choices
            ]

        def row_context(self, column, subform, selected):
            aggregation = subform["aggregation_measure"].value()
            choice_labels = dict(self.aggregation_choices)
            return {
                "column": column,
                "form": subform,
                "parameter_field": subform["parameter"],
                "parameter_options": self.parameter_options(column, subform, selected),
                "aggregation_field": subform["aggregation_measure"],
                "aggregation_options": self.aggregation_options(subform),
                "default_aggregation_label": choice_labels.get(column.default_aggregation),
                "overridden": self.aggregating and subform.has_parameter()
                              and aggregation != column.default_aggregation,
            }

        def rows(self):
            selected = self.selected_parameters()
            sections = []
            for column, subform in self.row_forms:
                if not sections or sections[-1]["key"] != column.section:
                    sections.append({"key": column.section, "label": column.section_label, "rows": []})
                sections[-1]["rows"].append(self.row_context(column, subform, selected))
            return sections

        def spec_data(self):
            """
            Every spec the channel can be switched to, with the ADL parameters that fit each column,
            for the script to rebuild the rows without another request. ``None`` when the spec is fixed.
            """
            instance = self.form.instance
            field = instance.parameter_mapping_spec_field
            specs = instance.get_parameter_mapping_specs()
            if not field or len(specs) < 2:
                return None
            data = {"field": self.form[field].auto_id, "templates": {}, "fits": {}, "parameters": {}}
            data["labels"] = {
                "doesNotFit": str(_("%(name)s (in %(unit)s, which does not fit)")),
                "parameterFor": str(_("ADL parameter for %(column)s")),
                "aggregationFor": str(_("Aggregation for %(column)s")),
            }
            for parameter in self.parameters:
                data["parameters"][str(parameter.pk)] = [parameter.name, parameter.unit.symbol]
            for key, (label, columns) in specs.items():
                data["templates"][key] = {"label": str(label), "columns": [
                    {
                        "name": column.name,
                        "unit": column.unit or "",
                        "hint": str(column.hint or ""),
                        "section": column.section,
                        "sectionLabel": str(column.section_label),
                        "defaultAggregation": column.default_aggregation,
                    } for column in group_by_section(columns)
                ]}
                data["fits"][key] = {
                    column.name: [p.pk for p in self.parameters if self.column_fits(column, p)]
                    for column in columns
                }
            return data

        def prototype_row(self):
            """A row for a column the current template lacks, numbered ``__prefix__`` for the script to fill in."""
            subform = self.formset.empty_form
            self.hide_bookkeeping_fields(subform, 0)
            return {
                "column": SimpleNamespace(name="", unit=None, hint=None, default_aggregation="avg_value"),
                "form": subform,
                "parameter_field": subform["parameter"],
                "parameter_options": [],
                "aggregation_field": subform["aggregation_measure"],
                "aggregation_options": self.aggregation_options(subform),
                "default_aggregation_label": None,
                "overridden": False,
            }

        def get_context_data(self, parent_context=None):
            context = super().get_context_data(parent_context)
            spec_data = self.spec_data()
            context.update({
                "prototype": self.prototype_row() if spec_data else None,
                "spec_data": spec_data,
                "parked": self.parked,
                "sections": self.rows(),
                "unrecognised": self.unrecognised,
                "management_form": self.management_form,
                "aggregating": self.aggregating,
                "non_form_errors": self.formset.non_form_errors(),
                # the script relabels options as rows change; it fills in this translated pattern
                "used_in_label": _("%(name)s (used in %(column)s)"),
            })
            return context
