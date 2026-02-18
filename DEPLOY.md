# 🚀 GitHub-Based Deployment Guide

## Prerequisites
- Docker Desktop installed on Windows Server 2022
- Internet connection for GitHub access

## Zero-File Deployment

### Step 1: Create Deployment Folder
Create a folder on your Windows Server:
```powershell
mkdir C:\KidsMinistryDeploy
cd C:\KidsMinistryDeploy
```

### Step 2: Create Docker Compose File
Create a new file called `docker-compose.yml` with this content:

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
      - ./static:/app/static
    environment:
      - DB_PATH=/data/attendance.db
      - STATION_TOKENS=entrance-a,entrance-b,checkout-a
      - WORKER_POLL_INTERVAL=2
      - SECRET_KEY=kids-ministry-default-secret-change-in-production
      - ADMIN_USERNAME=admin
      - ADMIN_PASSWORD=admin123
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    command: >
      sh -c "
        echo 'Starting Kids Ministry Check-in System...' &&
        python -c 'import asyncio; from database import init_database; asyncio.run(init_database())' &&
        echo 'Database initialized.' &&
        python seed_data.py &&
        echo 'Sample data created.' &&
        echo 'Starting web server...' &&
        uvicorn main:app --host 0.0.0.0 --port 8000
      "

  worker:
    build:
      context: .
      dockerfile: Dockerfile
    command: python worker.py
    volumes:
      - ./data:/data
      - ./whatsapp_session:/home/pi/.whatsapp_session
    environment:
      - DB_PATH=/data/attendance.db
      - PLAYWRIGHT_USER_DATA_DIR=/home/pi/.whatsapp_session
      - WORKER_POLL_INTERVAL=2
      - SECRET_KEY=kids-ministry-default-secret-change-in-production
    restart: unless-stopped
    depends_on:
      app:
        condition: service_healthy
```

### Step 3: Create Dockerfile
Create a new file called `Dockerfile` with this content:

```dockerfile
FROM python:3.11-slim

# Install system dependencies including git
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone the repository
RUN git clone https://github.com/ChiefMcGill/Attendance-Tracker-for-Kids-Ministry.git .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p /data /home/pi/.whatsapp_session

# Expose port
EXPOSE 8000

# Default command (overridden by docker-compose)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 4: Run Single Command
```powershell
docker-compose up --build
```

**That's it!** 🎉

The system will automatically:
- ✅ Clone the latest code from GitHub
- ✅ Build the Docker containers
- ✅ Initialize the database
- ✅ Create sample data
- ✅ Start the web server
- ✅ Start the background worker
- ✅ Run health checks

### Step 5: Access the System
Wait 2-3 minutes for initialization, then open:
- **Main Interface**: `http://localhost:8000`
- **Scanner**: `http://localhost:8000/scanner`
- **Registration**: `http://localhost:8000/register`
- **Health Check**: `http://localhost:8000/health`

### Step 6: Test with Sample QR Codes
Use these test QR codes:
- `KID-EMMA-JOHNSON-001`
- `KID-NOAH-JOHNSON-002`
- `KID-OLIVIA-SMITH-003`

---

## 📱 Access from Other Devices

Find your server IP:
```powershell
ipconfig
```

Then access from tablets/phones:
`http://[YOUR-SERVER-IP]:8000`

---

## 🔧 Management Commands

**Stop the system:**
```powershell
docker-compose down
```

**Update to latest version:**
```powershell
docker-compose down
docker rmi $(docker images -q)  # Remove old images
docker-compose up --build      # Pull latest from GitHub
```

**View logs:**
```powershell
docker-compose logs
```

**Check status:**
```powershell
docker-compose ps
```

---

## 🛠️ Troubleshooting

**If port 8000 is already in use:**
```powershell
netstat -ano | findstr :8000
# Kill the process using the port
taskkill /PID [PROCESS-ID] /F
```

**If GitHub clone fails:**
```powershell
# Check internet connection
ping github.com

# Try manual clone
git clone https://github.com/ChiefMcGill/Attendance-Tracker-for-Kids-Ministry.git
```

**If containers won't start:**
```powershell
# Clean rebuild
docker-compose down
docker system prune -f
docker-compose up --build
```

**If you need to reset everything:**
```powershell
docker-compose down -v
Remove-Item .\data\* -Recurse -Force
docker-compose up --build
```

---

## 📊 What's Included

The automated setup creates:
- 8 sample children with families
- 4 age-based programs (Nursery, Toddlers, Preschool, Elementary)
- Sample attendance records
- Admin user: `admin` / `admin123`

---

## 🔐 Default Configuration

- **Station IDs**: `entrance-a`, `entrance-b`, `checkout-a`
- **Database**: SQLite in `./data/attendance.db`
- **Port**: 8000
- **Admin**: admin/admin123

---

## 🎯 Always Up-to-Date

Since this pulls directly from GitHub, you'll always get the latest version with bug fixes and new features!

---

**That's it! Your Kids Ministry Check-in system is now running from GitHub with a single command!** 🎉
