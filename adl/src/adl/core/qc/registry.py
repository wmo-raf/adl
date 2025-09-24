import logging
from typing import Dict, Type, Any

from adl.core.registry import Registry, Instance
from .validators import QCValidator

logger = logging.getLogger(__name__)


class QCValidatorRegistry(Registry):
    """Registry for QC validators"""
    name = "qc_validator"
    
    def create_validator(self, validator_type: str, config: Dict[str, Any] = None) -> QCValidator:
        """Create a validator instance by type"""
        validator_class = self.get(validator_type)
        return validator_class(config or {})
    
    def get_validator_config_schema(self, validator_type: str) -> Dict[str, Any]:
        """Get configuration schema for a validator type"""
        validator_class = self.get(validator_type)
        # Create temporary instance to get schema
        temp_instance = validator_class()
        return temp_instance.get_config_schema()
    
    def get_all_schemas(self) -> Dict[str, Dict[str, Any]]:
        """Get configuration schemas for all registered validators"""
        schemas = {}
        for validator_type in self.get_types():
            try:
                schemas[validator_type] = self.get_validator_config_schema(validator_type)
            except Exception as e:
                logger.error(f"Error getting schema for {validator_type}: {e}")
        return schemas


# Global registry instance
qc_validator_registry = QCValidatorRegistry()


# Validator wrapper for registration
class QCValidatorType(Instance):
    """Wrapper to make QC validators registrable"""
    
    def __init__(self, validator_class: Type[QCValidator]):
        self.validator_class = validator_class
        # Create temporary instance to get type
        temp_instance = validator_class()
        self.type = temp_instance.validator_type
        super().__init__()
    
    def __call__(self, config: Dict[str, Any] = None) -> QCValidator:
        """Make the type callable to create instances"""
        return self.validator_class(config or {})
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Get configuration schema"""
        temp_instance = self.validator_class()
        return temp_instance.get_config_schema()


def register_qc_validator(validator_class: Type[QCValidator]):
    """Decorator to register QC validators"""
    validator_type = QCValidatorType(validator_class)
    qc_validator_registry.register(validator_type)
    return validator_class


# Register built-in validators
from .validators import RangeValidator, StepValidator, PersistenceValidator, SpikeValidator

register_qc_validator(RangeValidator)
register_qc_validator(StepValidator)
register_qc_validator(PersistenceValidator)
register_qc_validator(SpikeValidator)
