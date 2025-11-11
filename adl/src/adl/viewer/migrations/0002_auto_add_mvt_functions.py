# Created by Erick Otenyo on 2025-11-11 11:39

from django.db import migrations

obs_latest_records_sql = """
CREATE OR REPLACE FUNCTION public.obs_latest_records_mvt(
    z integer, x integer, y integer,
    in_connection_id integer,
    in_parameter_id integer
)
RETURNS bytea
AS $$
WITH
bounds AS (
  SELECT ST_TileEnvelope(z, x, y) AS geom
),
tile_stations AS (
  SELECT
    s.id AS station_id,
    s.name AS station_name,
    ST_Transform(s.location, 3857) AS geom_3857
  FROM core_station s
  CROSS JOIN bounds
  WHERE ST_Intersects(s.location, ST_Transform(bounds.geom, 4326))
),
now_cte AS (
  SELECT now()::timestamptz AS now_ts
),
candidates AS (
  SELECT
    o.station_id,
    o.value,
    o.time,
    ABS(EXTRACT(EPOCH FROM (o.time - n.now_ts))) AS seconds_from_now
  FROM core_observationrecord o
  JOIN tile_stations ts ON ts.station_id = o.station_id
  JOIN now_cte n ON TRUE
  WHERE o.connection_id = in_connection_id
    AND o.parameter_id  = in_parameter_id
    AND o.time BETWEEN (n.now_ts - INTERVAL '90 minutes')
                    AND (n.now_ts + INTERVAL '90 minutes')
),
picked AS (
  SELECT *
  FROM (
    SELECT c.*,
           ROW_NUMBER() OVER (
             PARTITION BY c.station_id
             ORDER BY c.seconds_from_now ASC, c.time DESC
           ) AS rn
    FROM candidates c
  ) q
  WHERE rn = 1
),
data AS (
  SELECT
    p.station_id,
    ts.station_name,
    p.value,
    p.time AT TIME ZONE 'UTC' AS utc_time,
    ts.geom_3857
  FROM picked p
  JOIN tile_stations ts ON ts.station_id = p.station_id
),
mvtgeom AS (
  SELECT
    ST_AsMVTGeom(data.geom_3857, bounds.geom) AS geom,
    station_id,
    station_name,
    value,
    utc_time
  FROM data
  CROSS JOIN bounds
)
SELECT ST_AsMVT(mvtgeom, 'default') FROM mvtgeom;
$$
LANGUAGE sql STABLE PARALLEL SAFE;
"""

obs_nearest_records_sql = """
CREATE OR REPLACE FUNCTION public.obs_nearest_records_mvt(
    z integer, x integer, y integer,
    in_connection_id integer,
    in_parameter_id integer,
    in_datetime timestamptz
)
RETURNS bytea
AS $$
WITH
bounds AS (
  SELECT ST_TileEnvelope(z, x, y) AS geom
),
tile_stations AS (
  SELECT
    s.id AS station_id,
    s.name AS station_name,
    ST_Transform(s.location, 3857) AS geom_3857
  FROM core_station s
  CROSS JOIN bounds
  WHERE ST_Intersects(s.location, ST_Transform(bounds.geom, 4326))
),
candidates AS (
  SELECT
    o.station_id,
    o.value,
    o.time,
    ABS(EXTRACT(EPOCH FROM (o.time - in_datetime))) AS seconds_from_target
  FROM core_observationrecord o
  JOIN tile_stations ts ON ts.station_id = o.station_id
  WHERE o.connection_id = in_connection_id
    AND o.parameter_id  = in_parameter_id
    AND o.time BETWEEN (in_datetime - INTERVAL '45 minutes')
                    AND (in_datetime + INTERVAL '45 minutes')
),
picked AS (
  SELECT *
  FROM (
    SELECT c.*,
           ROW_NUMBER() OVER (
             PARTITION BY c.station_id
             ORDER BY c.seconds_from_target ASC, c.time DESC
           ) AS rn
    FROM candidates c
  ) q
  WHERE rn = 1
),
data AS (
  SELECT
    p.station_id,
    ts.station_name,
    p.value,
    p.time AT TIME ZONE 'UTC' AS utc_time,
    ts.geom_3857
  FROM picked p
  JOIN tile_stations ts ON ts.station_id = p.station_id
),
mvtgeom AS (
  SELECT
    ST_AsMVTGeom(data.geom_3857, bounds.geom) AS geom,
    station_id,
    station_name,
    value,
    utc_time
  FROM data
  CROSS JOIN bounds
)
SELECT ST_AsMVT(mvtgeom, 'default') FROM mvtgeom;
$$
LANGUAGE sql STABLE PARALLEL SAFE;
"""

drop_sql = """
DROP FUNCTION IF EXISTS public.obs_latest_records_mvt(
    integer, integer, integer, integer, integer
);
DROP FUNCTION IF EXISTS public.obs_nearest_records_mvt(
    integer, integer, integer, integer, integer, timestamptz
);
"""

class Migration(migrations.Migration):

    dependencies = [
        ('viewer', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql=obs_latest_records_sql + obs_nearest_records_sql,
            reverse_sql=drop_sql
        ),
    ]
