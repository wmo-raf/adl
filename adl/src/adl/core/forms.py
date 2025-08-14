from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Network
from .utils import (
    validate_as_integer
)


class StationLoaderForm(forms.Form):
    file = forms.FileField(label=_("File"), required=True, help_text=_("CSV file"))
    data = forms.JSONField(widget=forms.HiddenInput)
    
    # only allow csv files
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['file'].widget.attrs.update({'accept': '.csv'})
    
    def clean(self):
        cleaned_data = super().clean()
        data = cleaned_data.get("data")
        fields = data.get("fields")
        rows = data.get("rows")
        
        if not fields or not rows:
            self.add_error(None, "No data found in the table.")
            return cleaned_data
        
        fields = data.get("fields")
        rows = data.get("rows")
        
        stations_data = []
        for row in rows:
            data_dict = dict(zip(fields, row))
            
            # strip spaces from the values
            for key, value in data_dict.items():
                if value and isinstance(value, str):
                    data_dict[key] = value.strip()
            
            name = data_dict.get("Station")
            wigos_id = data_dict.get("WIGOS Station Identifier(s)").split("|")[0]
            latitude = data_dict.get("Latitude")
            longitude = data_dict.get("Longitude")
            elevation = data_dict.get("Elevation")
            
            station_data = {
                "name": name,
                "wigos_id": wigos_id,
                "latitude": latitude,
                "longitude": longitude,
                "elevation": elevation
            }
            
            stations_data.append(station_data)
        
        cleaned_data["stations_data"] = stations_data
        
        return cleaned_data


class StationsCSVTemplateDownloadForm(forms.Form):
    network = forms.ModelChoiceField(queryset=Network.objects.all(), label=_("Network"), required=True)


class OSCARStationImportForm(forms.Form):
    STATION_TYPE_CHOICES = (
        (0, _("Automatic")),
        (1, _("Manned")),
        (2, _("Hybrid: both automatic and manned")),
    )
    
    station_id = forms.CharField(label=_("Station ID"), required=True)
    wmo_block_number = forms.CharField(label=_("WMO Block Number"), required=False)
    wmo_station_number = forms.CharField(label=_("WMO Station Number"), required=False,
                                         validators=[validate_as_integer])
    network = forms.ModelChoiceField(queryset=Network.objects.all(), label=_("Assign Network"), required=True)
    station_type = forms.ChoiceField(choices=STATION_TYPE_CHOICES, label=_("Assign Station Type"), required=True,
                                     initial=0)
    oscar_data = forms.JSONField(widget=forms.HiddenInput)


class CreatePredefinedDataParametersForm(forms.Form):
    create_conversion_units = forms.BooleanField(label=_("Create optional conversion Units"),
                                                 required=False,
                                                 initial=True)


class StationIncludeForm(forms.Form):
    """
    Checked = included (no DB row).
    Unchecked = excluded (persist a DispatchChannelStationLink row with disabled=True).
    """
    included_ids = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple
    )
    
    def __init__(self, *args, station_links_qs=None, excluded_ids=None, **kwargs):
        """
        station_links_qs: queryset limited to the CURRENT PAGE
        excluded_ids: a set of station_link IDs already excluded (all pages)
        """
        super().__init__(*args, **kwargs)
        station_links_qs = station_links_qs or []
        excluded_ids = excluded_ids or set()
        
        # Build choices for the current page
        self.fields["included_ids"].choices = [
            (str(sl.id), sl.station.name) for sl in station_links_qs
        ]
        
        # Default checked (included) = all on this page that are NOT in excluded_ids
        initial_included = [str(sl.id) for sl in station_links_qs if sl.id not in excluded_ids]
        self.initial["included_ids"] = initial_included
