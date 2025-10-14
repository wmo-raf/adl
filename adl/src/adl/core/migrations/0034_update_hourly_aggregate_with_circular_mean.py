from django.db import migrations


def forwards_update_cagg(apps, schema_editor):
    tbl = apps.get_model("core", "ObservationRecord")._meta.db_table
    param_tbl = apps.get_model("core", "DataParameter")._meta.db_table
    
    # Step 1: Remove existing refresh policy
    schema_editor.execute("""
        SELECT remove_continuous_aggregate_policy('obs_agg_1h', if_exists => true);
    """)
    
    # Step 2: Drop existing views (wrapper first, then materialized view)
    schema_editor.execute("""
        DROP VIEW IF EXISTS obs_agg_1h_v;
        DROP MATERIALIZED VIEW IF EXISTS obs_agg_1h;
    """)
    
    # Step 3: Create circular mean function
    # FIXED: Using double precision instead of numeric
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION circular_mean_agg(input_values double precision[])
        RETURNS double precision AS $$
        DECLARE
          sin_sum double precision := 0;
          cos_sum double precision := 0;
          mean_angle double precision;
          val double precision;
        BEGIN
          IF array_length(input_values, 1) IS NULL OR array_length(input_values, 1) = 0 THEN
            RETURN NULL;
          END IF;
          
          FOREACH val IN ARRAY input_values LOOP
            sin_sum := sin_sum + sin(radians(val));
            cos_sum := cos_sum + cos(radians(val));
          END LOOP;
          
          mean_angle := degrees(atan2(sin_sum, cos_sum));
          
          -- Normalize to 0-360
          IF mean_angle < 0 THEN
            mean_angle := mean_angle + 360;
          END IF;
          
          RETURN mean_angle;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
    """)
    
    # Step 4: Create new continuous aggregate with circular mean support
    schema_editor.execute(f"""
        CREATE MATERIALIZED VIEW obs_agg_1h
        WITH (timescaledb.continuous) AS
        SELECT
          obs.station_id,
          obs.connection_id,
          obs.parameter_id,
          time_bucket('1 hour', obs.time) AS bucket,
          MIN(obs.value)  AS min_value,
          MAX(obs.value)  AS max_value,
          
          -- Use parameter's aggregation_method flag
          CASE
            WHEN param.aggregation_method = 'circular' THEN
              circular_mean_agg(array_agg(obs.value))
            ELSE
              AVG(obs.value)
          END AS avg_value,
          
          SUM(obs.value)  AS sum_value,
          COUNT(*)        AS records_count
        FROM {tbl} obs
        INNER JOIN {param_tbl} param ON param.id = obs.parameter_id
        WHERE obs.is_daily = false
        GROUP BY obs.station_id, obs.connection_id, obs.parameter_id, bucket, param.aggregation_method
        WITH NO DATA;

        ALTER MATERIALIZED VIEW obs_agg_1h
        SET (timescaledb.materialized_only = false);

        CREATE INDEX IF NOT EXISTS obs_agg_1h_idx
          ON obs_agg_1h (station_id, connection_id, parameter_id, bucket);
    """)
    
    # Step 5: Recreate wrapper view
    schema_editor.execute("""
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
    
    # Step 6: Add refresh policy
    schema_editor.execute("""
        SELECT add_continuous_aggregate_policy(
          'obs_agg_1h',
          start_offset      => INTERVAL '90 days',
          end_offset        => INTERVAL '1 hour',
          schedule_interval => INTERVAL '5 minutes'
        );
    """)
    
    print("\n" + "="*60)
    print("IMPORTANT: Continuous aggregate structure updated!")
    print("You MUST manually refresh the aggregate to recalculate existing data.")
    print("Run: python manage.py refresh_hourly_agg")
    print("="*60 + "\n")


def backwards_revert_cagg(apps, schema_editor):
    """Revert to the original simple aggregate without circular mean"""
    
    tbl = apps.get_model("core", "ObservationRecord")._meta.db_table
    
    # Remove policy and views
    schema_editor.execute("""
        SELECT remove_continuous_aggregate_policy('obs_agg_1h', if_exists => true);
        DROP VIEW IF EXISTS obs_agg_1h_v;
        DROP MATERIALIZED VIEW IF EXISTS obs_agg_1h;
        DROP FUNCTION IF EXISTS circular_mean_agg(double precision[]);
    """)
    
    # Recreate original simple aggregate
    schema_editor.execute(f"""
        CREATE MATERIALIZED VIEW obs_agg_1h
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

        SELECT add_continuous_aggregate_policy(
          'obs_agg_1h',
          start_offset      => INTERVAL '90 days',
          end_offset        => INTERVAL '1 hour',
          schedule_interval => INTERVAL '5 minutes'
        );
    """)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0033_set_aggregation_methods_for_directional_params"),
    ]
    
    operations = [
        migrations.RunPython(forwards_update_cagg, backwards_revert_cagg),
    ]