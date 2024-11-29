import logging

from adl.core.utils import get_object_or_none

logger = logging.getLogger(__name__)


def get_dispatch_channel_data(dispatch_channel):
    from adl.core.models import ObservationRecord
    parameter_mappings = dispatch_channel.parameter_mappings.all()
    
    if not parameter_mappings:
        logger.error(f"No parameter mappings found for dispatch channel {dispatch_channel.name}. Skipping...")
        return
    
    parameter_mappings_ids = parameter_mappings.values_list("parameter_id", flat=True)
    
    parameter_channel_mapping = {pm.parameter_id: pm.channel_parameter for pm in parameter_mappings}
    
    connection = dispatch_channel.network_connection
    last_upload_obs_time = dispatch_channel.last_upload_obs_time
    
    obs_records = ObservationRecord.objects.filter(connection_id=connection.id)
    
    logger.info(f"Found {obs_records.count()} records for network connection {connection}")
    
    if last_upload_obs_time:
        obs_records = obs_records.filter(time__gt=last_upload_obs_time)
    
    # group by station and by time
    by_station_by_time = {}
    for obs in obs_records:
        if obs.station_id not in by_station_by_time:
            by_station_by_time[obs.station_id] = {}
        
        if obs.time not in by_station_by_time[obs.station_id]:
            by_station_by_time[obs.station_id][obs.time] = []
        
        if obs.parameter_id in parameter_mappings_ids:
            by_station_by_time[obs.station_id][obs.time].append(obs)
    
    records = []
    for station_id, time_obs_map in by_station_by_time.items():
        for time, obs_list in time_obs_map.items():
            record = {
                "station_id": station_id,
                "timestamp": time,
                "values": {parameter_channel_mapping[obs.parameter_id]: obs.value for obs in obs_list}
            }
            
            records.append(record)
    
    return records


def run_dispatch_channel(dispatcher_id):
    from adl.core.models import DispatchChannel
    dispatch_channel = get_object_or_none(DispatchChannel, id=dispatcher_id)
    
    if not dispatch_channel:
        logger.error(f"Dispatch channel with id {dispatcher_id} does not exist. Skipping...")
        return
    
    data = get_dispatch_channel_data(dispatch_channel)
    
    print(data)
