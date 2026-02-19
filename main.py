import os
import uuid
import secrets
from database import Database
from database import init_database
from database import get_db
from database import AsyncSessionLocal
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.responses import Response
import csv
import io
from models import (
    ScanRequest, ScanResponse, CheckinRequest, CheckinResponse,
    RegisterRequest, RegisterResponse, ChildInfo, Program, SessionInfo,
    LoginRequest, LoginResponse, Volunteer
)
from passlib.context import CryptContext
from jose import JWTError, jwt
from pydantic import BaseModel
from datetime import datetime, timedelta
import pyotp
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

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

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Auth configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
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
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = await Database.get_user_by_username(username)
    if user is None:
        raise credentials_exception
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

@app.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    user = await Database.get_user_by_username(request.username)
    if not user:
        return LoginResponse(success=False, message="Invalid username or password")
    if not verify_password(request.password, user['password_hash']):
        return LoginResponse(success=False, message="Invalid username or password")
    if user['enabled_2fa']:
        if not request.otp:
            return LoginResponse(success=False, message="2FA required", requires_2fa=True)
        totp = pyotp.TOTP(user['totp_secret'])
        if not totp.verify(request.otp):
            return LoginResponse(success=False, message="Invalid 2FA code")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['username']}, expires_delta=access_token_expires
    )
    return LoginResponse(success=True, message="Login successful", token=access_token)

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

@app.post("/api/checkin-direct", response_model=CheckinResponse)
async def checkin_direct(request: DirectCheckinRequest, current_user: dict = Depends(get_current_user)):
    """Direct check-in for searched children - requires auth"""
    try:
        # Validate station
        if not validate_station(request.station_id):
            return CheckinResponse(success=False, message="Invalid station ID")
        
        # Create attendance
        await Database.create_attendance(request.child_id, request.program_id, request.station_id, current_user['username'])
        
        # Get child name
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT first_name, last_name FROM children WHERE id = :id"), {"id": request.child_id})
            row = result.fetchone()
            child_name = f"{row[0]} {row[1]}" if row else "Unknown"
        
        await Database.log_event("info", "api", "Direct check-in", 
                               details=f"Child: {child_name}, Volunteer: {current_user['username']}")
        
        return CheckinResponse(success=True, message=f"{child_name} checked in successfully!", child_name=child_name)
        
    except Exception as e:
        await Database.log_event("error", "api", f"Error direct check-in: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

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

@app.post("/api/checkin", response_model=CheckinResponse)
async def confirm_checkin(request: CheckinRequest):
    """
    Confirm check-in and create attendance record
    
    This endpoint is called after the volunteer confirms the check-in on the tablet.
    """
    try:
        # Validate station
        if not validate_station(request.station_id):
            await Database.log_event("warning", "api", f"Invalid station ID: {request.station_id}")
            return CheckinResponse(
                success=False,
                message="Invalid station ID"
            )
        
        # Get session details
        session_info = await Database.get_checkin_session(request.session_id)
        
        if not session_info:
            await Database.log_event("warning", "api", "Invalid or expired session", 
                                   details=f"Session: {request.session_id}")
            return CheckinResponse(
                success=False,
                message="Session expired or not found. Please scan again."
            )
        
        # Confirm check-in
        success = await Database.confirm_checkin(
            session_id=request.session_id,
            station_id=request.station_id,
            created_by=request.created_by
        )
        
        if success:
            child_name = f"{session_info.get('first_name', '')} {session_info.get('last_name', '')}".strip()
            await Database.log_event("info", "api", "Check-in confirmed", 
                                   details=f"Child: {child_name}, Volunteer: {request.created_by}")
            
            return CheckinResponse(
                success=True,
                message=f"{child_name} checked in successfully!",
                child_name=child_name
            )
        else:
            await Database.log_event("error", "api", "Failed to confirm check-in", 
                                   details=f"Session: {request.session_id}")
            return CheckinResponse(
                success=False,
                message="Failed to check in. Please try again."
            )
            
    except Exception as e:
        await Database.log_event("error", "api", f"Error confirming check-in: {str(e)}", 
                               details=f"Session: {request.session_id}")
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
            "family_name": request.family_name
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

@app.get("/api/session/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    """Get session information for confirmation"""
    try:
        session_info = await Database.get_session_info(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        
        # Convert to Pydantic models
        programs = [Program(**p) for p in session_info["programs"]]
        child_info = ChildInfo(**session_info["child_info"])
        
        return SessionInfo(
            session_id=session_id,
            child_info=child_info,
            programs=programs
        )
        
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

@app.get("/scanner")
async def scanner_page(request: Request):
    """Scanner page"""
    return templates.TemplateResponse("scanner.html", {"request": request})

@app.get("/confirm")
async def confirm_page(request: Request):
    """Confirmation page"""
    return templates.TemplateResponse("confirm.html", {"request": request})

@app.get("/register")
async def register_page(request: Request):
    """Registration page"""
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/login")
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
