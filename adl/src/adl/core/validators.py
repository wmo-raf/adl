from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class StationRecordModel(BaseModel):
    observation_time: datetime = Field(..., description="Timestamp of observation")
    values: Dict[str, Optional[float]] = Field(default_factory=dict)
