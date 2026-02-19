-- Kids Ministry Attendance Tracker Database Schema
-- SQLite database schema for Phase 1 MVP

-- Families table
CREATE TABLE IF NOT EXISTS families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Parents/Guardians table
CREATE TABLE IF NOT EXISTS parents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT,
    relationship TEXT NOT NULL, -- 'mother', 'father', 'guardian', etc.
    whatsapp_opt_in BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (family_id) REFERENCES families(id)
);

-- Children table
CREATE TABLE IF NOT EXISTS children (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    birth_date DATE NOT NULL,
    allergies TEXT, -- JSON array of allergies
    medications TEXT, -- JSON array of medications
    special_notes TEXT,
    medical_notes TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (family_id) REFERENCES families(id)
);

-- QR codes table (links children to their QR codes)
CREATE TABLE IF NOT EXISTS qr_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER NOT NULL,
    qr_value TEXT NOT NULL UNIQUE, -- The actual QR code value
    issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP,
    active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (child_id) REFERENCES children(id)
);

-- Programs table (Sunday School, Nursery, etc.)
CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    min_age INTEGER,
    max_age INTEGER,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Attendance sessions table (check-in/check-out events)
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER NOT NULL,
    program_id INTEGER NOT NULL,
    station_id TEXT NOT NULL, -- Which station performed the check-in
    checkin_time TIMESTAMP NOT NULL,
    checkout_time TIMESTAMP,
    created_by TEXT, -- Volunteer who checked them in
    checked_out_by TEXT, -- Volunteer who checked them out
    notes TEXT,
    FOREIGN KEY (child_id) REFERENCES children(id),
    FOREIGN KEY (program_id) REFERENCES programs(id)
);

-- Check-in sessions (temporary sessions for scan-to-confirm flow)
CREATE TABLE IF NOT EXISTS checkin_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    child_id INTEGER,
    program_id INTEGER,
    station_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL, -- 5 minutes from scan
    confirmed BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (child_id) REFERENCES children(id),
    FOREIGN KEY (program_id) REFERENCES programs(id)
);

-- Volunteers table
CREATE TABLE IF NOT EXISTS volunteers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL, -- bcrypt hash
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'volunteer', -- 'volunteer', 'manager', 'admin'
    totp_secret TEXT, -- For 2FA
    enabled_2fa BOOLEAN DEFAULT FALSE,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Message queue table (for WhatsApp notifications)
CREATE TABLE IF NOT EXISTS message_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    message_type TEXT NOT NULL, -- 'checkin', 'checkout', 'request_info'
    message_content TEXT NOT NULL,
    phone TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- 'pending', 'sent', 'failed', 'retry'
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    scheduled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES parents(id),
    FOREIGN KEY (child_id) REFERENCES children(id)
);

-- Logs table (for audit trail and debugging)
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level TEXT NOT NULL, -- 'info', 'warning', 'error', 'debug'
    category TEXT NOT NULL, -- 'api', 'database', 'whatsapp', 'auth', etc.
    message TEXT NOT NULL,
    details TEXT, -- JSON string with additional context
    user_id TEXT, -- Volunteer ID if applicable
    session_id TEXT -- Check-in session ID if applicable
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_qr_codes_child_id ON qr_codes(child_id);
CREATE INDEX IF NOT EXISTS idx_qr_codes_qr_value ON qr_codes(qr_value);
CREATE INDEX IF NOT EXISTS idx_qr_codes_active ON qr_codes(active);

CREATE INDEX IF NOT EXISTS idx_attendance_child_id ON attendance(child_id);
CREATE INDEX IF NOT EXISTS idx_attendance_program_id ON attendance(program_id);
CREATE INDEX IF NOT EXISTS idx_attendance_checkin_time ON attendance(checkin_time);
CREATE INDEX IF NOT EXISTS idx_attendance_checkout_time ON attendance(checkout_time);

CREATE INDEX IF NOT EXISTS idx_checkin_sessions_session_id ON checkin_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_checkin_sessions_expires_at ON checkin_sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_children_family_id ON children(family_id);
CREATE INDEX IF NOT EXISTS idx_children_active ON children(active);

CREATE INDEX IF NOT EXISTS idx_parents_family_id ON parents(family_id);
CREATE INDEX IF NOT EXISTS idx_parents_whatsapp_opt_in ON parents(whatsapp_opt_in);

CREATE INDEX IF NOT EXISTS idx_message_queue_status ON message_queue(status);
CREATE INDEX IF NOT EXISTS idx_message_queue_scheduled_at ON message_queue(scheduled_at);

CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_category ON logs(category);
