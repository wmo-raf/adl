from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Any, Optional, List, Set


class QCFlag(Enum):
    RANGE = auto()
    STEP = auto()
    PERSISTENCE = auto()
    SPIKE = auto()
    CLIMATOLOGY = auto()
    CROSS_PARAMETER = auto()


@dataclass
class QCResult:
    """Result of a QC validation check"""
    passed: bool
    flags: Set[QCFlag]
    confidence: float = 1.0  # 0-1, how confident we are in this result
    message: Optional[str] = None
    evidence: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.evidence is None:
            self.evidence = {}


@dataclass
class QCContext:
    """Context data available to QC validators"""
    station_metadata: Dict[str, Any]
    parameter_metadata: Dict[str, Any]
    recent_history: List[Any] = None  # Recent observations for this parameter
    nearby_stations_data: List[Any] = None
    climatology_data: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.recent_history is None:
            self.recent_history = []
        if self.climatology_data is None:
            self.climatology_data = {}


class QCValidator(ABC):
    """Base class for all QC validators"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.validate_config()
    
    @property
    @abstractmethod
    def validator_type(self) -> str:
        """Unique identifier for this validator type"""
        pass
    
    @property
    @abstractmethod
    def supported_flags(self) -> Set[QCFlag]:
        """QC flags this validator can raise"""
        pass
    
    @abstractmethod
    def validate(self, value: float, context: QCContext) -> QCResult:
        """
        Validate a single observation value
        
        Args:
            value: The observation value to validate
            context: Additional context for validation
            
        Returns:
            QCResult indicating pass/fail and details
        """
        pass
    
    def validate_config(self) -> None:
        """Validate the configuration for this validator"""
        schema = self.get_config_schema()
        # Implement validation logic based on schema
        pass
    
    @abstractmethod
    def get_config_schema(self) -> Dict[str, Any]:
        """Return JSON schema describing valid configuration"""
        pass
    
    def get_display_name(self) -> str:
        """Human readable name for this validator"""
        return self.validator_type.replace('_', ' ').title()
    
    @property
    def requires_history(self) -> bool:
        """Whether this validator needs recent observation history"""
        return False
    
    def get_history_requirements(self) -> Dict[str, Any]:
        """
        Get history requirements for this validator.
        
        Returns:
            Dict with keys:
            - 'needed': bool - whether history is needed
            - 'limit': int - number of historical records needed
            - 'min_required': int - minimum records required to run validation
        """
        return {
            'needed': self.requires_history,
            'limit': 20,  # default
            'min_required': 1
        }


class RangeValidator(QCValidator):
    """Validates values are within acceptable range"""
    
    @property
    def validator_type(self) -> str:
        return "range_check"
    
    @property
    def supported_flags(self) -> Set[QCFlag]:
        return {QCFlag.RANGE}
    
    @property
    def requires_history(self) -> bool:
        return False
    
    def get_history_requirements(self) -> Dict[str, Any]:
        return {
            'needed': False,
            'limit': 0,
            'min_required': 0
        }
    
    def validate(self, value: float, context: QCContext) -> QCResult:
        min_val = self.config.get('min_value')
        max_val = self.config.get('max_value')
        inclusive = self.config.get('inclusive_bounds', True)
        
        # Check minimum
        if min_val is not None:
            failed = value < min_val if inclusive else value <= min_val
            if failed:
                op = ">=" if inclusive else ">"
                return QCResult(
                    passed=False,
                    flags={QCFlag.RANGE},
                    message=f"Value {value} below minimum: must be {op} {min_val}",
                    evidence={"min_value": min_val, "operator": op}
                )
        
        # Check maximum
        if max_val is not None:
            failed = value > max_val if inclusive else value >= max_val
            if failed:
                op = "<=" if inclusive else "<"
                return QCResult(
                    passed=False,
                    flags={QCFlag.RANGE},
                    message=f"Value {value} above maximum: must be {op} {max_val}",
                    evidence={"max_value": max_val, "operator": op}
                )
        
        return QCResult(passed=True, flags=set())
    
    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "min_value": {"type": ["number", "null"]},
                "max_value": {"type": ["number", "null"]},
                "inclusive_bounds": {"type": "boolean", "default": True}
            },
            "additionalProperties": False
        }


class StepValidator(QCValidator):
    """Validates changes between consecutive readings"""
    
    @property
    def validator_type(self) -> str:
        return "step_check"
    
    @property
    def supported_flags(self) -> Set[QCFlag]:
        return {QCFlag.STEP}
    
    @property
    def requires_history(self) -> bool:
        return True
    
    def get_history_requirements(self) -> Dict[str, Any]:
        return {
            'needed': True,
            'limit': 1,  # Only need the most recent observation
            'min_required': 1
        }
    
    def validate(self, value: float, context: QCContext) -> QCResult:
        max_step = self.config.get('max_step_change')
        max_step_per_minute = self.config.get('max_step_change_per_minute')
        ignore_after_gap = self.config.get('ignore_after_gap_minutes', 30)
        
        if not context.recent_history:
            return QCResult(passed=True, flags=set())
        
        # Get the most recent previous value
        previous_obs = context.recent_history[-1]
        previous_value = previous_obs.get('value')
        previous_time = previous_obs.get('time')
        current_time = context.parameter_metadata.get('observation_time')
        
        if previous_value is None or not current_time or not previous_time:
            return QCResult(passed=True, flags=set())
        
        time_diff_minutes = (current_time - previous_time).total_seconds() / 60
        
        # Ignore check if gap is too large
        if time_diff_minutes > ignore_after_gap:
            return QCResult(passed=True, flags=set())
        
        step_change = abs(value - previous_value)
        
        # Check absolute step change
        if max_step is not None and step_change > max_step:
            return QCResult(
                passed=False,
                flags={QCFlag.STEP},
                message=f"Step change {step_change:.2f} exceeds maximum {max_step}",
                evidence={"step_change": step_change, "max_allowed": max_step}
            )
        
        # Check rate-based step change
        if max_step_per_minute is not None and time_diff_minutes > 0:
            rate = step_change / time_diff_minutes
            if rate > max_step_per_minute:
                return QCResult(
                    passed=False,
                    flags={QCFlag.STEP},
                    message=f"Rate of change {rate:.2f}/min exceeds maximum {max_step_per_minute}/min",
                    evidence={"rate": rate, "max_rate": max_step_per_minute}
                )
        
        return QCResult(passed=True, flags=set())
    
    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_step_change": {"type": "number", "minimum": 0},
                "max_step_change_per_minute": {"type": ["number", "null"], "minimum": 0},
                "ignore_after_gap_minutes": {"type": "integer", "minimum": 1, "default": 30}
            },
            "required": ["max_step_change"],
            "additionalProperties": False
        }


class PersistenceValidator(QCValidator):
    """Validates against stuck sensors reporting identical values"""
    
    @property
    def validator_type(self) -> str:
        return "persistence_check"
    
    @property
    def supported_flags(self) -> Set[QCFlag]:
        return {QCFlag.PERSISTENCE}
    
    @property
    def requires_history(self) -> bool:
        return True
    
    def get_history_requirements(self) -> Dict[str, Any]:
        max_identical = self.config.get('max_identical_readings', 10)
        return {
            'needed': True,
            'limit': max_identical,  # Need enough to check persistence
            'min_required': 1
        }
    
    def validate(self, value: float, context: QCContext) -> QCResult:
        max_identical = self.config.get('max_identical_readings', 10)
        tolerance = self.config.get('tolerance', 0.001)
        allow_zero = self.config.get('allow_zero_persistence', True)
        
        if not context.recent_history or len(context.recent_history) < max_identical - 1:
            return QCResult(passed=True, flags=set())
        
        # Check if current value is identical to recent values
        identical_count = 1  # Count current value
        
        for obs in context.recent_history[:max_identical - 1]:
            prev_value = obs.get('value')
            if prev_value is None:
                break
            
            # Check if values are identical within tolerance
            if abs(value - prev_value) <= tolerance:
                identical_count += 1
            else:
                break
        
        # Special handling for zero values if allowed
        if allow_zero and abs(value) <= tolerance:
            return QCResult(passed=True, flags=set())
        
        if identical_count >= max_identical:
            return QCResult(
                passed=False,
                flags={QCFlag.PERSISTENCE},
                message=f"Value {value} repeated {identical_count} times (max {max_identical})",
                evidence={"identical_count": identical_count, "max_allowed": max_identical}
            )
        
        return QCResult(passed=True, flags=set())
    
    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_identical_readings": {"type": "integer", "minimum": 2, "default": 10},
                "tolerance": {"type": "number", "minimum": 0, "default": 0.001},
                "allow_zero_persistence": {"type": "boolean", "default": True}
            },
            "required": ["max_identical_readings"],
            "additionalProperties": False
        }


class SpikeValidator(QCValidator):
    """Statistical spike detection using standard deviation"""
    
    @property
    def validator_type(self) -> str:
        return "spike_check"
    
    @property
    def supported_flags(self) -> Set[QCFlag]:
        return {QCFlag.SPIKE}
    
    @property
    def requires_history(self) -> bool:
        return True
    
    def get_history_requirements(self) -> Dict[str, Any]:
        lookback_samples = self.config.get('lookback_samples', 20)
        min_samples = self.config.get('min_samples', 5)
        return {
            'needed': True,
            'limit': lookback_samples,
            'min_required': min_samples
        }
    
    def validate(self, value: float, context: QCContext) -> QCResult:
        threshold_multiplier = self.config.get('threshold_multiplier', 3.0)
        lookback_samples = self.config.get('lookback_samples', 20)
        min_samples = self.config.get('min_samples', 5)
        
        if not context.recent_history or len(context.recent_history) < min_samples:
            return QCResult(passed=True, flags=set())
        
        # Get values for statistical analysis
        values = []
        for obs in context.recent_history[:lookback_samples]:
            prev_value = obs.get('value')
            if prev_value is not None:
                values.append(prev_value)
        
        if len(values) < min_samples:
            return QCResult(passed=True, flags=set())
        
        # Calculate statistics
        import statistics
        try:
            mean = statistics.mean(values)
            if len(values) > 1:
                stdev = statistics.stdev(values)
            else:
                return QCResult(passed=True, flags=set())
            
            # Check if current value is a spike
            if stdev > 0:
                z_score = abs(value - mean) / stdev
                if z_score > threshold_multiplier:
                    return QCResult(
                        passed=False,
                        flags={QCFlag.SPIKE},
                        message=f"Value {value} is {z_score:.2f} standard deviations from mean {mean:.2f} (threshold: {threshold_multiplier})",
                        evidence={
                            "z_score": z_score,
                            "mean": mean,
                            "stdev": stdev,
                            "threshold": threshold_multiplier,
                            "sample_size": len(values)
                        }
                    )
        
        except statistics.StatisticsError as e:
            # Not enough data or all values identical
            return QCResult(passed=True, flags=set())
        
        return QCResult(passed=True, flags=set())
    
    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "threshold_multiplier": {"type": "number", "minimum": 0.1, "default": 3.0},
                "lookback_samples": {"type": "integer", "minimum": 5, "default": 20},
                "min_samples": {"type": "integer", "minimum": 3, "default": 5}
            },
            "required": ["threshold_multiplier"],
            "additionalProperties": False
        }
