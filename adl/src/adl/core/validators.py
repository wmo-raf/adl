from datetime import datetime
from typing import Dict, Optional, Union
from pydantic import BaseModel, Field, field_validator


class StationRecordModel(BaseModel):
    observation_time: datetime = Field(..., description="Timestamp of observation")
    values: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator("values", mode="before")
    def stringify_keys(cls, v):
        if isinstance(v, dict):
            # Ensure all keys are strings
            return {str(k): val for k, val in v.items()}
        return v
