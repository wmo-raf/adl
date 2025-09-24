import logging
from typing import Dict, Any

from .pipeline import QCPipeline, QCPipelineBuilder
from .registry import qc_validator_registry

logger = logging.getLogger(__name__)


class QCConfigConverter:
    """Convert StreamField QC configurations to QC pipeline"""
    
    @staticmethod
    def streamfield_to_pipeline(qc_checks) -> QCPipeline:
        """Convert StreamField qc_checks to QCPipeline"""
        builder = QCPipelineBuilder()
        
        for qc_check in qc_checks:
            check_type = qc_check.block_type
            check_value = qc_check.value
            
            try:
                if check_type == "range_check":
                    builder.with_range_check(
                        min_value=check_value.get('min_value'),
                        max_value=check_value.get('max_value'),
                        inclusive=check_value.get('inclusive_bounds', True)
                    )
                elif check_type == "step_check":
                    builder.with_step_check(
                        max_step_change=check_value.get('max_step_change'),
                        max_step_per_minute=check_value.get('max_step_change_per_minute'),
                        ignore_after_gap_minutes=check_value.get('ignore_after_gap_minutes', 30)
                    )
                elif check_type == "persistence_check":
                    builder.with_persistence_check(
                        max_identical_readings=check_value.get('max_identical_readings', 10),
                        tolerance=check_value.get('tolerance', 0.001),
                        allow_zero_persistence=check_value.get('allow_zero_persistence', True)
                    )
                elif check_type == "spike_check":
                    builder.with_spike_check(
                        threshold_multiplier=check_value.get('threshold_multiplier', 3.0),
                        lookback_samples=check_value.get('lookback_samples', 20),
                        min_samples=check_value.get('min_samples', 5)
                    )
                else:
                    logger.warning(f"Unknown QC check type: {check_type}")
            
            except Exception as e:
                logger.error(f"Error adding {check_type} validator: {e}")
                continue
        
        return builder.build()
    
    @staticmethod
    def pipeline_to_config_dict(pipeline: QCPipeline) -> Dict[str, Any]:
        """Convert QCPipeline back to configuration dictionary"""
        config = {}
        
        for validator_config in pipeline.validators:
            validator = validator_config.validator
            validator_type = validator.validator_type
            
            config[validator_type] = {
                'config': validator.config,
                'weight': validator_config.weight,
                'enabled': validator_config.enabled,
                'fail_fast': validator_config.fail_fast
            }
        
        return config
    
    @staticmethod
    def config_dict_to_pipeline(config_dict: Dict[str, Any]) -> QCPipeline:
        """Create QCPipeline from configuration dictionary"""
        pipeline = QCPipeline()
        
        for validator_type, validator_config in config_dict.items():
            try:
                validator = qc_validator_registry.create_validator(
                    validator_type,
                    validator_config.get('config', {})
                )
                
                pipeline.add_validator(
                    validator,
                    weight=validator_config.get('weight', 1.0),
                    enabled=validator_config.get('enabled', True),
                    fail_fast=validator_config.get('fail_fast', False)
                )
            
            except Exception as e:
                logger.error(f"Error creating validator {validator_type}: {e}")
                continue
        
        return pipeline


def build_qc_context(observation_record, parameter, station_link, recent_history=None) -> 'QCContext':
    """Build QC context from Django models"""
    from .validators import QCContext
    
    station = station_link.station
    
    station_metadata = {
        'station_id': station.station_id,
        'wigos_id': station.wigos_id,
        'location': {
            'latitude': station.location.y,
            'longitude': station.location.x
        },
        'elevation': station.station_height_above_msl,
        'station_type': station.station_type,
    }
    
    parameter_metadata = {
        'parameter_name': parameter.name,
        'unit': parameter.unit.symbol,
        'category': parameter.category,
        'observation_time': getattr(observation_record, 'time', None) or observation_record.get('observation_time')
    }
    
    # Convert recent history to simple format
    history_data = []
    if recent_history:
        for obs in recent_history:
            if hasattr(obs, 'value'):  # Django model
                history_data.append({
                    'value': obs.value,
                    'time': obs.time,
                    'qc_status': obs.qc_status
                })
            else:  # Dictionary
                history_data.append(obs)
    
    return QCContext(
        station_metadata=station_metadata,
        parameter_metadata=parameter_metadata,
        recent_history=history_data
    )
