from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone as dj_tz

from adl.core.models import ObservationRecord
from .factories import (
    StationLinkFactory,
    DataParameterFactory,
    UnitFactory,
    StationFactory,
)


class ModelExtrasTests(TestCase):
    def test_station_wigos_id_format(self):
        s = StationFactory(wsi_series=1, wsi_issuer=2, wsi_issue_number=3, wsi_local="ABC")
        self.assertEqual(s.wigos_id, "1-2-3-ABC")

    def test_stationlink_timezone_switch(self):
        sl = StationLinkFactory(use_connection_timezone=True, timezone_info="UTC")
        # when use_connection_timezone=True, we expect connection tz (Africa/Nairobi)
        self.assertIn("Africa/Nairobi", str(sl.timezone))
        # flip to station's own tz
        sl.use_connection_timezone = False
        self.assertIn("UTC", str(sl.timezone))

    def test_cannot_change_parameter_unit_if_records_exist(self):
        param = DataParameterFactory()
        other_unit = UnitFactory(name="Millimetre", symbol="mm")
        sl = StationLinkFactory()

        ObservationRecord.objects.create(
            station=sl.station,
            connection=sl.network_connection,
            parameter=param,
            value=1.0,
            time=dj_tz.now(),
        )

        # attempting to change parameter.unit should fail validation
        param.unit = other_unit
        with self.assertRaises(ValidationError):
            param.clean()
