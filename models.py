from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# Request models
class ScanRequest(BaseModel):
    qr_value: str
    station_id: str
    device_id: str

class CheckinRequest(BaseModel):
    session_id: str
    station_id: str
    device_id: str
    created_by: str

class RegisterRequest(BaseModel):
    child: dict
    family: dict
    parent: dict
    qr_value: str
    program_id: int

# Response models
class ScanResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    child_info: Optional[dict] = None
    programs: Optional[List[dict]] = None
    message: str

class CheckinResponse(BaseModel):
    success: bool
    message: str
    child_name: Optional[str] = None

class RegisterResponse(BaseModel):
    success: bool
    message: str
    child_id: Optional[int] = None

# Child info model
class ChildInfo(BaseModel):
    id: int
    first_name: str
    last_name: str
    birth_date: str
    family_name: str
    allergies: Optional[str] = None
    medications: Optional[str] = None
    special_notes: Optional[str] = None
    medical_notes: Optional[str] = None

# Program model
class Program(BaseModel):
    id: int
    name: str
    min_age: Optional[int] = None
    max_age: Optional[int] = None

# Session info model
class SessionInfo(BaseModel):
    session_id: str
    child_info: ChildInfo
    programs: List[Program]
