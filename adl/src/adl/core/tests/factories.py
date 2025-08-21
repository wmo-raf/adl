import factory
from django.contrib.gis.geos import Point

from adl.core import models


class NetworkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Network
    
    name = factory.Sequence(lambda n: f"Network-{n}")
    type = "automatic"


class StationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Station
    
    station_id = factory.Sequence(lambda n: f"ST-{n:04d}")
    name = factory.Sequence(lambda n: f"Station {n}")
    network = factory.SubFactory(NetworkFactory)
    station_type = 0
    location = Point(36.8, -1.3)  # lon, lat (Nairobi-ish)
    wsi_series = 0
    wsi_issuer = 0
    wsi_issue_number = 0
    wsi_local = "0"


class UnitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Unit
    
    name = factory.Sequence(lambda n: f"Unit {n}")
    symbol = factory.Sequence(lambda n: f"U{n}")


class CelsiusUnitFactory(UnitFactory):
    name = "Celsius"
    symbol = "degC"


class KelvinUnitFactory(UnitFactory):
    name = "Kelvin"
    symbol = "K"


class DataParameterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.DataParameter
    
    name = factory.Sequence(lambda n: f"param_{n}")
    unit = factory.SubFactory(CelsiusUnitFactory)  # default to degC


class NetworkConnectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.NetworkConnection
    
    name = factory.Sequence(lambda n: f"Conn-{n}")
    network = factory.SubFactory(NetworkFactory)
    plugin = "test_plugin"
    stations_timezone = "Africa/Nairobi"
    is_daily_data = False


class StationLinkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.StationLink
    
    network_connection = factory.SubFactory(NetworkConnectionFactory)
    station = factory.SubFactory(StationFactory)
    enabled = True
    use_connection_timezone = True
    timezone_info = "UTC"
