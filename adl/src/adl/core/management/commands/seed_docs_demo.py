"""
Seed the deterministic demo state the documentation screenshots are taken
against (docs/screenshots/capture/README.md).

Run on a **fresh** database. The base seed is the same for every plugin —
an admin user, one network, three stations with WIGOS identifiers and the
common data parameters — so every guide's screenshots share one world. The
per-plugin part comes from a fixture file (``--fixture``) describing one
connection of the plugin's type and its station links -- and, for a plugin
that pushes data out, its dispatch channels; see the plugin guides'
``docs/screenshots/fixture.json`` for the shape.

Same input, same rows, same ids: with a fresh database the connection is
always id 1, the station links are ids 1..n in fixture order and the
dispatch channels 1..n likewise, which is what the screenshot manifests
rely on.
"""

import json
import os
import re
from datetime import timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.utils import timezone as dj_timezone

from adl.core.models import (
    DataParameter,
    DispatchChannel,
    Network,
    NetworkConnection,
    Station,
    StationLink,
    Unit,
)

# pint symbols, as the Unit model requires
UNITS = [
    ("Celsius", "degC"),
    ("Percent", "percent"),
    ("Hectopascal", "hPa"),
    ("Millimetre", "mm"),
    ("Metre per second", "m/s"),
    ("Degree", "degree"),
    ("Watt per square metre", "W/m^2"),
    # Imperial units, for sources that report in them (Davis/WeatherLink sends
    # °F, inHg and mph by default). A plugin fixture may only name a unit that
    # exists here, and the point of the demo seed is to serve those fixtures.
    ("Fahrenheit", "degF"),
    ("Inch of mercury", "inHg"),
    ("Mile per hour", "mph"),
    ("Inch", "in"),
    # KMD/KCSAP loggers report wind in knots; the KCSAP decoder declares
    # "knot" as the file unit, so a fixture mapping wind speed has to name it.
    ("Knot", "knot"),
]

PARAMETERS = [
    # name, unit symbol, aggregation
    ("Air Temperature", "degC", "avg"),
    ("Relative Humidity", "percent", "avg"),
    ("Atmospheric Pressure", "hPa", "avg"),
    ("Precipitation", "mm", "sum"),
    ("Wind Speed", "m/s", "avg"),
    ("Wind Direction", "degree", "circular"),
    ("Solar Radiation", "W/m^2", "avg"),
]

# station_id, name, (lon, lat), elevation, wsi_local
STATIONS = [
    ("DEMO001", "Kabete Demo AWS", (36.74, -1.25), 1820.0, "DEMO001"),
    ("DEMO002", "Lodwar Demo AWS", (35.60, 3.12), 506.0, "DEMO002"),
    ("DEMO003", "Mombasa Demo AWS", (39.62, -4.03), 55.0, "DEMO003"),
]

NETWORK_NAME = "Demo AWS Network"

_ENV_RE = re.compile(r"^\$ENV:([A-Za-z_][A-Za-z0-9_]*)(?:\|(.*))?$")
_NOW_RE = re.compile(r"^\$NOW(?:([+-])(\d+)([dhm]))?$")


def resolve_scalar(value):
    """``$ENV:NAME`` / ``$ENV:NAME|default`` and ``$NOW``, ``$NOW-2d``."""
    if not isinstance(value, str):
        return value
    m = _ENV_RE.match(value)
    if m:
        name, default = m.group(1), m.group(2)
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            return default
        raise CommandError(
            f"Fixture references ${name} but it is not set in the environment. "
            "Credentials are supplied at capture time, never committed."
        )
    m = _NOW_RE.match(value)
    if m:
        # Hour-aligned, so file names a plugin derives from the start date land
        # on the mock source's hourly files
        now = dj_timezone.now().replace(minute=0, second=0, microsecond=0)
        if not m.group(1):
            return now
        amount = int(m.group(2))
        unit = {"d": "days", "h": "hours", "m": "minutes"}[m.group(3)]
        delta = timedelta(**{unit: amount})
        return now + delta if m.group(1) == "+" else now - delta
    return value


def resolve_fk(field, value):
    """Look a foreign-key target up by its natural key, so fixtures name
    things the way the admin shows them instead of by database id."""
    if value is None:
        return None
    if isinstance(value, dict):
        return field.related_model.objects.get(**value)
    target = field.related_model
    if issubclass(target, Station):
        return target.objects.get(station_id=value)
    if issubclass(target, Unit):
        return target.objects.filter(symbol=value).first() or target.objects.get(name=value)
    if issubclass(target, (DataParameter, Network, NetworkConnection, StationLink,
                          DispatchChannel)):
        return target.objects.get(name=value) if hasattr(target, "name") else target.objects.get(pk=value)
    if any(f.name == "name" for f in target._meta.fields):
        return target.objects.get(name=value)
    return target.objects.get(pk=value)


def build_fields(model, raw_fields):
    resolved = {}
    for name, value in (raw_fields or {}).items():
        field = model._meta.get_field(name)
        value = resolve_scalar(value)
        if isinstance(field, models.ForeignKey):
            value = resolve_fk(field, value)
        resolved[name] = value
    return resolved


def replace_children(parent, children):
    """``children`` maps a reverse relation name (the ``related_name`` of a
    ParentalKey / ForeignKey on the child) to a list of child field dicts.
    Existing rows of each named relation are replaced."""
    created = {}
    for related_name, rows in (children or {}).items():
        rel = parent._meta.get_field(related_name)
        child_model = rel.related_model
        fk_name = rel.field.name
        child_model.objects.filter(**{fk_name: parent}).delete()
        ids = []
        for row in rows:
            fields = build_fields(child_model, row)
            fields[fk_name] = parent
            obj = child_model(**fields)
            obj.full_clean(exclude=[fk_name])
            obj.save()
            ids.append(obj.pk)
        created[related_name] = ids
    return created


class Command(BaseCommand):
    help = "Seed the demo state used by the documentation screenshot pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--fixture", help="Per-plugin fixture JSON (connection + station links).")
        parser.add_argument("--admin-user", default=os.environ.get("CAPTURE_ADMIN_USER", "admin"))
        parser.add_argument("--admin-password",
                            default=os.environ.get("CAPTURE_ADMIN_PASSWORD", "adl-docs-demo"))

    @transaction.atomic
    def handle(self, *args, **options):
        summary = {"admin": self.seed_admin(options["admin_user"], options["admin_password"])}
        network = self.seed_network()
        summary["network_id"] = network.id
        summary["units"] = self.seed_units()
        summary["parameters"] = self.seed_parameters()
        summary["stations"] = self.seed_stations(network)

        if options["fixture"]:
            summary.update(self.apply_fixture(options["fixture"], network))

        self.stdout.write(json.dumps(summary, default=str, indent=2))

    # -- base seed -----------------------------------------------------------

    def seed_admin(self, username, password):
        user_model = get_user_model()
        user, _ = user_model.objects.get_or_create(
            username=username,
            defaults={"is_staff": True, "is_superuser": True, "email": "admin@example.org"},
        )
        user.is_staff = user.is_superuser = True
        user.set_password(password)
        user.save()
        return username

    def seed_network(self):
        network, _ = Network.objects.get_or_create(name=NETWORK_NAME, defaults={"type": "automatic"})
        return network

    def seed_units(self):
        ids = {}
        for name, symbol in UNITS:
            unit = Unit.objects.filter(symbol=symbol).first()
            if unit is None:
                unit = Unit.objects.create(name=name, symbol=symbol)
            ids[symbol] = unit.id
        return ids

    def seed_parameters(self):
        ids = {}
        for name, symbol, aggregation in PARAMETERS:
            unit = Unit.objects.get(symbol=symbol)
            parameter, _ = DataParameter.objects.get_or_create(
                name=name, defaults={"unit": unit, "aggregation_method": aggregation},
            )
            ids[name] = parameter.id
        return ids

    def seed_stations(self, network):
        ids = {}
        for station_id, name, (lon, lat), elevation, wsi_local in STATIONS:
            station, _ = Station.objects.get_or_create(
                station_id=station_id, network=network,
                defaults={
                    "name": name,
                    "station_type": 0,
                    "location": Point(lon, lat),
                    "wsi_series": 0,
                    "wsi_issuer": 20000,
                    "wsi_issue_number": 0,
                    "wsi_local": wsi_local,
                    "station_height_above_msl": elevation,
                    "thermometer_height": 2.0,
                    "anemometer_height": 10.0,
                    "rain_sensor_height": 1.0,
                },
            )
            ids[station_id] = station.id
        return ids

    # -- per-plugin fixture ---------------------------------------------------

    def apply_fixture(self, path, network):
        with open(path) as f:
            fixture = json.load(f)

        spec = fixture["connection"]
        model = apps.get_model(spec["model"])
        fields = build_fields(model, spec.get("fields"))
        fields.setdefault("network", network)

        # Re-runnable without moving ids: a connection of the same name is
        # updated in place, its child rows rewritten, its links matched by station
        connection = model.objects.filter(name=fields["name"]).first() or model()
        for name, value in fields.items():
            setattr(connection, name, value)
        connection.full_clean()
        connection.save()
        result = {
            "connection_id": connection.id,
            "connection_children": replace_children(connection, spec.get("children")),
            "station_links": [],
        }

        for link_spec in fixture.get("station_links", []):
            link_model = apps.get_model(link_spec["model"])
            link_fields = build_fields(link_model, link_spec.get("fields"))
            link_fields["network_connection"] = connection
            if "station" in link_spec:
                link_fields["station"] = Station.objects.get(station_id=link_spec["station"])
            link = link_model.objects.filter(
                network_connection=connection, station=link_fields["station"]).first() or link_model()
            for name, value in link_fields.items():
                setattr(link, name, value)
            link.full_clean()
            link.save()
            result["station_links"].append({
                "id": link.id,
                "station": link.station.station_id,
                "children": replace_children(link, link_spec.get("children")),
            })

        result["dispatch_channels"] = [
            self.apply_dispatch_channel(spec, connection)
            for spec in fixture.get("dispatch_channels", [])
        ]

        return result

    def apply_dispatch_channel(self, spec, default_connection):
        """
        Seed one dispatch channel -- the outbound half of a plugin, which a
        dispatch plugin's guide screenshots need configured and linked before
        anything can be captured.

        ``network_connections`` is the many-to-many that decides which
        stations a channel sends for. It is named by connection name and
        defaults to the connection this fixture seeded, so a dispatch-only
        plugin's fixture can borrow whatever ingestion connection is
        supplying the data without repeating its name.
        """
        model = apps.get_model(spec["model"])
        fields = build_fields(model, spec.get("fields"))

        channel = model.objects.filter(name=fields["name"]).first() or model()
        for name, value in fields.items():
            setattr(channel, name, value)
        channel.full_clean(exclude=["network_connections"])
        channel.save()

        # M2M has to wait for a pk, so it is set after the save rather than
        # through build_fields.
        names = spec.get("network_connections")
        if names is None:
            connections = [default_connection] if default_connection else []
        else:
            connections = [NetworkConnection.objects.get(name=n) for n in names]
        channel.network_connections.set(connections)

        return {
            "id": channel.id,
            "name": channel.name,
            "network_connections": [c.name for c in connections],
            "children": replace_children(channel, spec.get("children")),
        }
