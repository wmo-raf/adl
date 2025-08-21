from datetime import datetime
from typing import Dict, Optional, Union

from pydantic import BaseModel, Field


class StationRecordModel(BaseModel):
    observation_time: datetime = Field(..., description="Timestamp of observation")
    values: Dict[str, Optional[Union[str, int, float]]] = Field(default_factory=dict)
