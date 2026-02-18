import pytest
import asyncio
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import tempfile
import os

# Import the main application
import sys
sys.path.append('..')
from main import app
from database import init_database, Database

# Create test database
@pytest.fixture(scope="function")
def test_db():
    """Create a temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
        db_path = tmp_file.name
    
    # Override database path for testing
    original_db_path = os.getenv("DB_PATH")
    os.environ["DB_PATH"] = db_path
    
    # Initialize test database
    async_engine = create_engine(f"sqlite:///{db_path}")
    
    # Create schema
    with open('../schema.sql', 'r') as f:
        schema_sql = f.read()
    
    with async_engine.connect() as conn:
        conn.execute(text(schema_sql))
        conn.commit()
    
    # Seed test data
    with async_engine.connect() as conn:
        # Add test programs
        conn.execute(text("""
            INSERT INTO programs (name, min_age, max_age) VALUES 
            ('Nursery', 0, 2), ('Toddlers', 2, 4)
        """))
        
        # Add test family
        conn.execute(text("""
            INSERT INTO families (family_name) VALUES ('Test Family')
        """))
        family_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
        
        # Add test child
        conn.execute(text("""
            INSERT INTO children (family_id, first_name, last_name, birth_date) 
            VALUES (:family_id, 'Test', 'Child', '2020-01-01')
        """), {"family_id": family_id})
        child_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
        
        # Add test QR code
        conn.execute(text("""
            INSERT INTO qr_codes (child_id, qr_value) 
            VALUES (:child_id, 'TEST-QR-123')
        """), {"child_id": child_id})
        
        conn.commit()
    
    yield db_path
    
    # Cleanup
    os.unlink(db_path)
    if original_db_path:
        os.environ["DB_PATH"] = original_db_path
    else:
        os.environ.pop("DB_PATH", None)

@pytest.fixture
def client(test_db):
    """Create test client"""
    with TestClient(app) as test_client:
        yield test_client

class TestHealthEndpoint:
    """Test health check endpoint"""
    
    def test_health_check(self, client):
        """Test health endpoint returns correct status"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

class TestProgramsEndpoint:
    """Test programs endpoint"""
    
    def test_get_programs(self, client):
        """Test getting all programs"""
        response = client.get("/api/programs")
        assert response.status_code == 200
        programs = response.json()
        assert len(programs) >= 2  # At least Nursery and Toddlers
        
        # Check program structure
        program = programs[0]
        assert "id" in program
        assert "name" in program
        assert "min_age" in program
        assert "max_age" in program

class TestScanEndpoint:
    """Test QR code scanning endpoint"""
    
    def test_scan_valid_qr(self, client):
        """Test scanning a valid QR code"""
        response = client.post("/api/scan", json={
            "qr_value": "TEST-QR-123",
            "station_id": "entrance-a",
            "device_id": "test-device"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "session_id" in data
        assert "child_info" in data
        assert "programs" in data
        assert data["child_info"]["first_name"] == "Test"
        assert data["child_info"]["last_name"] == "Child"
    
    def test_scan_invalid_qr(self, client):
        """Test scanning an invalid QR code"""
        response = client.post("/api/scan", json={
            "qr_value": "INVALID-QR",
            "station_id": "entrance-a",
            "device_id": "test-device"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "message" in data
    
    def test_scan_invalid_station(self, client):
        """Test scanning with invalid station ID"""
        response = client.post("/api/scan", json={
            "qr_value": "TEST-QR-123",
            "station_id": "invalid-station",
            "device_id": "test-device"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Invalid station ID" in data["message"]

class TestCheckinEndpoint:
    """Test check-in confirmation endpoint"""
    
    def test_checkin_valid_session(self, client):
        """Test confirming check-in with valid session"""
        # First scan to get session
        scan_response = client.post("/api/scan", json={
            "qr_value": "TEST-QR-123",
            "station_id": "entrance-a",
            "device_id": "test-device"
        })
        session_id = scan_response.json()["session_id"]
        
        # Then confirm check-in
        response = client.post("/api/checkin", json={
            "session_id": session_id,
            "station_id": "entrance-a",
            "device_id": "test-device",
            "created_by": "Test Volunteer"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Test Child" in data["message"]
    
    def test_checkin_invalid_session(self, client):
        """Test confirming check-in with invalid session"""
        response = client.post("/api/checkin", json={
            "session_id": "invalid-session",
            "station_id": "entrance-a",
            "device_id": "test-device",
            "created_by": "Test Volunteer"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "expired" in data["message"].lower()
    
    def test_checkin_invalid_station(self, client):
        """Test confirming check-in with invalid station"""
        response = client.post("/api/checkin", json={
            "session_id": "any-session",
            "station_id": "invalid-station",
            "device_id": "test-device",
            "created_by": "Test Volunteer"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Invalid station ID" in data["message"]

class TestRegisterEndpoint:
    """Test child registration endpoint"""
    
    def test_register_new_child(self, client):
        """Test registering a new child"""
        response = client.post("/api/register", json={
            "child": {
                "first_name": "New",
                "last_name": "Child",
                "birth_date": "2021-01-01",
                "allergies": None,
                "medications": None,
                "special_notes": None,
                "medical_notes": None
            },
            "family": {
                "family_name": "New Family"
            },
            "parent": {
                "first_name": "Parent",
                "last_name": "One",
                "phone": "555-123-4567",
                "email": "parent@example.com",
                "relationship": "mother"
            },
            "qr_value": "NEW-QR-456",
            "program_id": 1
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "child_id" in data
        assert "New Child" in data["message"]
    
    def test_register_missing_required_fields(self, client):
        """Test registration with missing required fields"""
        response = client.post("/api/register", json={
            "child": {
                "first_name": "New",
                # Missing last_name
            },
            "family": {
                "family_name": "New Family"
            },
            "parent": {
                "first_name": "Parent",
                "last_name": "One",
                "phone": "555-123-4567",
                "relationship": "mother"
            },
            "qr_value": "NEW-QR-456",
            "program_id": 1
        })
        # Should return 500 due to database constraint violation
        assert response.status_code == 500

class TestSessionEndpoint:
    """Test session information endpoint"""
    
    def test_get_valid_session(self, client):
        """Test getting valid session information"""
        # First create a session
        scan_response = client.post("/api/scan", json={
            "qr_value": "TEST-QR-123",
            "station_id": "entrance-a",
            "device_id": "test-device"
        })
        session_id = scan_response.json()["session_id"]
        
        # Then get session info
        response = client.get(f"/api/session/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "first_name" in data
        assert data["first_name"] == "Test"
    
    def test_get_invalid_session(self, client):
        """Test getting invalid session information"""
        response = client.get("/api/session/invalid-session")
        assert response.status_code == 404

class TestDatabaseIntegration:
    """Test database integration"""
    
    @pytest.mark.asyncio
    async def test_database_logging(self, test_db):
        """Test database logging functionality"""
        await Database.log_event("info", "test", "Test log message")
        
        # Verify log was created (this would require additional database query)
        # For now, just ensure no exception is raised
        assert True
    
    @pytest.mark.asyncio
    async def test_get_child_by_qr(self, test_db):
        """Test getting child by QR code"""
        child_info = await Database.get_child_by_qr("TEST-QR-123")
        assert child_info is not None
        assert child_info["first_name"] == "Test"
        assert child_info["last_name"] == "Child"
    
    @pytest.mark.asyncio
    async def test_get_child_by_invalid_qr(self, test_db):
        """Test getting child by invalid QR code"""
        child_info = await Database.get_child_by_qr("INVALID-QR")
        assert child_info is None

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
