import logging
from datetime import timedelta

from dateutil.parser import parse as parse_date
from django.db.models import Min, Max, Avg, Sum, Count
from django.utils import timezone as dj_timezone

from .models import (
    ObservationRecord,
    HourlyAggregatedObservationRecord,
    DailyAggregatedObservationRecord,
    NetworkConnection
)
from .utils import get_object_or_none

logger = logging.getLogger(__name__)


def aggregate_hourly_network_connection(network_connection_id):
    logger.info("[HOURLY_AGGREGATE] Starting hourly aggregation...")
    
    network_connection = get_object_or_none(NetworkConnection, id=network_connection_id)
    
    if network_connection is None:
        logger.error(f"[HOURLY_AGGREGATE] Network connection with id {network_connection_id} not found")
        return
    
    for station_link in network_connection.station_links.all():
        logger.debug(f"[HOURLY_AGGREGATE] Aggregating hourly data for station link: {station_link}")
        
        station = station_link.station
        
        from_date = None
        
        if station_link.aggregate_from_date:
            from_date = station_link.aggregate_from_date
        
        if from_date is None:
            # get the last aggregated record
            last_aggregated_record = HourlyAggregatedObservationRecord.objects.filter(station_id=station.id,
                                                                                      connection_id=network_connection.id).last()
            if last_aggregated_record:
                from_date = last_aggregated_record.time
            else:
                try:
                    earliest_record = ObservationRecord.objects.earliest("time")
                    from_date = earliest_record.time
                except ObservationRecord.DoesNotExist:
                    # no records to aggregate
                    logger.warning("[AGGREGATE] No observation records to aggregate")
                    return
        
        # use the current time as the end date
        to_date = dj_timezone.localtime()
        
        # reset to beginning of the hour
        from_date = from_date.replace(minute=0, second=0)
        to_date = to_date.replace(minute=0, second=0)
        
        # minus one hour  from the to_date, to make sure we don't include the current hour
        # since we are not sure that all the data for this current has been collected
        to_date = to_date - timedelta(hours=1)
        
        current_time = from_date
        
        aggregation_records_count = 0
        
        logger.info(f"[HOURLY_AGGREGATE] Starting hourly aggregation from {from_date} to {to_date}")
        
        while current_time < to_date:
            next_time = current_time + timedelta(hours=1)
            
            logger.debug(f"[HOURLY_AGGREGATE] Hourly aggregating data from {current_time} to {next_time}")
            
            # Perform aggregation for the current hour
            aggregations = (
                ObservationRecord.objects.filter(
                    station_id=station.id,
                    connection_id=network_connection.id,
                    time__gte=current_time,
                    time__lt=next_time,
                    is_daily=False, )
                .values("parameter_id", "station_id", "connection_id")  # group by parameter, station and connection
                .annotate(
                    min_value=Min("value"),
                    max_value=Max("value"),
                    avg_value=Avg("value"),
                    sum_value=Sum("value"),
                    records_count=Count("value"),
                )
            )
            
            for aggregation in aggregations:
                aggregation_time = current_time
                aggregation["time"] = aggregation_time
                
                logger.debug(f"[HOURLY_AGGREGATE] Saving hourly aggregation record for hour: {aggregation['time']}, "
                             f"station: {aggregation['station_id']}, " f"parameter: {aggregation['parameter_id']}, "
                             f"connection: {aggregation['connection_id']}")
                
                HourlyAggregatedObservationRecord.objects.update_or_create(**aggregation)
            
            aggregation_records_count += len(aggregations)
            
            # move to the next hour
            current_time = next_time
        
        logger.info(f"[HOURLY_AGGREGATE] Aggregated {aggregation_records_count} hourly records")


def aggregate_daily(from_date=None):
    logger.info("[DAILY_AGGREGATE] Starting daily aggregation...")
    
    if from_date:
        from_date = parse_date(from_date)
        
        if from_date and dj_timezone.is_naive(from_date):
            from_date = dj_timezone.make_aware(from_date)
    
    if from_date is None:
        # get the last aggregated record
        last_aggregated_record = DailyAggregatedObservationRecord.objects.last()
        
        if last_aggregated_record:
            from_date = last_aggregated_record.time
        else:
            earliest_record = ObservationRecord.objects.earliest("time")
            
            if earliest_record:
                from_date = earliest_record.time
            else:
                # no records to aggregate
                logger.warning("[DAILY_AGGREGATE] No observation records to aggregate")
                return
    
    to_date = dj_timezone.localtime()
    
    # reset to beginning of the day
    from_date = from_date.replace(hour=0, minute=0, second=0)
    to_date = to_date.replace(hour=0, minute=0, second=0)
    
    # minus one day from the to_date, to make sure we don't include the current day
    # since we are not sure that all the data for this current day has been collected
    to_date = to_date - timedelta(days=1)
    
    current_time = from_date
    aggregation_records_count = 0
    
    logger.info(f"[DAILY_AGGREGATE] Starting daily aggregation from {from_date} to {to_date}")
    
    while current_time < to_date:
        next_time = current_time + timedelta(days=1)
        
        logger.debug(f"[DAILY_AGGREGATE] Aggregating data from {current_time} to {next_time}")
        
        # Perform aggregation for the current day
        aggregations = (
            ObservationRecord.objects.filter(time__gte=current_time, time__lt=next_time)
            .values("parameter_id", "station_id", "connection_id")  # group by parameter, station and connection
            .annotate(
                min_value=Min("value"),
                max_value=Max("value"),
                avg_value=Avg("value"),
                sum_value=Sum("value"),
                records_count=Count("value"),
            )
        )
        
        if not aggregations:
            # no data to aggregate
            logger.debug(f"[DAILY_AGGREGATE] No data to aggregate for day: {current_time}")
        else:
            for aggregation in aggregations:
                aggregation_time = current_time
                aggregation["time"] = aggregation_time
                
                logger.debug(f"[DAILY_AGGREGATE] Saving daily aggregation record for day: {aggregation['time']}, "
                             f"station: {aggregation['station_id']}, " f"parameter: {aggregation['parameter_id']}, "
                             f"connection: {aggregation['connection_id']}")
                
                DailyAggregatedObservationRecord.objects.update_or_create(**aggregation)
            
            aggregation_records_count += len(aggregations)
        
        # move to the next day
        current_time = next_time
    
    logger.info(f"[DAILY_AGGREGATE] Aggregated {aggregation_records_count} daily records")
