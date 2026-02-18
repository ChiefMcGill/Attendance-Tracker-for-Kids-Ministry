# Test Commands for Kids Ministry Check-in System

This document provides sample curl commands and testing procedures for the Phase 1 MVP.

## Quick Test Flow

### 1. Start the Application
```bash
docker-compose up --build
```

### 2. Create Sample Data
```bash
docker-compose exec app python seed_data.py
```

### 3. Test API Endpoints

#### Health Check
```bash
curl http://localhost:8000/health
```

#### Get Programs
```bash
curl http://localhost:8000/api/programs
```

#### Scan QR Code (Valid)
```bash
curl -X POST http://localhost:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{
    "qr_value": "KID-EMMA-JOHNSON-001",
    "station_id": "entrance-a",
    "device_id": "tablet-01"
  }'
```

#### Scan QR Code (Invalid)
```bash
curl -X POST http://localhost:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{
    "qr_value": "INVALID-QR-CODE",
    "station_id": "entrance-a",
    "device_id": "tablet-01"
  }'
```

#### Scan QR Code (Invalid Station)
```bash
curl -X POST http://localhost:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{
    "qr_value": "KID-EMMA-JOHNSON-001",
    "station_id": "invalid-station",
    "device_id": "tablet-01"
  }'
```

#### Confirm Check-in
```bash
# First get a session ID from scan, then:
curl -X POST http://localhost:8000/api/checkin \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "your-session-id-here",
    "station_id": "entrance-a",
    "device_id": "tablet-01",
    "created_by": "Test Volunteer"
  }'
```

#### Register New Child
```bash
curl -X POST http://localhost:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{
    "child": {
      "first_name": "Test",
      "last_name": "Child",
      "birth_date": "2020-01-01",
      "allergies": null,
      "medications": null,
      "special_notes": null,
      "medical_notes": null
    },
    "family": {
      "family_name": "Test Family"
    },
    "parent": {
      "first_name": "Parent",
      "last_name": "One",
      "phone": "555-123-4567",
      "email": "parent@example.com",
      "relationship": "mother"
    },
    "qr_value": "TEST-QR-NEW-001",
    "program_id": 1
  }'
```

#### Get Session Information
```bash
curl http://localhost:8000/api/session/your-session-id-here
```

## Sample QR Codes for Testing

After running `seed_data.py`, you'll have these test QR codes available:

- `KID-EMMA-JOHNSON-001` - Emma Johnson (Age 3, Allergies: Peanuts)
- `KID-NOAH-JOHNSON-002` - Noah Johnson (Age 5, No allergies)
- `KID-OLIVIA-SMITH-003` - Olivia Smith (Age 4, No allergies)
- `KID-LIAM-WILLIAMS-004` - Liam Williams (Age 6, Allergies: Dairy)
- `KID-SOPHIA-BROWN-005` - Sophia Brown (Age 2, No allergies)
- `KID-MASON-DAVIS-006` - Mason Davis (Age 5, No allergies)
- `KID-AVA-JOHNSON-007` - Ava Johnson (Age 4, No allergies)
- `KID-LUCAS-SMITH-008` - Lucas Smith (Age 3, No allergies)

## Manual Testing Steps

### 1. Test Registration Flow
1. Navigate to: http://localhost:8000/register
2. Fill in the registration form with sample data
3. Generate a QR code or enter a custom one
4. Submit the form
5. Verify success message

### 2. Test QR Scanning Flow
1. Navigate to: http://localhost:8000/scanner
2. Allow camera permissions when prompted
3. Use a test QR code (you can display one on another screen/device)
4. Verify child information appears
5. Should redirect to confirmation page

### 3. Test Check-in Confirmation Flow
1. After scanning, you'll be on the confirmation page
2. Verify child information is correct
3. Select an appropriate program
4. Enter volunteer name
5. Click "Check In"
6. Verify success message

### 4. Test Error Scenarios
- Invalid QR code
- Expired session
- Missing volunteer name
- Invalid station ID

## Database Verification

### Check Database Contents
```bash
docker-compose exec app sqlite3 /data/attendance.db

# Inside SQLite:
.tables
SELECT * FROM children LIMIT 5;
SELECT * FROM qr_codes LIMIT 5;
SELECT * FROM attendance LIMIT 5;
SELECT * FROM logs ORDER BY timestamp DESC LIMIT 10;
.exit
```

### Check Logs
```bash
docker-compose logs app
docker-compose logs worker
```

## Unit Tests

### Run All Tests
```bash
docker-compose exec app pip install -r test_requirements.txt
docker-compose exec app pytest tests/ -v
```

### Run Specific Test
```bash
docker-compose exec app pytest tests/test_api.py::TestScanEndpoint::test_scan_valid_qr -v
```

## Performance Testing

### Load Test with Multiple Requests
```bash
# Install Apache Bench if needed
# Then test scan endpoint:
ab -n 100 -c 10 -p test_payload.json -T application/json http://localhost:8000/api/scan

# test_payload.json content:
{
  "qr_value": "KID-EMMA-JOHNSON-001",
  "station_id": "entrance-a",
  "device_id": "tablet-01"
}
```

## Troubleshooting

### Common Issues and Solutions

1. **Camera not working**
   - Ensure browser has camera permissions
   - Try different browser (Chrome recommended)
   - Use HTTPS in production environments

2. **QR code not recognized**
   - Verify QR code exists in database
   - Check QR code format matches expected pattern
   - Ensure QR code is active (not revoked)

3. **Station validation failed**
   - Check station ID in request matches STATION_TOKENS
   - Verify environment variables are loaded correctly

4. **Database connection issues**
   - Ensure Docker volume is mounted correctly
   - Check permissions on data directory
   - Verify SQLite file exists and is writable

### Debug Mode

Enable debug logging by setting environment variable:
```bash
docker-compose -f docker-compose.yml -f docker-compose.debug.yml up
```

Or add to `.env`:
```
DEBUG=true
LOG_LEVEL=debug
```

## Test Data Cleanup

### Clear All Sample Data
```bash
docker-compose exec app python seed_data.py clear
```

### Reset Database Completely
```bash
docker-compose down
docker volume rm attendance-tracker-for-kids-ministry_data  # Adjust volume name
docker-compose up --build
```

## Production Readiness Checklist

- [ ] All tests passing
- [ ] Sample data created and tested
- [ ] QR codes printing correctly
- [ ] Camera permissions working on target tablets
- [ ] Station IDs configured for physical stations
- [ ] Database backups configured
- [ ] SSL/HTTPS configured for production
- [ ] Monitoring and logging verified
- [ ] Performance tested with expected load
