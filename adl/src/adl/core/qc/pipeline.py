import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

from .validators import QCValidator, QCResult, QCContext, QCFlag

logger = logging.getLogger(__name__)


@dataclass
class ValidatorConfig:
    """Configuration for a validator in the pipeline"""
    validator: QCValidator
    weight: float = 1.0
    enabled: bool = True
    fail_fast: bool = False  # Stop pipeline if this validator fails


class QCPipeline:
    """Manages and executes a pipeline of QC validators"""
    
    def __init__(self):
        self.validators: List[ValidatorConfig] = []
    
    def add_validator(self, validator: QCValidator, weight: float = 1.0,
                      enabled: bool = True, fail_fast: bool = False) -> 'QCPipeline':
        """Add a validator to the pipeline"""
        config = ValidatorConfig(
            validator=validator,
            weight=weight,
            enabled=enabled,
            fail_fast=fail_fast
        )
        self.validators.append(config)
        return self  # For method chaining
    
    def remove_validator(self, validator_type: str) -> bool:
        """Remove validator by type"""
        initial_len = len(self.validators)
        self.validators = [
            vc for vc in self.validators
            if vc.validator.validator_type != validator_type
        ]
        return len(self.validators) < initial_len
    
    def get_validator(self, validator_type: str) -> Optional[QCValidator]:
        """Get validator by type"""
        for validator_config in self.validators:
            if validator_config.validator.validator_type == validator_type:
                return validator_config.validator
        return None
    
    def run_single(self, value: float, context: QCContext) -> 'QCPipelineResult':
        """Run QC pipeline on a single value"""
        results = []
        overall_passed = True
        combined_flags = set()
        messages = []
        evidence = {}
        total_weight = 0
        weighted_confidence = 0
        
        for validator_config in self.validators:
            if not validator_config.enabled:
                continue
            
            try:
                result = validator_config.validator.validate(value, context)
                results.append((validator_config, result))
                
                if not result.passed:
                    overall_passed = False
                    combined_flags.update(result.flags)
                    if result.message:
                        messages.append(f"{validator_config.validator.get_display_name()}: {result.message}")
                
                # Update evidence
                if result.evidence:
                    evidence[validator_config.validator.validator_type] = result.evidence
                
                # Calculate weighted confidence
                total_weight += validator_config.weight
                weighted_confidence += result.confidence * validator_config.weight
                
                # Fail fast if configured
                if validator_config.fail_fast and not result.passed:
                    logger.info(f"Fail-fast triggered by {validator_config.validator.validator_type}")
                    break
            
            except Exception as e:
                logger.error(f"Error in validator {validator_config.validator.validator_type}: {e}")
                # You might want to handle this differently - continue, fail, etc.
                messages.append(f"{validator_config.validator.get_display_name()}: Validation error")
        
        # Calculate overall confidence
        final_confidence = weighted_confidence / total_weight if total_weight > 0 else 0.0
        
        return QCPipelineResult(
            passed=overall_passed,
            flags=combined_flags,
            confidence=final_confidence,
            messages=messages,
            evidence=evidence,
            individual_results=results
        )
    
    def run_batch(self, observations: List[Tuple[float, QCContext]]) -> List['QCPipelineResult']:
        """Run QC pipeline on multiple observations"""
        return [self.run_single(value, context) for value, context in observations]
    
    def get_pipeline_summary(self) -> Dict[str, Any]:
        """Get summary information about the pipeline"""
        return {
            'total_validators': len(self.validators),
            'enabled_validators': len([vc for vc in self.validators if vc.enabled]),
            'validator_types': [vc.validator.validator_type for vc in self.validators if vc.enabled],
            'supported_flags': list(set().union(*[
                vc.validator.supported_flags for vc in self.validators if vc.enabled
            ])),
        }


@dataclass
class QCPipelineResult:
    """Result of running the entire QC pipeline"""
    passed: bool
    flags: set
    confidence: float
    messages: List[str]
    evidence: Dict[str, Any]
    individual_results: List[Tuple[ValidatorConfig, QCResult]]
    
    def get_summary_message(self) -> str:
        """Get a human-readable summary of the QC result"""
        if self.passed:
            return "All QC checks passed"
        else:
            return "; ".join(self.messages)
    
    def has_flag(self, flag: QCFlag) -> bool:
        """Check if a specific flag was raised"""
        return flag in self.flags
    
    def get_failed_validators(self) -> List[str]:
        """Get list of validator types that failed"""
        return [
            vc.validator.validator_type
            for vc, result in self.individual_results
            if not result.passed
        ]


class QCPipelineBuilder:
    """Builder pattern for creating QC pipelines"""
    
    def __init__(self):
        self.pipeline = QCPipeline()
    
    def with_range_check(self, min_value: Optional[float] = None,
                         max_value: Optional[float] = None,
                         inclusive: bool = True, **kwargs) -> 'QCPipelineBuilder':
        """Add range validator"""
        from .validators import RangeValidator
        config = {
            'min_value': min_value,
            'max_value': max_value,
            'inclusive_bounds': inclusive
        }
        validator = RangeValidator(config)
        self.pipeline.add_validator(validator, **kwargs)
        return self
    
    def with_step_check(self, max_step_change: float,
                        max_step_per_minute: Optional[float] = None,
                        ignore_after_gap_minutes: int = 30, **kwargs) -> 'QCPipelineBuilder':
        """Add step validator"""
        from .validators import StepValidator
        config = {
            'max_step_change': max_step_change,
            'max_step_change_per_minute': max_step_per_minute,
            'ignore_after_gap_minutes': ignore_after_gap_minutes
        }
        validator = StepValidator(config)
        self.pipeline.add_validator(validator, **kwargs)
        return self
    
    def with_persistence_check(self, max_identical_readings: int = 10,
                               tolerance: float = 0.001,
                               allow_zero_persistence: bool = True, **kwargs) -> 'QCPipelineBuilder':
        """Add persistence validator"""
        from .validators import PersistenceValidator
        config = {
            'max_identical_readings': max_identical_readings,
            'tolerance': tolerance,
            'allow_zero_persistence': allow_zero_persistence
        }
        validator = PersistenceValidator(config)
        self.pipeline.add_validator(validator, **kwargs)
        return self
    
    def with_spike_check(self, threshold_multiplier: float = 3.0,
                         lookback_samples: int = 20,
                         min_samples: int = 5, **kwargs) -> 'QCPipelineBuilder':
        """Add spike validator"""
        from .validators import SpikeValidator
        config = {
            'threshold_multiplier': threshold_multiplier,
            'lookback_samples': lookback_samples,
            'min_samples': min_samples
        }
        validator = SpikeValidator(config)
        self.pipeline.add_validator(validator, **kwargs)
        return self
    
    def with_custom_validator(self, validator: QCValidator, **kwargs) -> 'QCPipelineBuilder':
        """Add custom validator"""
        self.pipeline.add_validator(validator, **kwargs)
        return self
    
    def build(self) -> QCPipeline:
        """Build and return the pipeline"""
        return self.pipeline
