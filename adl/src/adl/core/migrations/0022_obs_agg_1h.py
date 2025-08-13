# Manually created on 2025-08-13 19:30
from django.db import migrations


def forwards_create_cagg(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    tbl = apps.get_model("core", "ObservationRecord")._meta.db_table
    schema_editor.execute(f"""
        -- 1) Continuous aggregate (no md5/id inside; note WITH NO DATA)
        CREATE MATERIALIZED VIEW IF NOT EXISTS obs_agg_1h
        WITH (timescaledb.continuous) AS
        SELECT
          station_id,
          connection_id,
          parameter_id,
          time_bucket('1 hour', time) AS bucket,
          MIN(value)  AS min_value,
          MAX(value)  AS max_value,
          AVG(value)  AS avg_value,
          SUM(value)  AS sum_value,
          COUNT(*)    AS records_count
        FROM {tbl}
        WHERE is_daily = false
        GROUP BY station_id, connection_id, parameter_id, bucket
        WITH NO DATA;

        ALTER MATERIALIZED VIEW obs_agg_1h
        SET (timescaledb.materialized_only = false);

        CREATE INDEX IF NOT EXISTS obs_agg_1h_idx
          ON obs_agg_1h (station_id, connection_id, parameter_id, bucket);

        -- 2) Wrapper view that adds a deterministic primary key for Django
        CREATE OR REPLACE VIEW obs_agg_1h_v AS
        SELECT
          md5(
            station_id::text || ':' ||
            connection_id::text || ':' ||
            parameter_id::text || ':' ||
            extract(epoch from bucket)::text
          ) AS id,
          station_id,
          connection_id,
          parameter_id,
          bucket,
          min_value,
          max_value,
          avg_value,
          sum_value,
          records_count
        FROM obs_agg_1h;
    """)


def backwards_drop_cagg(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
                          DROP VIEW IF EXISTS obs_agg_1h_v;
                          DROP
                          MATERIALIZED VIEW IF EXISTS obs_agg_1h;
                          """)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_networkconnection_stations_timezone_and_more"),
    ]
    
    operations = [
        migrations.RunPython(forwards_create_cagg, backwards_drop_cagg),
        migrations.RunSQL(
            # 3) Refresh policy (separate op; reversible)
            """
            SELECT add_continuous_aggregate_policy(
              'obs_agg_1h',
              start_offset      => INTERVAL '90 days',
              end_offset        => INTERVAL '1 hour',
              schedule_interval => INTERVAL '5 minutes'
            );
            """,
            reverse_sql="SELECT remove_continuous_aggregate_policy('obs_agg_1h');",
        ),
    ]
