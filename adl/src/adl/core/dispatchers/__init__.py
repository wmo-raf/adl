import logging
import time

from django.utils import timezone as dj_timezone

from adl.core.utils import get_object_or_none
from adl.monitoring.models import StationLinkActivityLog

logger = logging.getLogger(__name__)


def get_station_channel_records(dispatch_channel, station_id):
    from adl.core.models import (
        StationChannelDispatchStatus,
        ObservationRecord,
        HourlyObsAgg
    )
    
    connection = dispatch_channel.network_connection
    send_agg_data = dispatch_channel.send_aggregated_data
    aggregation_period = dispatch_channel.aggregation_period
    start_date = dispatch_channel.start_date
    
    records_model = ObservationRecord
    time_field = "time"
    
    if send_agg_data and aggregation_period:
        if aggregation_period == "hourly":
            records_model = HourlyObsAgg
            time_field = "bucket"
    
    # get all records for the channel connection and station
    obs_records = records_model.objects.filter(connection_id=connection.id, station_id=station_id)
    
    if start_date:
        obs_records = obs_records.filter(**{f"{time_field}__gte": start_date})
    
    # filter by last upload time
    station_dispatch_status = get_object_or_none(StationChannelDispatchStatus, station_id=station_id,
                                                 channel_id=dispatch_channel.id)
    
    last_sent_obs_time = None
    if station_dispatch_status and station_dispatch_status.last_sent_obs_time:
        last_sent_obs_time = station_dispatch_status.last_sent_obs_time
    
    if last_sent_obs_time:
        logger.debug(f"[DISPATCH] Getting dispatch records for station {station_id} after {last_sent_obs_time}")
        obs_records = obs_records.filter(**{f"{time_field}__gt": last_sent_obs_time})
    
    else:
        logger.debug(f"[DISPATCH] Getting all dispatch records for station {station_id}")
    
    return obs_records.order_by(time_field)


def get_dispatch_channel_data(dispatch_channel):
    channel_name = dispatch_channel.name
    logger.info(f"[DISPATCH] Getting dispatch data for channel '{channel_name}'")
    
    parameter_mappings = dispatch_channel.parameter_mappings.all()
    
    if not parameter_mappings:
        logger.error(
            f"[DISPATCH] No parameter mappings found for dispatch channel {channel_name}. Skipping...")
        return
    
    parameter_mappings_ids = parameter_mappings.values_list("parameter_id", flat=True)
    
    connection = dispatch_channel.network_connection
    send_agg_data = dispatch_channel.send_aggregated_data
    
    parameter_channel_mapping = {
        pm.parameter_id: {
            "channel_parameter": pm.channel_parameter,
            "adl_parameter": pm.parameter,
            "value_field": "value" if not send_agg_data else pm.aggregation_measure,
            "channel_unit": pm.channel_unit
        } for pm in parameter_mappings
    }
    
    # get all station links for the connection
    station_links = connection.station_links.all()
    
    # group by station and by time
    by_station_by_time = {}
    
    logger.debug(f"[DISPATCH] Found {len(station_links)} station links for connection '{connection.name}'")
    
    for station_link in station_links:
        # get all records for the station and channel
        station_channel_records = get_station_channel_records(dispatch_channel, station_link.station_id)
        
        logger.debug(f"[DISPATCH] Found {station_channel_records.count()} records for "
                     f"station {station_link.station_id} and channel '{channel_name}'")
        
        for obs in station_channel_records:
            if obs.station_id not in by_station_by_time:
                by_station_by_time[obs.station_id] = {}
            
            if obs.time not in by_station_by_time[obs.station_id]:
                by_station_by_time[obs.station_id][obs.time] = {
                    "wigos_id": station_link.station.wigos_id,
                    "observations": []
                }
            
            if obs.parameter_id in parameter_mappings_ids:
                by_station_by_time[obs.station_id][obs.time]["observations"].append(obs)
    
    station_records_by_id = {}
    for station_id, time_obs_map in by_station_by_time.items():
        for time, station_record in time_obs_map.items():
            data_values = {}
            obs_list = station_record["observations"]
            wigos_id = station_record["wigos_id"]
            for obs in obs_list:
                key = parameter_channel_mapping[obs.parameter_id]["channel_parameter"]
                data_value = getattr(obs, parameter_channel_mapping[obs.parameter_id]["value_field"])
                channel_unit = parameter_channel_mapping[obs.parameter_id]["channel_unit"]
                
                # convert value to channel unit if necessary
                if channel_unit != obs.parameter.unit:
                    adl_parameter = parameter_channel_mapping[obs.parameter_id]["adl_parameter"]
                    data_value = adl_parameter.convert_value_to_units(data_value, channel_unit)
                
                data_values[key] = data_value
            
            record = {
                "station_id": station_id,
                "wigos_id": wigos_id,
                "timestamp": time,
                "values": data_values
            }
            
            if not station_id in station_records_by_id:
                station_records_by_id[station_id] = []
            
            station_records_by_id[station_id].append(record)
    
    logger.debug(f"[DISPATCH] Prepared {len(station_records_by_id)} station records "
                 f"for dispatch channel '{channel_name}'")
    
    return station_records_by_id


def run_dispatch_channel(dispatcher_id):
    from adl.core.models import DispatchChannel, StationChannelDispatchStatus, StationLink
    dispatch_channel = get_object_or_none(DispatchChannel, id=dispatcher_id)
    network_connection = dispatch_channel.network_connection
    
    if not dispatch_channel:
        logger.error(f"[DISPATCH] Dispatch channel with id {dispatcher_id} does not exist. Skipping...")
        return
    
    data_records_by_station = get_dispatch_channel_data(dispatch_channel)
    
    total_num_of_records = 0
    
    for station_id, data_records in data_records_by_station.items():
        station_link = get_object_or_none(StationLink, station_id=station_id, network_connection=network_connection)
        
        if not station_link:
            logger.error(f"[DISPATCH] Station link for station {station_id} and connection "
                         f"{network_connection.name} does not exist. Skipping...")
            continue
        
        start = time.monotonic()
        log = StationLinkActivityLog.objects.create(
            time=dj_timezone.now(),
            station_link=station_link,
            direction='push',
            dispatch_channel=dispatch_channel,
        )
        
        try:
            num_of_sent_records, last_sent_obs_time = dispatch_channel.send_station_data(station_link, data_records)
            
            previous_sent_obs_time = None
            # update the last sent observation time in the status
            if num_of_sent_records > 0 and last_sent_obs_time:
                
                total_num_of_records += num_of_sent_records
                
                station_dispatch_status = get_object_or_none(
                    StationChannelDispatchStatus,
                    channel_id=dispatch_channel.id,
                    station_id=station_id
                )
                
                if station_dispatch_status:
                    previous_sent_obs_time = station_dispatch_status.last_sent_obs_time
                    station_dispatch_status.last_sent_obs_time = last_sent_obs_time
                    station_dispatch_status.save()
                else:
                    StationChannelDispatchStatus.objects.create(
                        channel_id=dispatch_channel.id,
                        station_id=station_id,
                        last_sent_obs_time=last_sent_obs_time
                    )
            
            log.success = True
            log.records_count = num_of_sent_records
            if previous_sent_obs_time:
                log.obs_start_time = previous_sent_obs_time
            if last_sent_obs_time:
                log.obs_end_time = last_sent_obs_time
        
        
        except Exception as e:
            log.success = False
            log.message = str(e)
            logger.error(f"[DISPATCH] Error while sending data for station {station_link} on channel "
                         f"{dispatch_channel.name}: {e}")
        finally:
            log.duration_ms = (time.monotonic() - start) * 1000
            log.save()
    
    return {"num_of_sent_records": total_num_of_records}
