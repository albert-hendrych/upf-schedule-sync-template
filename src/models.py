from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ClassSession(BaseModel):
    subject_name: str
    start_time: datetime
    end_time: datetime
    classroom: str = Field(default="Sense aula")
    group_id: Optional[str] = None
    raw_id: Optional[str] = None
    session_type: Optional[str] = None
    teachers: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class CalendarEvent(BaseModel):
    event_id: str
    summary: str
    start_time: datetime
    end_time: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    upf_session_id: Optional[str] = None
    color_id: Optional[str] = None


class DiffType(str, Enum):
    ROOM_CHANGE = "ROOM_CHANGE"
    CANCELLED = "CANCELLED"
    NEW_SESSION = "NEW_SESSION"
    TIME_CHANGE = "TIME_CHANGE"
    RESTORED = "RESTORED"
    UNCHANGED = "UNCHANGED"


class DiffResult(BaseModel):
    diff_type: DiffType
    subject_name: str
    web_session: Optional[ClassSession] = None
    calendar_event: Optional[CalendarEvent] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    message: str
