import os
import uuid
import secrets
import base64
from jose import jwt
import pyotp
from database import verify_password, get_password_hash
from database import init_database
from database import get_db
from database import AsyncSessionLocal
from database import Database
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
    Setup2FARequest
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

app.add_middleware(SessionMiddleware, secret_key="your-secret-key-here")

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Auth configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
security = HTTPBearer()

# Station tokens from environment
STATION_TOKENS = os.getenv("STATION_TOKENS", "entrance-a,entrance-b,checkout-a").split(",")

def validate_station(station_id: str) -> bool:
    """Validate station ID"""
    return station_id in STATION_TOKENS

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
    token = request.session.get('token')
    if not token:
        authorization = request.headers.get("Authorization")
        if authorization and authorization.startswith("Bearer "):
            token = authorization[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = str(payload.get("sub"))
        if username is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
    except JWTError:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = await Database.get_user_by_username(username)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

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
    user = await Database.get_user_by_username(login_data.username)
    if not user:
        return {"success": False, "message": "Invalid username or password"}
    if not verify_password(login_data.password, user['password_hash']):
        return {"success": False, "message": "Invalid username or password"}
    
    # Check 2FA
    if user.get('enabled_2fa'):
        if not login_data.otp:
            return {"success": False, "message": "2FA code required", "requires_2fa": True}
        totp = pyotp.TOTP(user['totp_secret'])
        if not totp.verify(login_data.otp):
            return {"success": False, "message": "Invalid 2FA code"}
    else:
        # Not enabled, setup required
        totp_secret = pyotp.random_base32()
        await Database.update_volunteer_2fa(user['id'], totp_secret, False)
        return {"success": False, "setup_2fa": True, "totp_secret": totp_secret, "message": "2FA setup required"}
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['username']}, expires_delta=access_token_expires
    )
    request.session['token'] = access_token
    return {"success": True, "message": "Login successful", "token": access_token, "role": user['role']}

@app.post("/api/setup_2fa")
async def setup_2fa_endpoint(request: Setup2FARequest):
    user = await Database.get_user_by_username(request.username)
    if not user:
        return {"success": False, "message": "User not found"}
    if user.get('enabled_2fa'):
        return {"success": False, "message": "2FA already enabled"}
    if not user.get('totp_secret'):
        return {"success": False, "message": "2FA not initialized"}
    
    totp = pyotp.TOTP(user['totp_secret'])
    if not totp.verify(request.totp_code):
        return {"success": False, "message": "Invalid 2FA code"}
    
    # Enable 2FA
    await Database.update_volunteer_2fa(user['id'], user['totp_secret'], True)
    
    # Create token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['username']}, expires_delta=access_token_expires
    )
    
    return {"success": True, "message": "2FA enabled", "token": access_token, "role": user['role']}

@app.get("/api/search-children")
async def search_children(query: str, current_user: dict = Depends(get_current_user)):
    """Search children by name - requires auth"""
    if not query or len(query) < 2:
        return []
    results = await Database.search_children(query)
    return results

@app.get("/api/programs")
async def get_programs_api():
    """Get all programs"""
    return await Database.get_programs()

@app.post("/api/scan", response_model=ScanResponse)
async def scan_qr_code(request: ScanRequest):
    """
    Scan QR code and create check-in session
    
    This endpoint is called when a QR code is scanned at a station.
    It validates the QR code, retrieves child information, and creates a temporary session.
    """
    try:
        # Validate station
        if not validate_station(request.station_id):
            await Database.log_event("warning", "api", f"Invalid station ID: {request.station_id}", 
                                   details=f"Device: {request.device_id}")
            return ScanResponse(
                success=False,
                message="Invalid station ID"
            )
        
        # Look up child by QR code
        child_info = await Database.get_child_by_qr(request.qr_value)
        
        if not child_info:
            await Database.log_event("warning", "api", "QR code not found", 
                                   details=f"QR: {request.qr_value[:10]}..., Station: {request.station_id}")
            return ScanResponse(
                success=False,
                message="QR code not found. Please register this child."
            )
        
        # Generate session ID
        session_id = secrets.token_urlsafe(16)
        
        # Get available programs
        programs = await Database.get_programs()
        
        # Create check-in session (without program_id for now - will be selected by user)
        await Database.create_checkin_session(
            session_id=session_id,
            child_id=child_info["id"],
            program_id=1,  # Default to first program, will be updated
            station_id=request.station_id,
            device_id=request.device_id
        )
        
        await Database.log_event("info", "api", "QR code scanned successfully", 
                               details=f"Child: {child_info['first_name']} {child_info['last_name']}, Session: {session_id}")
        
        return ScanResponse(
            success=True,
            session_id=session_id,
            child_info=child_info,
            programs=programs,
            message=f"Found {child_info['first_name']} {child_info['last_name']}"
        )
        
    except Exception as e:
        await Database.log_event("error", "api", f"Error scanning QR code: {str(e)}", 
                               details=f"QR: {request.qr_value[:10]}..., Station: {request.station_id}")
        raise HTTPException(status_code=500, detail="Internal server error")
async def scan_qr_code(request: ScanRequest):
    """
    Scan QR code and create check-in session
    
    This endpoint is called when a QR code is scanned at a station.
    It validates the QR code, retrieves child information, and creates a temporary session.
    """
    try:
        # Validate station
        if not validate_station(request.station_id):
            await Database.log_event("warning", "api", f"Invalid station ID: {request.station_id}", 
                                   details=f"Device: {request.device_id}")
            return ScanResponse(
                success=False,
                message="Invalid station ID"
            )
        
        # Look up child by QR code
        child_info = await Database.get_child_by_qr(request.qr_value)
        
        if not child_info:
            await Database.log_event("warning", "api", "QR code not found", 
                                   details=f"QR: {request.qr_value[:10]}..., Station: {request.station_id}")
            return ScanResponse(
                success=False,
                message="QR code not found. Please register this child."
            )
        
        # Generate session ID
        session_id = secrets.token_urlsafe(16)
        
        # Get available programs
        programs = await Database.get_programs()
        
        # Create check-in session (without program_id for now - will be selected by user)
        await Database.create_checkin_session(
            session_id=session_id,
            child_id=child_info["id"],
            program_id=1,  # Default to first program, will be updated
            station_id=request.station_id,
            device_id=request.device_id
        )
        
        await Database.log_event("info", "api", "QR code scanned successfully", 
                               details=f"Child: {child_info['first_name']} {child_info['last_name']}, Session: {session_id}")
        
        return ScanResponse(
            success=True,
            session_id=session_id,
            child_info=child_info,
            programs=programs,
            message=f"Found {child_info['first_name']} {child_info['last_name']}"
        )
        
    except Exception as e:
        await Database.log_event("error", "api", f"Error scanning QR code: {str(e)}", 
                               details=f"QR: {request.qr_value[:10]}..., Station: {request.station_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/checkin")
async def confirm_checkin(request: CheckinRequest):
    """
    Confirm check-in and create attendance record
    
    This endpoint is called after the volunteer confirms the check-in on the tablet.
    """
    try:
        # Validate station
        if not validate_station(request.station_id):
            await Database.log_event("warning", "api", f"Invalid station ID: {request.station_id}")
            return {
                "success": False,
                "message": "Invalid station ID"
            }
        
        # Get session details
        session_info = await Database.get_checkin_session(request.session_id)
        
        if not session_info:
            await Database.log_event("warning", "api", "Invalid or expired session", 
                                   details=f"Session: {request.session_id}")
            return {
                "success": False,
                "message": "Session expired or not found. Please scan again."
            }
        
        # Confirm check-in
        success = await Database.confirm_checkin(
            session_id=request.session_id,
            station_id=request.station_id,
            created_by=request.created_by
        )
        
        if success:
            child_name = f"{session_info.get('first_name', '')} {session_info.get('last_name', '')}".strip()
            
            # Get attendance_id
            async with AsyncSessionLocal() as db:
                result = await db.execute(text("SELECT id FROM attendance WHERE child_id = :child_id ORDER BY created_at DESC LIMIT 1"), {"child_id": session_info['child_id']})
                row = result.fetchone()
                attendance_id = row[0] if row else None
            
            # Get label payload
            label_payload = await get_print_payload(attendance_id) if attendance_id else None
            
            await Database.log_event("info", "api", "Check-in confirmed", 
                                   details=f"Child: {child_name}, Volunteer: {request.created_by}")
            
            return {
                "success": True,
                "message": f"{child_name} checked in successfully!",
                "attendance_id": attendance_id,
                "label_payload": label_payload
            }
        else:
            await Database.log_event("error", "api", "Failed to confirm check-in", 
                                   details=f"Session: {request.session_id}")
            return {
                "success": False,
                "message": "Failed to check in. Please try again."
            }
            
    except Exception as e:
        await Database.log_event("error", "api", f"Error confirming check-in: {str(e)}", 
                               details=f"Session: {request.session_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/checkin-direct")
async def direct_checkin(request: DirectCheckinRequest, current_user: dict = Depends(get_current_user)):
    """Direct check-in from scanner search - requires auth"""
    print(f"Direct checkin request: {request.dict()}")
    try:
        # Create attendance record
        created_by = f"{current_user['first_name']} {current_user['last_name']}".strip() or current_user['username']
        attendance_id = await Database.create_attendance(
            child_id=request.child_id,
            program_id=request.program_id,
            station_id=request.station_id,
            created_by=created_by
        )
        print(f"Attendance created with ID: {attendance_id}")
        # Get child name
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(text("SELECT first_name, last_name FROM children WHERE id = :id"), {"id": request.child_id})
                row = result.fetchone()
                child_name = f"{row[0]} {row[1]}" if row else "Unknown Child"
            print(f"Child name: {child_name}")
        except Exception as e:
            print(f"Error getting child name: {e}")
            raise
        
        # Get label payload
        try:
            label_payload = await get_print_payload(attendance_id)
            print("Label payload retrieved")
        except Exception as e:
            print(f"Error getting label payload: {e}")
            raise
        
        await Database.log_event("info", "api", f"Direct check-in: {child_name}", 
                               details=f"Station: {request.station_id}, Volunteer: {current_user['username']}")
        
        return {
            "success": True,
            "message": f"{child_name} checked in successfully!",
            "attendance_id": attendance_id,
            "label_payload": label_payload
        }
        
    except Exception as e:
        print(f"Unexpected error in direct_checkin: {e}")
        await Database.log_event("error", "api", f"Error direct check-in: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/register", response_model=RegisterResponse)
async def register_new_child(request: RegisterRequest, current_user: dict = Depends(get_current_user)):
    """
    Register a new child and family - requires auth
    
    This endpoint is called when a new child is registered at the check-in station.
    """
    try:
        # Validate phone (10 digits)
        if not request.parent_phone.isdigit() or len(request.parent_phone) != 10:
            raise HTTPException(status_code=400, detail="Phone number must be exactly 10 digits")
        
        # Validate email
        if '@' not in request.parent_email or '.' not in request.parent_email:
            raise HTTPException(status_code=400, detail="Invalid email address")
        
        # Combine birth date
        try:
            from datetime import date
            birth_date = date(request.child_birth_year, request.child_birth_month, request.child_birth_day).isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid birth date")
        
        # Generate unique QR value
        qr_value = f"KID-{str(uuid.uuid4())}"
        
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
        child_id = await Database.register_new_child(
            child_data=child_data,
            family_data=family_data,
            parent_data=parent_data,
            qr_value=qr_value
        )
        
        # Check in the child
        await Database.create_attendance(
            child_id=child_id,
            program_id=request.program_id,
            station_id=request.station_id,
            created_by=current_user['username']
        )
        
        child_name = f"{request.child_first_name} {request.child_last_name}"
        await Database.log_event("info", "api", f"New child registered and checked in: {child_name}", 
                               details=f"Volunteer: {current_user['username']}")
        
        return RegisterResponse(
            success=True,
            message=f"{child_name} registered and checked in successfully!",
            child_id=child_id,
            qr_value=qr_value
        )
        
    except Exception as e:
        print(f"Registration error: {str(e)}")  # Debug print
        await Database.log_event("error", "api", f"Error registering child: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/child/{child_id}/qr")
async def get_child_qr_image(child_id: int, current_user: dict = Depends(get_current_user)):
    """Download QR code image for child - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    qr_value = await Database.get_child_qr(child_id)
    if not qr_value:
        raise HTTPException(status_code=404, detail="QR not found")
    
    # Generate QR image
    import qrcode
    from io import BytesIO
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_value)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    # Get child name for filename
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT first_name, last_name FROM children WHERE id = :id"), {"id": child_id})
        row = result.fetchone()
        name = f"{row[0]}_{row[1]}" if row else f"child_{child_id}"
    
    return Response(
        buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f"attachment; filename={name}_QR.png"}
    )

@app.get("/api/admin/children")
async def get_admin_children(current_user: dict = Depends(get_current_user)):
    """Get children list for admin - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT id, first_name, last_name FROM children ORDER BY last_name, first_name"))
        rows = result.fetchall()
        return [dict(zip(result.keys(), row)) for row in rows]

@app.get("/api/session/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    """Get session information for confirmation"""
    try:
        session_info = await Database.get_session_info(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        
        # Check expiry
        from datetime import datetime
        if datetime.now() > session_info['expires_at']:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        
        # Convert to Pydantic models
        programs = [Program(**p) for p in session_info["programs"]]
        child_info = ChildInfo(**session_info["child_info"])
        
        return SessionInfo(
            session_id=session_id,
            child_info=child_info,
            programs=programs
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await Database.log_event("error", "api", f"Error getting session: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/attendance/download")
async def download_attendance(current_user: dict = Depends(get_current_user)):
    """Download attendance records as CSV - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from sqlalchemy import text
    try:
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
            
            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(columns)
            
            # Write data
            for row in rows:
                writer.writerow([str(cell) for cell in row])
            
            output.seek(0)
            
            # Return CSV file
            return Response(
                output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=attendance_records.csv"}
            )
            
    except Exception as e:
        await Database.log_event("error", "api", f"Error downloading attendance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/attendance/stats")
async def get_attendance_stats(current_user: dict = Depends(get_current_user)):
    """Get attendance statistics - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        async with AsyncSessionLocal() as db:
            # Today's check-ins
            today = datetime.now().date()
            result = await db.execute(text("SELECT COUNT(*) FROM attendance WHERE DATE(checkin_time) = :today"), {"today": today})
            checkins_today = result.scalar()
            
            # This week's check-ins
            week_ago = datetime.now() - timedelta(days=7)
            result = await db.execute(text("SELECT COUNT(*) FROM attendance WHERE checkin_time >= :week_ago"), {"week_ago": week_ago})
            checkins_week = result.scalar()
            
            # This month's check-ins
            month_start = datetime.now().replace(day=1)
            result = await db.execute(text("SELECT COUNT(*) FROM attendance WHERE checkin_time >= :month_start"), {"month_start": month_start})
            checkins_month = result.scalar()
            
            # Total registered children
            result = await db.execute(text("SELECT COUNT(*) FROM children"))
            total_children = result.scalar()
            
            return {
                "checkins_today": checkins_today,
                "checkins_week": checkins_week,
                "checkins_month": checkins_month,
                "total_children": total_children
            }
        
    except Exception as e:
        await Database.log_event("error", "api", f"Error getting attendance stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/volunteers")
async def get_volunteers(current_user: dict = Depends(get_current_user)):
    """Get all volunteers - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        from sqlalchemy import text
        print("before get_all_volunteers")
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT id, username, first_name, last_name, role, enabled_2fa, active FROM volunteers ORDER BY username"))
            rows = result.fetchall()
            columns = result.keys()
            volunteers = [dict(zip(columns, row)) for row in rows]
        print(f"volunteers: {volunteers}")
        return volunteers
    except Exception as e:
        print(f"error in get_volunteers: {e}")
        await Database.log_event("error", "api", f"Error getting volunteers: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/volunteers")
async def add_volunteer(request: AddVolunteerRequest, current_user: dict = Depends(get_current_user)):
    """Add new volunteer - Admin only"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    print(f"Received request: {request.dict()}")
    
    try:
        # Check if username already exists
        existing = await Database.get_user_by_username(request.username)
        if existing:
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
        except Exception as e:
            print(f"Error in create_volunteer: {e}")
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
    except Exception as e:
        print(f"Unexpected error in add_volunteer: {e}")
        await Database.log_event("error", "api", f"Error creating volunteer: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.put("/api/volunteers/{volunteer_id}")
async def update_volunteer(volunteer_id: int, request: UpdateVolunteerRequest, current_user: dict = Depends(get_current_user)):
    """Update volunteer - Admin only"""
    if current_user['role'] != 'admin':
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
            if request.enabled_2fa:
                # Generate new TOTP secret if enabling
                totp_secret = pyotp.random_base32()
                await Database.update_volunteer_2fa(volunteer_id, totp_secret, True)
            else:
                # Disable 2FA
                await Database.update_volunteer_2fa(volunteer_id, None, False)
        
        # Update other fields
        if updates:
            await Database.update_volunteer(volunteer_id, updates)
        
        await Database.log_event("info", "api", f"Volunteer {volunteer_id} updated", 
                               details=f"Updated by: {current_user['username']}")
        
        return {"success": True, "message": "Volunteer updated successfully"}
        
    except Exception as e:
        await Database.log_event("error", "api", f"Error updating volunteer: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.delete("/api/volunteers/{volunteer_id}")
async def delete_volunteer(volunteer_id: int, current_user: dict = Depends(get_current_user)):
    """Delete volunteer - Admin only (cannot delete admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Check if trying to delete admin
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT role FROM volunteers WHERE id = ?"), (volunteer_id,))
            row = result.fetchone()
            if row and row[0] == 'admin':
                raise HTTPException(status_code=400, detail="Cannot delete admin users")
        
        await Database.delete_volunteer(volunteer_id)
        
        try:
            await Database.log_event("info", "api", f"Volunteer {volunteer_id} deleted", 
                                   details=f"Deleted by: {current_user['username']}")
        except Exception as e:
            print(f"Log error: {e}")
        
        return {"success": True, "message": "Volunteer deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        await Database.log_event("error", "api", f"Error deleting volunteer: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user['username'],
        "first_name": current_user.get('first_name', ''),
        "last_name": current_user.get('last_name', ''),
        "role": current_user['role']
    }
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
