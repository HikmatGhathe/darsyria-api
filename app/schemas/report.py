from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

REASON_PATTERN = "^(scam|spam|offensive|inaccurate|other)$"


class ReportCreate(BaseModel):
    reason: str = Field(pattern=REASON_PATTERN)
    details: Optional[str] = Field(default=None, max_length=2000)
    property_id: Optional[UUID] = None
    reported_user_id: Optional[UUID] = None

    @model_validator(mode="after")
    def exactly_one_target(self):
        if (self.property_id is None) == (self.reported_user_id is None):
            raise ValueError("Provide exactly one of property_id or reported_user_id")
        return self


class ReportAdminItem(BaseModel):
    id: UUID
    reason: str
    details: Optional[str] = None
    status: str
    created_at: datetime
    reporter_email: Optional[str] = None
    target_type: str  # "listing" | "seller"
    target_id: UUID
    target_label: Optional[str] = None
    target_owner_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)
