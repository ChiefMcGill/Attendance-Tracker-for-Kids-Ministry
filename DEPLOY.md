# 🚀 GitHub-Based Deployment Guide

## Prerequisites
- Docker Desktop installed on Windows Server 2022
- Internet connection for GitHub access

## 🔐 HTTPS Setup for Camera Access

**Required for camera permissions** - Modern browsers require HTTPS for `getUserMedia` API (QR code scanning).

### Step 1: Generate SSL Certificates

On your Windows Server, create certificates for `checkin.solidground.co.za`:

```powershell
# Create SSL directory
mkdir ssl

# Generate private key
openssl genrsa -out ssl/checkin.solidground.co.za.key 2048

# Generate certificate signing request
openssl req -new -key ssl/checkin.solidground.co.za.key -out ssl/checkin.solidground.co.za.csr -subj "/C=ZA/ST=Gauteng/L=JHB/O=Solid Ground Church/CN=checkin.solidground.co.za"

# Generate self-signed certificate (valid for 365 days)
openssl x509 -req -days 365 -in ssl/checkin.solidground.co.za.csr -signkey ssl/checkin.solidground.co.za.key -out ssl/checkin.solidground.co.za.crt

# Verify certificates were created
dir ssl\
```

### Step 2: DNS Configuration

Ensure your DNS is configured:
- **Domain**: `checkin.solidground.co.za`
- **IP Address**: `192.168.0.9` (your dedicated server IP)
- **Type**: A record

### Step 3: Create Deployment Files

Create these files in your deployment folder (`S:\Docker\KidsAttendanceTracker`):

**docker-compose.yml**:
```yaml
version: '3.8'

services:
  app:
    build: 
      context: .
      dockerfile: Dockerfile
    # Remove external port exposure - nginx handles this
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
    # Remove depends_on nginx - creates circular dependency

  nginx:
    build: 
      context: .
      dockerfile: Dockerfile.nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./ssl:/etc/ssl/certs:ro
      - ./ssl:/etc/ssl/private:ro
    restart: unless-stopped
    depends_on:
      - app

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

**nginx.conf**:
```nginx
# Nginx configuration for Kids Ministry Check-in System
# Reverse proxy with SSL termination

events {
    worker_connections 1024;
}

http {
    upstream app {
        server app:8000;
    }

    server {
        listen 80;
        server_name checkin.solidground.co.za;
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl http2;
        server_name checkin.solidground.co.za;

        # SSL configuration
        ssl_certificate /etc/ssl/certs/checkin.solidground.co.za.crt;
        ssl_certificate_key /etc/ssl/private/checkin.solidground.co.za.key;

        # SSL security settings
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
        ssl_prefer_server_ciphers off;

        # Security headers
        add_header X-Frame-Options DENY;
        add_header X-Content-Type-Options nosniff;
        add_header X-XSS-Protection "1; mode=block";

        # Proxy settings
        location / {
            proxy_pass http://app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # WebSocket support (for future real-time features)
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";

            # Timeout settings
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        # Static files
        location /static/ {
            proxy_pass http://app;
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
}
```

**Dockerfile**:
```dockerfile
FROM python:3.11-slim

# Install system dependencies including git
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone the repository (force rebuild - updated 2026-02-18)
RUN git clone --depth 1 https://github.com/ChiefMcGill/Attendance-Tracker-for-Kids-Ministry.git .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p /data /home/pi/.whatsapp_session

# Expose port
EXPOSE 8000

# Default command (overridden by docker-compose)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 4: Deploy with HTTPS

```powershell
# Navigate to your deployment folder
cd S:\Docker\KidsAttendanceTracker

# Ensure SSL certificates are in place
dir ssl\

# Deploy with HTTPS
docker-compose up --build
```

### Step 5: Trust the Certificate (First Time Setup)

Since we're using self-signed certificates, browsers will show a security warning. For local LAN access:

1. **Access the site**: `https://checkin.solidground.co.za`
2. **Click "Advanced"** or "Continue to site" 
3. **Add exception** for the certificate
4. **Camera permissions** will now work

### Step 6: Test Camera Access

- **Main Interface**: `https://checkin.solidground.co.za`
- **Scanner**: `https://checkin.solidground.co.za/scanner`
- **Registration**: `https://checkin.solidground.co.za/register`

The camera should now work without permission errors! 📷

---

## Zero-File Deployment (HTTP Only)

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
