# 🚀 One-Command Deployment Guide

## Prerequisites
- Docker Desktop installed on Windows Server 2022
- All project files copied to server

## Single Command Deployment

### Step 1: Copy Files
Copy the entire project folder to your Windows Server:
```
C:\KidsMinistryCheckin\
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── main.py
├── database.py
├── models.py
├── worker.py
├── schema.sql
├── seed_data.py
├── templates\
└── static\
```

### Step 2: Run Single Command
Open PowerShell as Administrator and run:
```powershell
cd C:\KidsMinistryCheckin
docker-compose up --build
```

**That's it!** 🎉

The system will automatically:
- ✅ Build the Docker containers
- ✅ Initialize the database
- ✅ Create sample data
- ✅ Start the web server
- ✅ Start the background worker
- ✅ Run health checks

### Step 3: Access the System
Wait 2-3 minutes for initialization, then open:
- **Main Interface**: `http://localhost:8000`
- **Scanner**: `http://localhost:8000/scanner`
- **Registration**: `http://localhost:8000/register`
- **Health Check**: `http://localhost:8000/health`

### Step 4: Test with Sample QR Codes
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

**Start again:**
```powershell
docker-compose up -d
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

## 🎯 Ready for Production

For production use, consider:
1. Change default passwords in docker-compose.yml
2. Set up HTTPS/SSL
3. Configure regular database backups
4. Monitor container health

---

**That's it! Your Kids Ministry Check-in system is now running with a single command!** 🎉
