# Kids Ministry Check-in System - Phase 1 MVP

A QR code-based check-in system for children's ministry built with FastAPI and SQLite.

## Features (Phase 1 MVP)

- **QR Code Scanning**: Tablet-based QR code scanning using html5-qrcode
- **Child Registration**: On-site registration for new children and families
- **Check-in Confirmation**: Volunteer confirmation with program selection
- **Database Storage**: SQLite database with complete schema
- **Logging System**: Comprehensive audit trail
- **Docker Deployment**: Ready-to-deploy containerized application

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A tablet or device with camera for QR scanning

### Installation

1. Clone the repository
2. Copy environment file:
   ```bash
   cp .env.example .env
   ```
3. Start the application:
   ```bash
   docker-compose up --build
   ```

4. Access the application at `http://localhost:8000`

## Configuration

### Environment Variables

Edit `.env` file to configure:

- `DB_PATH`: Path to SQLite database (default: `/data/attendance.db`)
- `STATION_TOKENS`: Comma-separated list of valid station IDs
- `WORKER_POLL_INTERVAL`: Message worker poll interval in seconds
- `SECRET_KEY`: JWT secret key for authentication
- `ADMIN_USERNAME`/`ADMIN_PASSWORD`: Default admin credentials

### Station Configuration

Default stations: `entrance-a,entrance-b,checkout-a`

Update `STATION_TOKENS` in your `.env` file to match your physical stations.

## API Endpoints

### Core Endpoints

- `POST /api/scan` - Scan QR code and create session
- `POST /api/checkin` - Confirm check-in and create attendance record
- `POST /api/register` - Register new child and family
- `GET /api/programs` - Get available programs
- `GET /api/session/{session_id}` - Get session information

### Utility Endpoints

- `GET /health` - Health check
- `GET /` - Scanner page
- `GET /scanner` - Scanner page
- `GET /confirm` - Confirmation page
- `GET /register` - Registration page

## Testing

### Unit Tests

Run the test suite:

```bash
# Install test dependencies
pip install -r test_requirements.txt

# Run tests
pytest tests/ -v
```

### Manual Testing Flow

1. **Register a Test Child**
   - Navigate to `http://localhost:8000/register`
   - Fill in family, parent, and child information
   - Generate or enter a QR code value
   - Submit registration

2. **Test QR Scanning**
   - Navigate to `http://localhost:8000/scanner`
   - Use the QR code from step 1 (or a test QR code)
   - Verify child information appears

3. **Test Check-in Confirmation**
   - After scanning, you'll be redirected to confirmation page
   - Select appropriate program
   - Enter volunteer name
   - Confirm check-in

4. **Verify Database Records**
   - Check that attendance records are created
   - Verify logs are being written

## Sample Data

### Test QR Codes

The system includes sample data with test QR codes:

- `TEST-QR-123` - Test Child from Test Family
- Create additional QR codes through the registration form

### Default Programs

- Nursery (Ages 0-2)
- Toddlers (Ages 2-4)
- Preschool (Ages 4-6)
- Elementary (Ages 6-12)

### Default Admin User

- Username: `admin`
- Password: `admin123`

## Database Schema

The system uses SQLite with the following main tables:

- `families` - Family information
- `parents` - Parent/guardian details
- `children` - Child records and medical info
- `qr_codes` - QR code to child mappings
- `programs` - Available programs/age groups
- `attendance` - Check-in/check-out records
- `checkin_sessions` - Temporary scan sessions
- `volunteers` - Volunteer accounts
- `message_queue` - WhatsApp message queue (Phase 2)
- `logs` - System audit logs

See `schema.sql` for complete schema definition.

## Development

### Project Structure

```
├── main.py              # FastAPI application
├── database.py          # Database operations
├── models.py            # Pydantic models
├── worker.py            # WhatsApp worker (placeholder)
├── schema.sql           # Database schema
├── requirements.txt     # Python dependencies
├── docker-compose.yml   # Docker configuration
├── Dockerfile          # Container definition
├── templates/          # HTML templates
│   ├── scanner.html
│   ├── confirm.html
│   └── register.html
├── static/             # Static files
├── tests/              # Unit tests
└── data/               # Database storage (mounted volume)
```

### Adding New Features

1. Update database schema in `schema.sql`
2. Add models in `models.py`
3. Implement database operations in `database.py`
4. Add API endpoints in `main.py`
5. Update UI templates as needed
6. Add corresponding tests

## Deployment

### Docker Production Deployment

1. Set production environment variables
2. Build and deploy:
   ```bash
   docker-compose -f docker-compose.yml up -d
   ```

### Database Backups

The SQLite database is stored in the mounted `./data` volume. Create regular backups:

```bash
# Backup database
cp data/attendance.db backups/attendance_$(date +%Y%m%d_%H%M%S).db

# Automated backup script example
#!/bin/bash
BACKUP_DIR="./backups"
mkdir -p $BACKUP_DIR
cp data/attendance.db "$BACKUP_DIR/attendance_$(date +%Y%m%d_%H%M%S).db"
find $BACKUP_DIR -name "*.db" -mtime +7 -delete
```

## Security Considerations

- QR codes contain unique identifiers but no personal information
- Station tokens validate check-in station authenticity
- Volunteer passwords are bcrypt hashed
- Medical information is protected by role-based access (Phase 2)
- All data stored locally on Pi-400 (no cloud exposure)

## Troubleshooting

### Common Issues

1. **QR Code Not Found**
   - Verify QR code exists in database
   - Check QR code is active (not revoked)
   - Ensure child record is active

2. **Station Validation Failed**
   - Verify station ID is in `STATION_TOKENS`
   - Check environment variables are loaded

3. **Database Connection Issues**
   - Ensure `./data` directory exists and is writable
   - Check Docker volume mounting

4. **Camera Not Working**
   - Ensure browser has camera permissions
   - Use HTTPS in production for camera access
   - Test with different browsers

### Logs

Check application logs:

```bash
docker-compose logs app
docker-compose logs worker
```

Database logs are stored in the `logs` table and can be queried directly.

## Phase 2 Roadmap

The next phase will include:

- WhatsApp integration via Playwright
- Parent notifications
- Opt-in management
- Admin dashboard for volunteers
- Attendance analytics
- Label printing integration

## Support

For issues and questions:

1. Check this README and troubleshooting section
2. Review the database schema in `schema.sql`
3. Check application logs
4. Run unit tests to verify functionality

## License

This project is part of the Solid Ground Church Kids Ministry attendance system.
