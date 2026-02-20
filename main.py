import os
import uuid
import secrets
import re
import base64
from jose import jwt
import pyotp
from database import verify_password, get_password_hash
from database import init_database
from database import get_db
from database import AsyncSessionLocal
from database import Database
from sqlalchemy import text
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response
from fastapi.responses import StreamingResponse
from starlette.responses import Response
import csv
import io
from models import (
    ScanRequest, ScanResponse, CheckinRequest, CheckinResponse,
    RegisterRequest, RegisterResponse, ChildInfo, Program, SessionInfo,
    LoginRequest, LoginResponse, DirectCheckinRequest,
    AddVolunteerRequest, UpdateVolunteerRequest, AddProgramRequest, UpdateProgramRequest,
    Setup2FARequest, ProfileUpdateRequest, ChangePasswordRequest
)
from passlib.context import CryptContext
from jose import JWTError, jwt
from pydantic import BaseModel
from datetime import datetime, timedelta
import pyotp
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import qrcode
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# Initialize FastAPI app
app = FastAPI(
    title="Kids Ministry Check-in System",
    description="QR code-based check-in system for children's ministry",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
security = HTTPBearer()

# Session middleware with proper HTTPS settings
app.add_middleware(SessionMiddleware, 
    secret_key=SECRET_KEY,
    session_cookie="session",
    max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
    same_site="lax",  # Changed from "none" for HTTPS compatibility
    https_only=True,
    path="/"
)

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Station tokens from environment
STATION_TOKENS = os.getenv("STATION_TOKENS", "entrance-a,entrance-b,checkout-a").split(",")

def validate_station(station_id: str) -> bool:
    """Validate station ID"""
    return station_id in STATION_TOKENS

def validate_password(password: str) -> bool:
    if len(password) < 8:
        return False
    if not re.search(r'[A-Z]', password):
        return False
    if not re.search(r'[a-z]', password):
        return False
    if not re.search(r'\d', password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True

# Auth utilities

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request):
    try:
        token = request.session.get('token')
        if not token:
            authorization = request.headers.get("Authorization")
            if authorization and authorization.startswith("Bearer "):
                token = authorization[7:]
        
        if not token:
            print("No authentication token found")
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = str(payload.get("sub"))
            if username is None:
                print("No username in token payload")
                raise HTTPException(status_code=401, detail="Not authenticated")
        except JWTError as jwt_error:
            print(f"JWT decode error: {jwt_error}")
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        try:
            user = await Database.get_user_by_username(username)
            if user is None:
                print(f"User not found: {username}")
                raise HTTPException(status_code=401, detail="Not authenticated")
        except Exception as db_error:
            print(f"Database error getting user {username}: {db_error}")
            raise HTTPException(status_code=500, detail="Authentication service unavailable")
        
        return user
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in get_current_user: {e}")
        raise HTTPException(status_code=500, detail="Authentication error")

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    from database import init_database
    await init_database()
    await Database.log_event("info", "api", "Application started")

@app.get("/")
async def root(request: Request):
    """Root endpoint - redirect to scanner"""
    return templates.TemplateResponse("scanner.html", {"request": request})

@app.get("/health")
async def health_check():
    from datetime import datetime
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/api/login")
async def login(request: Request, login_data: LoginRequest):
    try:
        print(f"Login attempt for username: {login_data.username}")
        
        # Get user
        try:
            user = await Database.get_user_by_username(login_data.username)
            if not user:
                print(f"User not found: {login_data.username}")
                await Database.log_event("warning", "auth", f"Failed login attempt - user not found", 
                                       details=f"Username: {login_data.username}")
                return {"success": False, "message": "Invalid username or password"}
        except Exception as db_error:
            print(f"Database error getting user {login_data.username}: {db_error}")
            await Database.log_event("error", "auth", f"Database error during login for {login_data.username}: {str(db_error)}")
            raise HTTPException(status_code=500, detail="Authentication service unavailable")
        
        # Verify password
        try:
            if not verify_password(login_data.password, user['password_hash']):
                print(f"Invalid password for user: {login_data.username}")
                await Database.log_event("warning", "auth", f"Failed login attempt - invalid password", 
                                       details=f"Username: {login_data.username}")
                return {"success": False, "message": "Invalid username or password"}
        except Exception as pwd_error:
            print(f"Password verification error for {login_data.username}: {pwd_error}")
            await Database.log_event("error", "auth", f"Password verification error for {login_data.username}: {str(pwd_error)}")
            raise HTTPException(status_code=500, detail="Authentication error")
        
        # Check 2FA
        if user.get('enabled_2fa'):
            if not login_data.otp:
                print(f"2FA required but not provided for user: {login_data.username}")
                await Database.log_event("info", "auth", f"2FA code required for login", 
                                       details=f"Username: {login_data.username}")
                return {"success": False, "message": "2FA code required", "requires_2fa": True}
            
            try:
                totp = pyotp.TOTP(user['totp_secret'])
                if not totp.verify(login_data.otp):
                    print(f"Invalid 2FA code for user: {login_data.username}")
                    await Database.log_event("warning", "auth", f"Invalid 2FA code provided", 
                                           details=f"Username: {login_data.username}")
                    return {"success": False, "message": "Invalid 2FA code"}
            except Exception as fa_error:
                print(f"2FA verification error for {login_data.username}: {fa_error}")
                await Database.log_event("error", "auth", f"2FA verification error for {login_data.username}: {str(fa_error)}")
                raise HTTPException(status_code=500, detail="2FA verification failed")
        else:
            # Not enabled, setup required
            try:
                totp_secret = pyotp.random_base32()
                await Database.update_volunteer_2fa(user['id'], totp_secret, False)
                print(f"2FA setup initiated for user: {login_data.username}")
                await Database.log_event("info", "auth", f"2FA setup initiated for {login_data.username}")
                return {"success": False, "setup_2fa": True, "totp_secret": totp_secret, "message": "2FA setup required"}
            except Exception as setup_error:
                print(f"2FA setup error for {login_data.username}: {setup_error}")
                await Database.log_event("error", "auth", f"2FA setup error for {login_data.username}: {str(setup_error)}")
                raise HTTPException(status_code=500, detail="Failed to initiate 2FA setup")
        
        # Create token
        try:
            access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            access_token = create_access_token(
                data={"sub": user['username']}, expires_delta=access_token_expires
            )
            request.session['token'] = access_token
            print(f"Login successful for user: {login_data.username}")
            await Database.log_event("info", "auth", f"User logged in successfully", 
                                   details=f"Username: {login_data.username}, Role: {user['role']}")
            return {"success": True, "message": "Login successful", "token": access_token, "role": user['role']}
        except Exception as token_error:
            print(f"Token creation error for {login_data.username}: {token_error}")
            await Database.log_event("error", "auth", f"Token creation error for {login_data.username}: {str(token_error)}")
            raise HTTPException(status_code=500, detail="Login token creation failed")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in login for {login_data.username}: {e}")
        await Database.log_event("error", "auth", f"Unexpected login error for {login_data.username}: {str(e)}")
        raise HTTPException(status_code=500, detail="Login failed")

@app.get("/api/search-children")
async def search_children(query: str, current_user: dict = Depends(get_current_user)):
    """Search children by name - requires auth"""
    try:
        print(f"Search children request: query='{query}', user={current_user['username']}")
        
        if not query or len(query) < 2:
            print("Search query too short or empty")
            return []
        
        try:
            results = await Database.search_children(query)
            print(f"Search returned {len(results)} results")
            await Database.log_event("info", "api", f"Children search performed", 
                                   details=f"Query: '{query}', Results: {len(results)}, User: {current_user['username']}")
            return results
        except Exception as db_error:
            print(f"Database error in search_children: {db_error}")
            await Database.log_event("error", "api", f"Database error in search_children: {str(db_error)}", 
                                   details=f"Query: '{query}', User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Search failed")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in search_children: {e}")
        await Database.log_event("error", "api", f"Unexpected error in search_children: {str(e)}", 
                               details=f"Query: '{query}', User: {current_user['username']}")
        raise HTTPException(status_code=500, detail="Search service unavailable")

@app.get("/api/programs")
async def get_programs_api():
    """Get all programs"""
    try:
        print("Getting programs list")
        try:
            programs = await Database.get_programs()
            print(f"Retrieved {len(programs)} programs")
            await Database.log_event("info", "api", f"Programs list retrieved", 
                                   details=f"Count: {len(programs)}")
            return programs
        except Exception as db_error:
            print(f"Database error in get_programs_api: {db_error}")
            await Database.log_event("error", "api", f"Database error in get_programs_api: {str(db_error)}")
            raise HTTPException(status_code=500, detail="Failed to retrieve programs")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in get_programs_api: {e}")
        await Database.log_event("error", "api", f"Unexpected error in get_programs_api: {str(e)}")
        raise HTTPException(status_code=500, detail="Programs service unavailable")

@app.post("/api/scan", response_model=ScanResponse)
async def scan_qr_code(request: ScanRequest):
    """
    Scan QR code and create check-in session
    
    This endpoint is called when a QR code is scanned at a station.
    It validates the QR code, retrieves child information, and creates a temporary session.
    """
    try:
        print(f"QR scan request: station={request.station_id}, device={request.device_id}, qr={request.qr_value[:20]}...")
        
        # Validate station
        if not validate_station(request.station_id):
            print(f"Invalid station ID: {request.station_id}")
            await Database.log_event("warning", "api", f"Invalid station ID: {request.station_id}", 
                                   details=f"Device: {request.device_id}")
            return ScanResponse(
                success=False,
                message="Invalid station ID"
            )
        
        # Look up child by QR code
        try:
            child_info = await Database.get_child_by_qr(request.qr_value)
            if not child_info:
                print(f"QR code not found: {request.qr_value[:20]}...")
                await Database.log_event("warning", "api", "QR code not found", 
                                       details=f"QR: {request.qr_value[:10]}..., Station: {request.station_id}")
                return ScanResponse(
                    success=False,
                    message="QR code not found. Please register this child."
                )
        except Exception as lookup_error:
            print(f"Error looking up QR code: {lookup_error}")
            await Database.log_event("error", "api", f"QR lookup error: {str(lookup_error)}", 
                                   details=f"QR: {request.qr_value[:10]}..., Station: {request.station_id}")
            raise HTTPException(status_code=500, detail="QR lookup failed")
        
        # Generate session ID
        session_id = secrets.token_urlsafe(16)
        print(f"Generated session ID: {session_id}")
        
        # Get available programs
        try:
            programs = await Database.get_programs()
            print(f"Retrieved {len(programs)} programs for session")
        except Exception as programs_error:
            print(f"Error getting programs: {programs_error}")
            await Database.log_event("error", "api", f"Failed to get programs for scan: {str(programs_error)}", 
                                   details=f"Station: {request.station_id}")
            raise HTTPException(status_code=500, detail="Failed to load programs")
        
        # Create check-in session
        try:
            await Database.create_checkin_session(
                session_id=session_id,
                child_id=child_info["id"],
                program_id=1,  # Default to first program, will be updated
                station_id=request.station_id,
                device_id=request.device_id
            )
            print(f"Check-in session created successfully")
        except Exception as session_error:
            print(f"Error creating check-in session: {session_error}")
            await Database.log_event("error", "api", f"Failed to create check-in session: {str(session_error)}", 
                                   details=f"Child: {child_info['first_name']} {child_info['last_name']}, Station: {request.station_id}")
            raise HTTPException(status_code=500, detail="Failed to create check-in session")
        
        await Database.log_event("info", "api", "QR code scanned successfully", 
                               details=f"Child: {child_info['first_name']} {child_info['last_name']}, Session: {session_id}")
        
        return ScanResponse(
            success=True,
            session_id=session_id,
            child_info=child_info,
            programs=programs,
            message=f"Found {child_info['first_name']} {child_info['last_name']}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in scan_qr_code: {e}")
        await Database.log_event("error", "api", f"Unexpected error scanning QR code: {str(e)}", 
                               details=f"QR: {request.qr_value[:10]}..., Station: {request.station_id}")
        raise HTTPException(status_code=500, detail="Scan failed")

@app.post("/api/checkin")
async def confirm_checkin(request: CheckinRequest):
    """
    Confirm check-in and create attendance record
    
    This endpoint is called after the volunteer confirms the check-in on the tablet.
    """
    try:
        print(f"Confirm check-in request: session={request.session_id}, station={request.station_id}, created_by={request.created_by}")
        
        # Validate station
        if not validate_station(request.station_id):
            print(f"Invalid station ID: {request.station_id}")
            await Database.log_event("warning", "api", f"Invalid station ID: {request.station_id}")
            return {
                "success": False,
                "message": "Invalid station ID"
            }
        
        # Get session details
        try:
            session_info = await Database.get_checkin_session(request.session_id)
            if not session_info:
                print(f"Session not found: {request.session_id}")
                await Database.log_event("warning", "api", "Invalid or expired session", 
                                       details=f"Session: {request.session_id}")
                return {
                    "success": False,
                    "message": "Session expired or not found. Please scan again."
                }
        except Exception as session_error:
            print(f"Error getting session info: {session_error}")
            await Database.log_event("error", "api", f"Failed to get session info: {str(session_error)}", 
                                   details=f"Session: {request.session_id}")
            raise HTTPException(status_code=500, detail="Session lookup failed")
        
        # Confirm check-in
        try:
            success = await Database.confirm_checkin(
                session_id=request.session_id,
                station_id=request.station_id,
                created_by=request.created_by
            )
            print(f"Check-in confirmation result: {success}")
        except Exception as confirm_error:
            print(f"Error confirming check-in: {confirm_error}")
            await Database.log_event("error", "api", f"Failed to confirm check-in: {str(confirm_error)}", 
                                   details=f"Session: {request.session_id}")
            raise HTTPException(status_code=500, detail="Check-in confirmation failed")
        
        if success:
            child_name = f"{session_info.get('first_name', '')} {session_info.get('last_name', '')}".strip()
            print(f"Check-in successful for child: {child_name}")
            
            # Get attendance_id
            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(text("SELECT id FROM attendance WHERE child_id = :child_id ORDER BY created_at DESC LIMIT 1"), {"child_id": session_info['child_id']})
                    row = result.fetchone()
                    attendance_id = row[0] if row else None
                print(f"Attendance record created with ID: {attendance_id}")
            except Exception as attendance_error:
                print(f"Error getting attendance ID: {attendance_error}")
                await Database.log_event("error", "api", f"Failed to get attendance ID: {str(attendance_error)}", 
                                       details=f"Child ID: {session_info['child_id']}")
                attendance_id = None
            
            # Get label payload
            label_payload = None
            if attendance_id:
                try:
                    label_payload = await get_print_payload(attendance_id)
                    print("Label payload retrieved successfully")
                except Exception as payload_error:
                    print(f"Error getting label payload: {payload_error}")
                    await Database.log_event("warning", "api", f"Failed to get label payload: {str(payload_error)}", 
                                           details=f"Attendance ID: {attendance_id}")
            
            await Database.log_event("info", "api", "Check-in confirmed", 
                                   details=f"Child: {child_name}, Volunteer: {request.created_by}")
            
            return {
                "success": True,
                "message": f"{child_name} checked in successfully!",
                "attendance_id": attendance_id,
                "label_payload": label_payload
            }
        else:
            print(f"Check-in confirmation returned false for session: {request.session_id}")
            await Database.log_event("error", "api", "Failed to confirm check-in", 
                                   details=f"Session: {request.session_id}")
            return {
                "success": False,
                "message": "Failed to check in. Please try again."
            }
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in confirm_checkin: {e}")
        await Database.log_event("error", "api", f"Unexpected error confirming check-in: {str(e)}", 
                               details=f"Session: {request.session_id}")
        raise HTTPException(status_code=500, detail="Check-in failed")

@app.post("/api/checkin-direct")
async def direct_checkin(request: DirectCheckinRequest, current_user: dict = Depends(get_current_user)):
    """Direct check-in from scanner search - requires auth"""
    try:
        print(f"Direct checkin request: child_id={request.child_id}, program_id={request.program_id}, station={request.station_id}, user={current_user['username']}")
        
        # Create attendance record
        created_by = f"{current_user['first_name']} {current_user['last_name']}".strip() or current_user['username']
        print(f"Created by: {created_by}")
        
        try:
            attendance_id = await Database.create_attendance(
                child_id=request.child_id,
                program_id=request.program_id,
                station_id=request.station_id,
                created_by=created_by
            )
            print(f"Attendance created with ID: {attendance_id}")
        except Exception as attendance_error:
            print(f"Error creating attendance record: {attendance_error}")
            await Database.log_event("error", "api", f"Failed to create attendance: {str(attendance_error)}", 
                                   details=f"Child: {request.child_id}, User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Failed to create attendance record")
        
        # Get child name
        child_name = "Unknown Child"
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(text("SELECT first_name, last_name FROM children WHERE id = :id"), {"id": request.child_id})
                row = result.fetchone()
                child_name = f"{row[0]} {row[1]}" if row else "Unknown Child"
            print(f"Child name: {child_name}")
        except Exception as name_error:
            print(f"Error getting child name: {name_error}")
            await Database.log_event("warning", "api", f"Failed to get child name: {str(name_error)}", 
                                   details=f"Child ID: {request.child_id}")
        
        # Get label payload
        label_payload = None
        try:
            label_payload = await get_print_payload(attendance_id)
            print("Label payload retrieved")
        except Exception as payload_error:
            print(f"Error getting label payload: {payload_error}")
            await Database.log_event("warning", "api", f"Failed to get label payload: {str(payload_error)}", 
                                   details=f"Attendance ID: {attendance_id}")
        
        await Database.log_event("info", "api", f"Direct check-in: {child_name}", 
                               details=f"Station: {request.station_id}, Volunteer: {current_user['username']}")
        
        return {
            "success": True,
            "message": f"{child_name} checked in successfully!",
            "attendance_id": attendance_id,
            "label_payload": label_payload
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in direct_checkin: {e}")
        await Database.log_event("error", "api", f"Unexpected error in direct check-in: {str(e)}")
        raise HTTPException(status_code=500, detail="Direct check-in failed")

@app.post("/api/register", response_model=RegisterResponse)
async def register_new_child(request: RegisterRequest, current_user: dict = Depends(get_current_user)):
    """
    Register a new child and family - requires auth
    
    This endpoint is called when a new child is registered at the check-in station.
    """
    try:
        print(f"Registration request: child={request.child_first_name} {request.child_last_name}, parent={request.parent_first_name} {request.parent_last_name}")
        
        # Validate phone (10 digits)
        if not request.parent_phone.isdigit() or len(request.parent_phone) != 10:
            print(f"Invalid phone number: {request.parent_phone}")
            await Database.log_event("warning", "api", f"Invalid phone number format", 
                                   details=f"Phone: {request.parent_phone}, User: {current_user['username']}")
            raise HTTPException(status_code=400, detail="Phone number must be exactly 10 digits")
        
        # Validate email
        if '@' not in request.parent_email or '.' not in request.parent_email:
            print(f"Invalid email format: {request.parent_email}")
            await Database.log_event("warning", "api", f"Invalid email format", 
                                   details=f"Email: {request.parent_email}, User: {current_user['username']}")
            raise HTTPException(status_code=400, detail="Invalid email address")
        
        # Combine birth date
        try:
            from datetime import date
            birth_date = date(request.child_birth_year, request.child_birth_month, request.child_birth_day).isoformat()
            print(f"Birth date parsed: {birth_date}")
        except ValueError as date_error:
            print(f"Invalid birth date: {request.child_birth_year}-{request.child_birth_month}-{request.child_birth_day}")
            await Database.log_event("warning", "api", f"Invalid birth date provided", 
                                   details=f"Date: {request.child_birth_year}-{request.child_birth_month}-{request.child_birth_day}, User: {current_user['username']}")
            raise HTTPException(status_code=400, detail="Invalid birth date")
        
        # Generate unique QR value
        qr_value = f"KID-{str(uuid.uuid4())}"
        print(f"Generated QR value: {qr_value}")
        
        # Construct data dicts
        child_data = {
            "first_name": request.child_first_name,
            "last_name": request.child_last_name,
            "birth_date": birth_date,
            "allergies": None,
            "medications": None,
            "special_notes": request.child_special_notes,
            "medical_notes": request.child_medical_notes
        }
        
        family_data = {
            "family_name": request.parent_last_name + " Family"
        }
        
        parent_data = {
            "first_name": request.parent_first_name,
            "last_name": request.parent_last_name,
            "phone": request.parent_phone,
            "email": request.parent_email,
            "relationship": request.parent_relationship
        }
        
        # Register the child
        try:
            child_id = await Database.register_new_child(
                child_data=child_data,
                family_data=family_data,
                parent_data=parent_data,
                qr_value=qr_value
            )
            print(f"Child registered with ID: {child_id}")
        except Exception as register_error:
            print(f"Error registering child: {register_error}")
            await Database.log_event("error", "api", f"Failed to register child: {str(register_error)}", 
                                   details=f"Child: {request.child_first_name} {request.child_last_name}, User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Failed to register child")
        
        # Check in the child
        try:
            await Database.create_attendance(
                child_id=child_id,
                program_id=request.program_id,
                station_id=request.station_id,
                created_by=current_user['username']
            )
            print("Child checked in successfully")
        except Exception as checkin_error:
            print(f"Error checking in child: {checkin_error}")
            await Database.log_event("error", "api", f"Failed to check in registered child: {str(checkin_error)}", 
                                   details=f"Child ID: {child_id}, User: {current_user['username']}")
            # Don't fail the registration if check-in fails, just log it
        
        child_name = f"{request.child_first_name} {request.child_last_name}"
        await Database.log_event("info", "api", f"New child registered and checked in: {child_name}", 
                               details=f"Volunteer: {current_user['username']}")
        
        return RegisterResponse(
            success=True,
            message=f"{child_name} registered and checked in successfully!",
            child_id=child_id,
            qr_value=qr_value
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Registration error: {str(e)}")  # Debug print
        await Database.log_event("error", "api", f"Error registering child: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/child/{child_id}/qr")
async def get_child_qr_image(child_id: int, current_user: dict = Depends(get_current_user)):
    """Download QR code image for child - Admin only"""
    try:
        if current_user['role'] != 'admin':
            await Database.log_event("warning", "api", "Unauthorized QR code access attempt", 
                                   details=f"Child ID: {child_id}, User: {current_user['username']}")
            raise HTTPException(status_code=403, detail="Admin access required")
        
        try:
            qr_value = await Database.get_child_qr(child_id)
            if not qr_value:
                print(f"QR code not found for child {child_id}")
                await Database.log_event("warning", "api", f"QR code not found for child {child_id}", 
                                       details=f"User: {current_user['username']}")
                raise HTTPException(status_code=404, detail="QR not found")
        except HTTPException:
            raise
        except Exception as qr_error:
            print(f"Error getting QR value for child {child_id}: {qr_error}")
            await Database.log_event("error", "api", f"Failed to get QR value for child {child_id}: {str(qr_error)}", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Failed to retrieve QR code")
        
        # Generate QR image
        try:
            import qrcode
            from io import BytesIO
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_value)
            qr.make(fit=True)
            img = qr.make_image(fill='black', back_color='white')
            buf = BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
        except Exception as img_error:
            print(f"Error generating QR image for child {child_id}: {img_error}")
            await Database.log_event("error", "api", f"Failed to generate QR image for child {child_id}: {str(img_error)}", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Failed to generate QR image")
        
        # Get child name for filename
        child_name = f"child_{child_id}"
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(text("SELECT first_name, last_name FROM children WHERE id = :id"), {"id": child_id})
                row = result.fetchone()
                if row:
                    child_name = f"{row[0]}_{row[1]}"
        except Exception as name_error:
            print(f"Error getting child name for filename: {name_error}")
            # Don't fail the request if we can't get the name
        
        print(f"Generated QR image for child {child_id} ({child_name})")
        await Database.log_event("info", "api", f"QR code downloaded for child {child_id}", 
                               details=f"User: {current_user['username']}")
        
        return Response(
            buf.getvalue(),
            media_type="image/png",
            headers={"Content-Disposition": f"attachment; filename={child_name}_QR.png"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in get_child_qr_image: {e}")
        await Database.log_event("error", "api", f"Unexpected error downloading QR for child {child_id}: {str(e)}", 
                               details=f"User: {current_user['username']}")
        raise HTTPException(status_code=500, detail="QR download failed")

@app.get("/api/admin/children")
async def get_admin_children(current_user: dict = Depends(get_current_user)):
    """Get children list for admin - Admin only"""
    try:
        if current_user['role'] != 'admin':
            await Database.log_event("warning", "api", "Unauthorized children list access", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=403, detail="Admin access required")
        
        try:
            print("before get_all_children")
            async with AsyncSessionLocal() as db:
                result = await db.execute(text("SELECT id, first_name, last_name FROM children ORDER BY last_name, first_name"))
                rows = result.fetchall()
                columns = result.keys()
                children = [dict(zip(columns, row)) for row in rows]
            print(f"children: {children}")
            await Database.log_event("info", "api", "Children list retrieved for admin", 
                                   details=f"Count: {len(children)}, User: {current_user['username']}")
            return children
        except Exception as db_error:
            print(f"error in get_admin_children: {db_error}")
            await Database.log_event("error", "api", f"Database error in get_admin_children: {str(db_error)}", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Database error")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in get_admin_children: {e}")
        await Database.log_event("error", "api", f"Unexpected error in get_admin_children: {str(e)}", 
                               details=f"User: {current_user['username']}")
        raise HTTPException(status_code=500, detail="Children list unavailable")

@app.get("/api/session/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    """Get session information for confirmation"""
    try:
        print(f"Getting session info for: {session_id}")
        try:
            session_info = await Database.get_session_info(session_id)
            if not session_info:
                print(f"Session not found: {session_id}")
                raise HTTPException(status_code=404, detail="Session not found or expired")
        except HTTPException:
            raise
        except Exception as session_error:
            print(f"Error getting session info: {session_error}")
            raise HTTPException(status_code=500, detail="Session lookup failed")
        
        # Check expiry
        try:
            from datetime import datetime
            if datetime.now() > session_info['expires_at']:
                print(f"Session expired: {session_id}")
                raise HTTPException(status_code=404, detail="Session not found or expired")
        except HTTPException:
            raise
        except Exception as expiry_error:
            print(f"Error checking session expiry: {expiry_error}")
            raise HTTPException(status_code=500, detail="Session validation failed")
        
        # Convert to Pydantic models
        try:
            programs = [Program(**p) for p in session_info["programs"]]
            child_info = ChildInfo(**session_info["child_info"])
            print(f"Session retrieved successfully for child: {child_info.first_name} {child_info.last_name}")
            return SessionInfo(
                session_id=session_id,
                child_info=child_info,
                programs=programs
            )
        except Exception as model_error:
            print(f"Error converting session data to models: {model_error}")
            raise HTTPException(status_code=500, detail="Session data format error")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in get_session: {e}")
        raise HTTPException(status_code=500, detail="Session retrieval failed")

@app.get("/api/attendance/download")
async def download_attendance(current_user: dict = Depends(get_current_user)):
    """Download attendance records as CSV - Admin only"""
    try:
        if current_user['role'] != 'admin':
            await Database.log_event("warning", "api", "Unauthorized attendance download attempt", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=403, detail="Admin access required")
        
        from sqlalchemy import text
        try:
            print("Starting attendance download")
            # Get all attendance records with child and program info
            async with AsyncSessionLocal() as db:
                result = await db.execute(text("""
                    SELECT 
                        a.id,
                        a.checkin_time,
                        a.created_by,
                        c.first_name || ' ' || c.last_name as child_name,
                        f.family_name,
                        p.name as program_name,
                        pr.first_name || ' ' || pr.last_name as parent_name,
                        pr.phone as parent_phone,
                        pr.email as parent_email
                    FROM attendance a
                    JOIN children c ON a.child_id = c.id
                    JOIN families f ON c.family_id = f.id
                    LEFT JOIN programs p ON a.program_id = p.id
                    LEFT JOIN parents pr ON f.id = pr.family_id
                    ORDER BY a.checkin_time DESC
                """))
                
                rows = result.fetchall()
                columns = result.keys()
                print(f"Retrieved {len(rows)} attendance records")
            
            # Create CSV in memory
            try:
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Write header
                writer.writerow(columns)
                
                # Write data
                for row in rows:
                    writer.writerow([str(cell) for cell in row])
                
                output.seek(0)
                print("CSV generated successfully")
            except Exception as csv_error:
                print(f"Error generating CSV: {csv_error}")
                await Database.log_event("error", "api", f"Failed to generate attendance CSV: {str(csv_error)}", 
                                       details=f"User: {current_user['username']}")
                raise HTTPException(status_code=500, detail="CSV generation failed")
            
            await Database.log_event("info", "api", f"Attendance CSV downloaded", 
                                   details=f"Records: {len(rows)}, User: {current_user['username']}")
            
            # Return CSV file
            return Response(
                output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=attendance_records.csv"}
            )
            
        except Exception as db_error:
            print(f"Database error in download_attendance: {db_error}")
            await Database.log_event("error", "api", f"Database error downloading attendance: {str(db_error)}", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Database error")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in download_attendance: {e}")
        await Database.log_event("error", "api", f"Unexpected error downloading attendance: {str(e)}", 
                               details=f"User: {current_user['username']}")
        raise HTTPException(status_code=500, detail="Attendance download failed")

@app.get("/api/attendance/stats")
async def get_attendance_stats(current_user: dict = Depends(get_current_user)):
    """Get attendance statistics - Admin only"""
    try:
        if current_user['role'] != 'admin':
            await Database.log_event("warning", "api", "Unauthorized attendance stats access", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=403, detail="Admin access required")
        
        try:
            async with AsyncSessionLocal() as db:
                print("Getting attendance statistics")
                
                # Today's check-ins
                today = datetime.now().date()
                result = await db.execute(text("SELECT COUNT(*) FROM attendance WHERE DATE(checkin_time) = :today"), {"today": today})
                checkins_today = result.scalar()
                print(f"Today's check-ins: {checkins_today}")
                
                # This week's check-ins
                week_ago = datetime.now() - timedelta(days=7)
                result = await db.execute(text("SELECT COUNT(*) FROM attendance WHERE checkin_time >= :week_ago"), {"week_ago": week_ago})
                checkins_week = result.scalar()
                print(f"This week's check-ins: {checkins_week}")
                
                # This month's check-ins
                month_start = datetime.now().replace(day=1)
                result = await db.execute(text("SELECT COUNT(*) FROM attendance WHERE checkin_time >= :month_start"), {"month_start": month_start})
                checkins_month = result.scalar()
                print(f"This month's check-ins: {checkins_month}")
                
                # Total registered children
                result = await db.execute(text("SELECT COUNT(*) FROM children"))
                total_children = result.scalar()
                print(f"Total children: {total_children}")
                
            stats = {
                "checkins_today": checkins_today,
                "checkins_week": checkins_week,
                "checkins_month": checkins_month,
                "total_children": total_children
            }
            
            await Database.log_event("info", "api", f"Attendance stats retrieved", 
                                   details=f"Today: {checkins_today}, Week: {checkins_week}, Month: {checkins_month}, Children: {total_children}, User: {current_user['username']}")
            
            return stats
            
        except Exception as db_error:
            print(f"Database error in get_attendance_stats: {db_error}")
            await Database.log_event("error", "api", f"Database error getting attendance stats: {str(db_error)}", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Database error")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in get_attendance_stats: {e}")
        await Database.log_event("error", "api", f"Unexpected error getting attendance stats: {str(e)}", 
                               details=f"User: {current_user['username']}")
        raise HTTPException(status_code=500, detail="Attendance stats unavailable")

@app.get("/api/volunteers")
async def get_volunteers(current_user: dict = Depends(get_current_user)):
    """Get all volunteers - Admin only"""
    try:
        if current_user['role'] != 'admin':
            await Database.log_event("warning", "api", "Unauthorized access to volunteers list", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=403, detail="Admin access required")
        
        print("before get_all_volunteers")
        try:
            from sqlalchemy import text
            async with AsyncSessionLocal() as db:
                result = await db.execute(text("SELECT id, username, first_name, last_name, role, enabled_2fa, active FROM volunteers ORDER BY username"))
                rows = result.fetchall()
                columns = result.keys()
                volunteers = [dict(zip(columns, row)) for row in rows]
            print(f"volunteers: {volunteers}")
            await Database.log_event("info", "api", "Volunteers list retrieved", 
                                   details=f"Count: {len(volunteers)}, Requested by: {current_user['username']}")
            return volunteers
        except Exception as db_error:
            print(f"error in get_volunteers: {db_error}")
            await Database.log_event("error", "api", f"Database error in get_volunteers: {str(db_error)}", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Database error")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in get_volunteers: {e}")
        await Database.log_event("error", "api", f"Unexpected error in get_volunteers: {str(e)}", 
                               details=f"User: {current_user['username']}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/volunteers")
async def add_volunteer(request: AddVolunteerRequest, current_user: dict = Depends(get_current_user)):
    """Add new volunteer - Admin only"""
    try:
        if current_user['role'] != 'admin':
            await Database.log_event("warning", "api", "Unauthorized volunteer creation attempt", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=403, detail="Admin access required")
        
        print(f"Received request: {request.dict()}")
        
        try:
            # Check if username already exists
            existing = await Database.get_user_by_username(request.username)
            if existing:
                await Database.log_event("warning", "api", f"Duplicate username attempt: {request.username}", 
                                       details=f"Attempted by: {current_user['username']}")
                raise HTTPException(status_code=400, detail="Username already exists")
            
            # Ensure role is set
            request.role = request.role or "volunteer"
            
            # Generate random password
            password = secrets.token_urlsafe(12)
            password_hash = get_password_hash(password)
            
            # Create volunteer
            try:
                volunteer_id = await Database.create_volunteer(
                    username=request.username,
                    password_hash=password_hash,
                    first_name=request.first_name,
                    last_name=request.last_name,
                    role=request.role
                )
                print(f"Volunteer created with ID: {volunteer_id}")
            except Exception as create_error:
                print(f"Error in create_volunteer: {create_error}")
                await Database.log_event("error", "api", f"Failed to create volunteer {request.username}: {str(create_error)}", 
                                       details=f"Attempted by: {current_user['username']}")
                raise
            
            # Log event
            await Database.log_event("info", "api", f"New volunteer created: {request.username}", 
                                   details=f"Created by: {current_user['username']}")
            
            return {
                "success": True,
                "message": f"Volunteer {request.username} created successfully",
                "volunteer_id": volunteer_id,
                "temp_password": password  # Return temp password so admin can give it to volunteer
            }
            
        except HTTPException:
            raise
        except Exception as validation_error:
            print(f"Validation error in add_volunteer: {validation_error}")
            await Database.log_event("error", "api", f"Validation error creating volunteer: {str(validation_error)}", 
                                   details=f"Username: {request.username}, User: {current_user['username']}")
            raise HTTPException(status_code=400, detail="Invalid volunteer data")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in add_volunteer: {e}")
        await Database.log_event("error", "api", f"Unexpected error creating volunteer: {str(e)}", 
                               details=f"Username: {request.username}, User: {current_user['username']}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.put("/api/volunteers/{volunteer_id}")
async def update_volunteer(volunteer_id: int, request: UpdateVolunteerRequest, current_user: dict = Depends(get_current_user)):
    """Update volunteer - Admin only"""
    try:
        if current_user['role'] != 'admin':
            await Database.log_event("warning", "api", "Unauthorized volunteer update attempt", 
                                   details=f"Volunteer ID: {volunteer_id}, User: {current_user['username']}")
            raise HTTPException(status_code=403, detail="Admin access required")
        
        try:
            # Prepare updates dict
            updates = {}
            if request.first_name is not None:
                updates['first_name'] = request.first_name
            if request.last_name is not None:
                updates['last_name'] = request.last_name
            if request.role is not None:
                updates['role'] = request.role
            if request.active is not None:
                updates['active'] = request.active
            
            # Handle 2FA changes
            if request.enabled_2fa is not None:
                try:
                    if request.enabled_2fa:
                        # Generate new TOTP secret if enabling
                        totp_secret = pyotp.random_base32()
                        await Database.update_volunteer_2fa(volunteer_id, totp_secret, True)
                        await Database.log_event("info", "api", f"2FA enabled for volunteer {volunteer_id}", 
                                               details=f"Updated by: {current_user['username']}")
                    else:
                        # Disable 2FA
                        await Database.update_volunteer_2fa(volunteer_id, None, False)
                        await Database.log_event("info", "api", f"2FA disabled for volunteer {volunteer_id}", 
                                               details=f"Updated by: {current_user['username']}")
                except Exception as fa_error:
                    print(f"Error updating 2FA for volunteer {volunteer_id}: {fa_error}")
                    await Database.log_event("error", "api", f"Failed to update 2FA for volunteer {volunteer_id}: {str(fa_error)}", 
                                           details=f"User: {current_user['username']}")
                    raise HTTPException(status_code=500, detail="Failed to update 2FA settings")
            
            # Update other fields
            if updates:
                try:
                    await Database.update_volunteer(volunteer_id, updates)
                except Exception as update_error:
                    print(f"Error updating volunteer {volunteer_id}: {update_error}")
                    await Database.log_event("error", "api", f"Failed to update volunteer {volunteer_id}: {str(update_error)}", 
                                           details=f"Updates: {updates}, User: {current_user['username']}")
                    raise
            
            await Database.log_event("info", "api", f"Volunteer {volunteer_id} updated", 
                                   details=f"Updates: {list(updates.keys()) if updates else '2FA only'}, Updated by: {current_user['username']}")
            
            return {"success": True, "message": "Volunteer updated successfully"}
            
        except HTTPException:
            raise
        except Exception as validation_error:
            print(f"Validation error in update_volunteer: {validation_error}")
            await Database.log_event("error", "api", f"Validation error updating volunteer {volunteer_id}: {str(validation_error)}", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=400, detail="Invalid update data")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in update_volunteer: {e}")
        await Database.log_event("error", "api", f"Unexpected error updating volunteer {volunteer_id}: {str(e)}", 
                               details=f"User: {current_user['username']}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.delete("/api/volunteers/{volunteer_id}")
async def delete_volunteer(volunteer_id: int, current_user: dict = Depends(get_current_user)):
    """Delete volunteer - Admin only (cannot delete admin)"""
    print(f"Starting delete_volunteer for ID: {volunteer_id}, user: {current_user['username']}")
    try:
        print(f"Checking admin role for user: {current_user['role']}")
        if current_user['role'] != 'admin':
            await Database.log_event("warning", "api", "Unauthorized volunteer deletion attempt", 
                                   details=f"Volunteer ID: {volunteer_id}, User: {current_user['username']}")
            raise HTTPException(status_code=403, detail="Admin access required")
        
        print(f"User is admin, checking if volunteer {volunteer_id} is admin")
        try:
            async with AsyncSessionLocal() as db:
                print(f"Executing query: SELECT role FROM volunteers WHERE id = {volunteer_id}")
                result = await db.execute(text("SELECT role FROM volunteers WHERE id = :id"), {"id": volunteer_id})
                row = result.fetchone()
                print(f"Query result: {row}")
                if row and row[0] == 'admin':
                    await Database.log_event("warning", "api", "Attempted to delete admin user", 
                                           details=f"Volunteer ID: {volunteer_id}, User: {current_user['username']}")
                    raise HTTPException(status_code=400, detail="Cannot delete admin users")
            
            print(f"Volunteer {volunteer_id} is not admin, proceeding with deletion")
            try:
                print(f"Calling Database.delete_volunteer({volunteer_id})")
                await Database.delete_volunteer(volunteer_id)
                print(f"Database.delete_volunteer completed successfully")
                await Database.log_event("info", "api", f"Volunteer {volunteer_id} deleted", 
                                       details=f"Deleted by: {current_user['username']}")
                return {"success": True, "message": "Volunteer deleted successfully"}
            except Exception as delete_error:
                print(f"Error in Database.delete_volunteer: {delete_error}")
                await Database.log_event("error", "api", f"Failed to delete volunteer {volunteer_id}: {str(delete_error)}", 
                                       details=f"User: {current_user['username']}")
                raise HTTPException(status_code=500, detail="Failed to delete volunteer")
            
        except HTTPException:
            raise
        except Exception as db_error:
            print(f"Database error in delete_volunteer: {db_error}")
            await Database.log_event("error", "api", f"Database error deleting volunteer {volunteer_id}: {str(db_error)}", 
                                   details=f"User: {current_user['username']}")
            raise HTTPException(status_code=500, detail="Database error")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in delete_volunteer: {e}")
        await Database.log_event("error", "api", f"Unexpected error deleting volunteer {volunteer_id}: {str(e)}", 
                               details=f"User: {current_user['username']}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user['username'],
        "first_name": current_user.get('first_name', ''),
        "last_name": current_user.get('last_name', ''),
        "role": current_user['role']
    }

@app.post("/api/setup_2fa")
async def setup_2fa(request: Setup2FARequest):
    user = await Database.get_user_by_username(request.username)
    if not user:
        raise HTTPException(status_code=400, detail="User not found")
    totp = pyotp.TOTP(request.totp_secret)
    if not totp.verify(request.otp):
        raise HTTPException(status_code=400, detail="Invalid OTP")
    await Database.update_volunteer_2fa(user['id'], request.totp_secret, True)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['username']}, expires_delta=access_token_expires
    )
    request.session['token'] = access_token
    return {"success": True, "token": access_token, "role": user['role']}

@app.get("/profile")
async def profile_page(request: Request, current_user: dict = Depends(get_current_user)):
    return templates.TemplateResponse("profile.html", {"request": request, "user": current_user})

@app.get("/api/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user['username'],
        "first_name": current_user['first_name'],
        "last_name": current_user['last_name'],
        "email": current_user.get('email', ''),
        "role": current_user['role']
    }

@app.put("/api/profile")
async def update_profile(request: ProfileUpdateRequest, current_user: dict = Depends(get_current_user)):
    updates = {}
    if request.first_name is not None:
        updates['first_name'] = request.first_name
    if request.last_name is not None:
        updates['last_name'] = request.last_name
    if request.email is not None:
        updates['email'] = request.email
    if updates:
        await Database.update_volunteer(current_user['id'], updates)
    return {"success": True, "message": "Profile updated"}

@app.post("/api/change-password")
async def change_password(request: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    if not verify_password(request.current_password, current_user['password_hash']):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if not validate_password(request.new_password):
        raise HTTPException(status_code=400, detail="Password does not meet strength requirements")
    new_hash = get_password_hash(request.new_password)
    await Database.update_volunteer(current_user['id'], {'password_hash': new_hash})
    return {"success": True, "message": "Password changed"}

@app.get("/api/programs/all")
async def get_all_programs(current_user: dict = Depends(get_current_user)):
    """Get all programs including inactive ones - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        from sqlalchemy import text
        print("before get_all_programs")
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT * FROM programs ORDER BY name"))
            rows = result.fetchall()
            columns = result.keys()
            programs = [dict(zip(columns, row)) for row in rows]
        print(f"programs: {programs}")
        return programs
    except Exception as e:
        print(f"error in get_all_programs: {e}")
        await Database.log_event("error", "api", f"Error getting programs: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/programs")
async def add_program(request: AddProgramRequest, current_user: dict = Depends(get_current_user)):
    """Add new program - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Check if program name already exists
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM programs WHERE name = :name"), {"name": request.name})
            count = result.scalar()
            if count > 0:
                raise HTTPException(status_code=400, detail="Program name already exists")
        
        program_id = await Database.create_program(request.name, request.min_age, request.max_age)
        
        await Database.log_event("info", "api", f"New program created: {request.name}", 
                               details=f"Created by: {current_user['username']}")
        
        return {
            "success": True,
            "message": f"Program '{request.name}' created successfully",
            "program_id": program_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await Database.log_event("error", "api", f"Error creating program: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.put("/api/programs/{program_id}")
async def update_program(program_id: int, request: UpdateProgramRequest, current_user: dict = Depends(get_current_user)):
    """Update program - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        updates = {}
        if request.name is not None:
            updates['name'] = request.name
        if request.min_age is not None:
            updates['min_age'] = request.min_age
        if request.max_age is not None:
            updates['max_age'] = request.max_age
        if request.active is not None:
            updates['active'] = request.active
        
        if updates:
            await Database.update_program(program_id, updates)
        
        await Database.log_event("info", "api", f"Program {program_id} updated", 
                               details=f"Updated by: {current_user['username']}")
        
        return {"success": True, "message": "Program updated successfully"}
        
    except Exception as e:
        await Database.log_event("error", "api", f"Error updating program: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.delete("/api/programs/{program_id}")
async def delete_program(program_id: int, current_user: dict = Depends(get_current_user)):
    """Delete program - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        await Database.delete_program(program_id)
        
        await Database.log_event("info", "api", f"Program {program_id} deleted", 
                               details=f"Deleted by: {current_user['username']}")
        
        return {"success": True, "message": "Program deleted successfully"}
        
    except Exception as e:
        await Database.log_event("error", "api", f"Error deleting program: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/children")
async def get_all_children(current_user: dict = Depends(get_current_user)):
    """Get all children with QR codes - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        from sqlalchemy import text
        print("before get_all_children")
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("""
                SELECT c.id, c.first_name, c.last_name, f.family_name, qc.qr_value
                FROM children c
                JOIN families f ON c.family_id = f.id
                JOIN qr_codes qc ON c.id = qc.child_id
                WHERE c.active = TRUE AND qc.active = TRUE
                ORDER BY c.last_name, c.first_name
            """))
            rows = result.fetchall()
            columns = result.keys()
            children = [dict(zip(columns, row)) for row in rows]
        print(f"children: {children}")
        return children
    except Exception as e:
        print(f"error in get_all_children: {e}")
        await Database.log_event("error", "api", f"Error getting children: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/print_payload/{attendance_id}")
async def get_print_payload(attendance_id: int):
    """Get printable label payload for attendance"""
    try:
        async with AsyncSessionLocal() as db:
            # Get attendance with child info
            result = await db.execute(text("""
                SELECT a.*, c.first_name, c.last_name, c.birth_date, f.family_name
                FROM attendance a
                JOIN children c ON a.child_id = c.id
                JOIN families f ON c.family_id = f.id
                WHERE a.id = :attendance_id
            """), {"attendance_id": attendance_id})
            attendance = result.fetchone()
            if not attendance:
                raise HTTPException(status_code=404, detail="Attendance not found")
            
            # Get parents
            parents_result = await db.execute(text("""
                SELECT first_name, last_name, phone, relationship
                FROM parents
                WHERE family_id = (SELECT family_id FROM children WHERE id = :child_id)
            """), {"child_id": attendance.child_id})
            parents = parents_result.fetchall()
            
            # Calculate age
            try:
                if attendance.birth_date:
                    birth_date = date.fromisoformat(attendance.birth_date)
                    today = date.today()
                    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
                else:
                    age = "Unknown"
            except:
                age = "Unknown"
            
            # Create vCard
            vcard = f"""BEGIN:VCARD
VERSION:3.0
N:{attendance.last_name};{attendance.first_name};;;
FN:{attendance.first_name} {attendance.last_name}
TEL;TYPE=CELL:{parents[0].phone if parents else ''}
END:VCARD"""
            
            # Generate QR for vCard
            import qrcode
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(vcard)
            qr.make(fit=True)
            img = qr.make_image(fill='black', back_color='white')
            buf = BytesIO()
            img.save(buf, format='PNG')
            qr_b64 = base64.b64encode(buf.getvalue()).decode()
            
            # Label payload
            label_payload = {
                "child_name": f"{attendance.first_name} {attendance.last_name}",
                "age": age,
                "family_name": attendance.family_name,
                "parents": [{"name": f"{p.first_name} {p.last_name}", "phone": p.phone, "relationship": p.relationship} for p in parents],
                "qr_b64": qr_b64
            }
            
            return label_payload
    except Exception as e:
        await Database.log_event("error", "api", f"Error getting print payload: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/qr/{otpauth:path}")
async def generate_qr(otpauth: str):
    """Generate QR code for TOTP otpauth URL"""
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(otpauth)
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white')
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type="image/png")
    except Exception as e:
        await Database.log_event("error", "api", f"Error generating QR code: {str(e)}")
        raise HTTPException(status_code=500, detail="Error generating QR code")

@app.get("/admin/volunteers")
async def admin_volunteers_page(request: Request, current_user: dict = Depends(get_current_user)):
    """Admin volunteers management page - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    return templates.TemplateResponse("admin_volunteers.html", {"request": request})

# ... (rest of the code remains the same)
@app.get("/admin/programs")
async def admin_programs_page(request: Request, current_user: dict = Depends(get_current_user)):
    """Admin programs management page - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    return templates.TemplateResponse("admin_programs.html", {"request": request})

@app.get("/admin/attendance")
async def admin_attendance_page(request: Request, current_user: dict = Depends(get_current_user)):
    """Admin attendance reports page - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    return templates.TemplateResponse("admin_attendance.html", {"request": request})

@app.get("/admin/qrcodes")
async def admin_qrcodes_page(request: Request, current_user: dict = Depends(get_current_user)):
    """Admin QR codes management page - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    return templates.TemplateResponse("admin_qrcodes.html", {"request": request})

@app.get("/admin")
async def admin_dashboard(request: Request, current_user: dict = Depends(get_current_user)):
    """Admin dashboard page - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/login")
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register")
async def register_page(request: Request):
    """Register page"""
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/confirm")
async def confirm_page(request: Request):
    """Confirmation page"""
    return templates.TemplateResponse("confirm.html", {"request": request})

@app.get("/success")
async def success_page(request: Request):
    """Success page"""
    return templates.TemplateResponse("success.html", {"request": request})

@app.get("/scanner")
async def scanner_page(request: Request, current_user: dict = Depends(get_current_user)):
    """Scanner page for volunteers and admins"""
    if current_user['role'] not in ['admin', 'volunteer']:
        raise HTTPException(status_code=403, detail="Access denied")
    return templates.TemplateResponse("scanner.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
