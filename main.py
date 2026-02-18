import os
import uuid
import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

from database import Database, init_database, get_db
from models import (
    ScanRequest, ScanResponse, CheckinRequest, CheckinResponse,
    RegisterRequest, RegisterResponse, ChildInfo, Program, SessionInfo
)

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

# Station tokens from environment
STATION_TOKENS = os.getenv("STATION_TOKENS", "entrance-a,entrance-b,checkout-a").split(",")

def validate_station(station_id: str) -> bool:
    """Validate station ID"""
    return station_id in STATION_TOKENS

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    await init_database()
    await Database.log_event("info", "api", "Application started")

@app.get("/")
async def root(request: Request):
    """Root endpoint - redirect to scanner"""
    return templates.TemplateResponse("scanner.html", {"request": request})

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

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
async def register_new_child(request: RegisterRequest):
    """
    Register a new child and family
    
    This endpoint is called when a new child is registered at the check-in station.
    """
    try:
        # Register the child
        child_id = await Database.register_new_child(
            child_data=request.child,
            family_data=request.family,
            parent_data=request.parent,
            qr_value=request.qr_value
        )
        
        child_name = f"{request.child['first_name']} {request.child['last_name']}"
        await Database.log_event("info", "api", "New child registered", 
                               details=f"Child: {child_name}, Family: {request.family['family_name']}")
        
        return RegisterResponse(
            success=True,
            message=f"{child_name} registered successfully!",
            child_id=child_id
        )
        
    except Exception as e:
        await Database.log_event("error", "api", f"Error registering child: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/programs", response_model=List[Program])
async def get_programs():
    """Get all available programs"""
    try:
        programs = await Database.get_programs()
        return [Program(**program) for program in programs]
    except Exception as e:
        await Database.log_event("error", "api", f"Error getting programs: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/session/{session_id}")
async def get_session_info(session_id: str):
    """Get session information by ID"""
    try:
        session_info = await Database.get_checkin_session(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="Session not found")
        return session_info
    except Exception as e:
        await Database.log_event("error", "api", f"Error getting session: {str(e)}", 
                               details=f"Session: {session_id}")
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
