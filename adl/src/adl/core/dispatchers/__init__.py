import logging

from adl.core.utils import get_object_or_none

logger = logging.getLogger(__name__)


def get_station_channel_records(dispatch_channel, station_id):
    from adl.core.models import (
        StationChannelDispatchStatus,
        ObservationRecord,
        HourlyAggregatedObservationRecord,
        DailyAggregatedObservationRecord
    )
    
    connection = dispatch_channel.network_connection
    send_agg_data = dispatch_channel.send_aggregated_data
    aggregation_period = dispatch_channel.aggregation_period
    
    records_model = ObservationRecord
    
    if send_agg_data and aggregation_period:
        if aggregation_period == "hourly":
            records_model = HourlyAggregatedObservationRecord
        elif aggregation_period == "daily":
            records_model = DailyAggregatedObservationRecord
    
    # get all records for the channel connection and station
    obs_records = records_model.objects.filter(connection_id=connection.id, station_id=station_id)
    
    # filter by last upload time
    station_dispatch_status = get_object_or_none(StationChannelDispatchStatus, station_id=station_id,
                                                 channel_id=dispatch_channel.id)
    
    last_sent_obs_time = None
    if station_dispatch_status and station_dispatch_status.last_sent_obs_time:
        last_sent_obs_time = station_dispatch_status.last_sent_obs_time
    
    if last_sent_obs_time:
        logger.info(f"[DISPATCH] Getting dispatch records for station {station_id} after {last_sent_obs_time}")
        obs_records = obs_records.filter(time__gt=station_dispatch_status.last_sent_obs_time)
    else:
        logger.info(f"[DISPATCH] Getting all dispatch records for station {station_id}")
    
    return obs_records.order_by("time")


def get_dispatch_channel_data(dispatch_channel):
    logger.info(f"[DISPATCH] Getting dispatch data for channel '{dispatch_channel.name}'")
    
    parameter_mappings = dispatch_channel.parameter_mappings.all()
    
    if not parameter_mappings:
        logger.error(
            f"[DISPATCH] No parameter mappings found for dispatch channel {dispatch_channel.name}. Skipping...")
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
    
    for station_link in station_links:
        # get all records for the station and channel
        station_channel_records = get_station_channel_records(dispatch_channel, station_link.station_id)
        
        logger.info(f"[DISPATCH] Found {station_channel_records.count()} records for "
                    f"station {station_link.station_id} and channel '{dispatch_channel.name}'")
        
        for obs in station_channel_records:
            if obs.station_id not in by_station_by_time:
                by_station_by_time[obs.station_id] = {}
            
            if obs.time not in by_station_by_time[obs.station_id]:
                by_station_by_time[obs.station_id][obs.time] = []
            
            if obs.parameter_id in parameter_mappings_ids:
                by_station_by_time[obs.station_id][obs.time].append(obs)
    
    records = []
    for station_id, time_obs_map in by_station_by_time.items():
        for time, obs_list in time_obs_map.items():
            data_values = {}
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
                "timestamp": time,
                "values": data_values
            }
            
            records.append(record)
    
    logger.info(f"[DISPATCH] Found a total of {len(records)} records for dispatch channel '{dispatch_channel.name}'")
    
    return records


def run_dispatch_channel(dispatcher_id):
    from adl.core.models import DispatchChannel
    dispatch_channel = get_object_or_none(DispatchChannel, id=dispatcher_id)
    
    if not dispatch_channel:
        logger.error(f"[DISPATCH] Dispatch channel with id {dispatcher_id} does not exist. Skipping...")
        return
    
    data = get_dispatch_channel_data(dispatch_channel)
    
    dispatch_channel.send_data(data)
