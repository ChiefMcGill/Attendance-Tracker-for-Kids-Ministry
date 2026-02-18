import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
import aiosqlite

# Database configuration
DB_PATH = os.getenv("DB_PATH", "/data/attendance.db")

# SQLAlchemy setup
Base = declarative_base()

# Async engine for main application
async_engine = create_async_engine(
    f"sqlite+aiosqlite:///{DB_PATH}",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
    echo=False
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Sync engine for migrations
sync_engine = create_engine(
    f"sqlite:///{DB_PATH}",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
    echo=False
)

SessionLocal = sessionmaker(bind=sync_engine)

async def init_database():
    """Initialize database with schema"""
    # Read schema file
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, 'r') as f:
        schema_sql = f.read()
    
    # Execute schema using sync connection - split into individual statements
    with sync_engine.connect() as conn:
        # Split SQL into individual statements
        statements = []
        current_statement = ""
        
        # Split by semicolon but preserve semicolons within statements
        lines = schema_sql.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('--') or line == '':
                continue  # Skip comments and empty lines
            current_statement += line + ' '
            if ';' in line:
                # Found end of statement
                statement = current_statement.strip()
                if statement:
                    statements.append(statement)
                current_statement = ""
        
        # Execute each statement individually
        for statement in statements:
            if statement.strip():  # Skip empty statements
                conn.execute(text(statement))
        
        conn.commit()
    
    # Seed initial data if needed
    await seed_initial_data()

async def seed_initial_data():
    """Seed initial data for MVP"""
    async with AsyncSessionLocal() as session:
        # Check if programs exist
        result = await session.execute(text("SELECT COUNT(*) FROM programs"))
        program_count = result.scalar()
        
        if program_count == 0:
            # Insert default programs
            programs = [
                ("Nursery", 0, 2),
                ("Toddlers", 2, 4),
                ("Preschool", 4, 6),
                ("Elementary", 6, 12)
            ]
            
            for name, min_age, max_age in programs:
                await session.execute(
                    text("INSERT INTO programs (name, min_age, max_age) VALUES (:name, :min_age, :max_age)"),
                    {"name": name, "min_age": min_age, "max_age": max_age}
                )
        
        # Check if admin volunteer exists
        result = await session.execute(text("SELECT COUNT(*) FROM volunteers WHERE username = 'admin'"))
        admin_count = result.scalar()
        
        if admin_count == 0:
            # Create admin volunteer (password: admin123)
            import bcrypt
            password_hash = bcrypt.hashpw("admin123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            await session.execute(
                text("""
                    INSERT INTO volunteers (username, password_hash, first_name, last_name, role) 
                    VALUES (:username, :password_hash, :first_name, :last_name, :role)
                """),
                {
                    "username": "admin",
                    "password_hash": password_hash,
                    "first_name": "Admin",
                    "last_name": "User",
                    "role": "admin"
                }
            )
        
        await session.commit()

async def get_db():
    """Get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

class Database:
    """Database helper class for common operations"""
    
    @staticmethod
    async def log_event(level: str, category: str, message: str, details: str = None, user_id: str = None, session_id: str = None):
        """Log an event to the logs table"""
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO logs (level, category, message, details, user_id, session_id)
                    VALUES (:level, :category, :message, :details, :user_id, :session_id)
                """),
                {
                    "level": level,
                    "category": category,
                    "message": message,
                    "details": details,
                    "user_id": user_id,
                    "session_id": session_id
                }
            )
            await db.commit()
    
    @staticmethod
    async def get_child_by_qr(qr_value: str) -> Optional[Dict[str, Any]]:
        """Get child information by QR code"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("""
                SELECT c.*, f.family_name, qc.qr_value
                FROM children c
                JOIN families f ON c.family_id = f.id
                JOIN qr_codes qc ON c.id = qc.child_id
                WHERE qc.qr_value = :qr_value AND qc.active = TRUE AND c.active = TRUE
            """), {"qr_value": qr_value})
            
            row = result.fetchone()
            if row:
                columns = result.keys()
                return dict(zip(columns, row))
            return None
    
    @staticmethod
    async def create_checkin_session(session_id: str, child_id: int, program_id: int, station_id: str, device_id: str) -> bool:
        """Create a check-in session"""
        async with AsyncSessionLocal() as db:
            expires_at = datetime.now() + timedelta(minutes=5)
            
            await db.execute(
                text("""
                    INSERT INTO checkin_sessions (session_id, child_id, program_id, station_id, device_id, expires_at)
                    VALUES (:session_id, :child_id, :program_id, :station_id, :device_id, :expires_at)
                """),
                {
                    "session_id": session_id,
                    "child_id": child_id,
                    "program_id": program_id,
                    "station_id": station_id,
                    "device_id": device_id,
                    "expires_at": expires_at
                }
            )
            await db.commit()
            return True
    
    @staticmethod
    async def get_checkin_session(session_id: str) -> Optional[Dict[str, Any]]:
        """Get check-in session by ID"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("""
                SELECT cs.*, c.first_name, c.last_name, p.name as program_name
                FROM checkin_sessions cs
                LEFT JOIN children c ON cs.child_id = c.id
                LEFT JOIN programs p ON cs.program_id = p.id
                WHERE cs.session_id = :session_id AND cs.expires_at > datetime('now') AND cs.confirmed = FALSE
            """), {"session_id": session_id})
            
            row = result.fetchone()
            if row:
                columns = result.keys()
                return dict(zip(columns, row))
            return None
    
    @staticmethod
    async def confirm_checkin(session_id: str, station_id: str, created_by: str) -> bool:
        """Confirm check-in and create attendance record"""
        async with AsyncSessionLocal() as db:
            # Get session details
            session_result = await db.execute(text("""
                SELECT child_id, program_id, station_id, device_id
                FROM checkin_sessions
                WHERE session_id = :session_id AND confirmed = FALSE
            """), {"session_id": session_id})
            
            session_row = session_result.fetchone()
            if not session_row:
                return False
            
            child_id, program_id, original_station_id, device_id = session_row
            
            # Create attendance record
            await db.execute(
                text("""
                    INSERT INTO attendance (child_id, program_id, station_id, checkin_time, created_by)
                    VALUES (:child_id, :program_id, :station_id, datetime('now'), :created_by)
                """),
                {
                    "child_id": child_id,
                    "program_id": program_id,
                    "station_id": station_id,
                    "created_by": created_by
                }
            )
            
            # Mark session as confirmed
            await db.execute(
                text("UPDATE checkin_sessions SET confirmed = TRUE WHERE session_id = :session_id"),
                {"session_id": session_id}
            )
            
            await db.commit()
            return True
    
    @staticmethod
    async def get_programs() -> List[Dict[str, Any]]:
        """Get all active programs"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT * FROM programs WHERE active = TRUE ORDER BY min_age"))
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
    
    @staticmethod
    async def register_new_child(child_data: Dict[str, Any], family_data: Dict[str, Any], parent_data: Dict[str, Any], qr_value: str) -> int:
        """Register a new child and family"""
        async with AsyncSessionLocal() as db:
            # Create family
            await db.execute(
                text("INSERT INTO families (family_name) VALUES (:family_name)"),
                {"family_name": family_data["family_name"]}
            )
            family_id = (await db.execute(text("SELECT last_insert_rowid()"))).scalar()
            
            # Create parent
            await db.execute(
                text("""
                    INSERT INTO parents (family_id, first_name, last_name, phone, email, relationship)
                    VALUES (:family_id, :first_name, :last_name, :phone, :email, :relationship)
                """),
                {
                    "family_id": family_id,
                    "first_name": parent_data["first_name"],
                    "last_name": parent_data["last_name"],
                    "phone": parent_data["phone"],
                    "email": parent_data.get("email"),
                    "relationship": parent_data["relationship"]
                }
            )
            
            # Create child
            await db.execute(
                text("""
                    INSERT INTO children (family_id, first_name, last_name, birth_date, allergies, medications, special_notes, medical_notes)
                    VALUES (:family_id, :first_name, :last_name, :birth_date, :allergies, :medications, :special_notes, :medical_notes)
                """),
                {
                    "family_id": family_id,
                    "first_name": child_data["first_name"],
                    "last_name": child_data["last_name"],
                    "birth_date": child_data["birth_date"],
                    "allergies": child_data.get("allergies"),
                    "medications": child_data.get("medications"),
                    "special_notes": child_data.get("special_notes"),
                    "medical_notes": child_data.get("medical_notes")
                }
            )
            child_id = (await db.execute(text("SELECT last_insert_rowid()"))).scalar()
            
            # Create QR code
            await db.execute(
                text("INSERT INTO qr_codes (child_id, qr_value) VALUES (:child_id, :qr_value)"),
                {"child_id": child_id, "qr_value": qr_value}
            )
            
            await db.commit()
            return child_id
