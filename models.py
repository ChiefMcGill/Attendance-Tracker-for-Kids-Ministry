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
    parent_first_name: str
    parent_last_name: str
    parent_phone: str
    parent_email: str
    parent_relationship: str
    family_name: str
    child_first_name: str
    child_last_name: str
    child_birth_year: int
    child_birth_month: int
    child_birth_day: int
    child_medical_notes: Optional[str] = None
    child_special_notes: Optional[str] = None
    program_id: int
    station_id: str = "entrance-a"
    device_id: str = "registration-device"

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
    qr_value: Optional[str] = None

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

# Auth models
class LoginRequest(BaseModel):
    username: str
    password: str
    otp: Optional[str] = None

class LoginResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None
    requires_2fa: bool = False
    role: Optional[str] = None

class DirectCheckinRequest(BaseModel):
    child_id: int
    program_id: int
    station_id: str
    device_id: str

class AddVolunteerRequest(BaseModel):
    username: str
    first_name: str
    last_name: str
    role: str = "volunteer"

class UpdateVolunteerRequest(BaseModel):
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    enabled_2fa: Optional[bool] = None
    active: Optional[bool] = None

class AddProgramRequest(BaseModel):
    name: str
    min_age: Optional[int] = None
    max_age: Optional[int] = None

class UpdateProgramRequest(BaseModel):
    name: Optional[str] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    active: Optional[bool] = None
