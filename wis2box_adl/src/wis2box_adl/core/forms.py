from django import forms
from django.contrib.gis.geos import Point
from django.utils.translation import gettext_lazy as _

from .models import Network
from .utils import (
    is_valid_wigos_id,
    get_wigos_id_parts,
    validate_as_integer
)


class StationLoaderForm(forms.Form):
    network = forms.ModelChoiceField(queryset=Network.objects.all(), label=_("Network"), required=True)
    file = forms.FileField(label=_("File"), required=True, help_text=_("CSV file"))
    data = forms.JSONField(widget=forms.HiddenInput)
    update_existing = forms.BooleanField(label=_("Update existing"),
                                         help_text=_("Update existing stations if found"),
                                         required=False, initial=True)

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

            wigos_id = data_dict.get("wigos_id")
            latitude = data_dict.get("latitude")
            longitude = data_dict.get("longitude")

            point = Point(x=longitude, y=latitude)
            data_dict.update({
                "location": point
            })

            # delete latitude and longitude from the dict
            del data_dict["latitude"]
            del data_dict["longitude"]

            if wigos_id and is_valid_wigos_id(wigos_id):
                wigos_id_parts = get_wigos_id_parts(wigos_id)
                data_dict.update({**wigos_id_parts})

                # delete wigos_id from the dict
                del data_dict["wigos_id"]

            stations_data.append(data_dict)

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
