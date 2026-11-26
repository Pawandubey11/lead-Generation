# database/auth_db.py
import sqlite3
import os
import hashlib
import binascii
from datetime import datetime
import secrets
import hmac

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_database.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")  # 64MB cache
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)").fetchall()}
    if "password_salt" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN password_salt TEXT")
    if "password_iterations" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN password_iterations INTEGER")
    
    # 2. User Settings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER UNIQUE,
        sender_name TEXT,
        sender_title TEXT,
        sender_company TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    # 3. User Services Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_services (
        user_id INTEGER,
        service_key TEXT,
        service_name TEXT,
        service_description TEXT,
        custom_pain_point TEXT,
        PRIMARY KEY(user_id, service_key),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 4. CRM Lead Pipeline Table (Safe idempotent migration)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lead_crm (
        lead_key TEXT PRIMARY KEY,
        business_name TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT 'New',
        owner TEXT DEFAULT '',
        follow_up_date TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        last_contacted_at TEXT DEFAULT '',
        estimated_value REAL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    # 5. CRM Activity & Status History Log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lead_activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_key TEXT NOT NULL,
        business_name TEXT NOT NULL,
        activity_type TEXT NOT NULL,
        old_value TEXT DEFAULT '',
        new_value TEXT DEFAULT '',
        note TEXT DEFAULT '',
        actor TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_lead_activities_key ON lead_activities(lead_key)")

    # 6. Persistent Website Audit & Opportunity Score Cache
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lead_audits (
        lead_key TEXT PRIMARY KEY,
        business_name TEXT NOT NULL,
        audit_json TEXT NOT NULL,
        opportunity_json TEXT NOT NULL,
        mx_json TEXT DEFAULT '{}',
        updated_at TEXT NOT NULL
    )
    """)
    
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    """Backward-compatible wrapper for legacy static-salt hashes."""
    salt = b"SystemaOpsLeadPulseSaltSecured"
    pwdhash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return binascii.hexlify(pwdhash).decode("ascii")


def hash_password_secure(password: str) -> tuple[str, str, int]:
    iterations = 310000
    salt = secrets.token_hex(16)
    pwdhash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    )
    return binascii.hexlify(pwdhash).decode("ascii"), salt, iterations

def create_user(email: str, password: str) -> int:
    """Create a new user and populate default settings/services."""
    email = email.strip().lower()
    pwd_hash, password_salt, password_iterations = hash_password_secure(password)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (email, password_hash, password_salt, password_iterations, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email, pwd_hash, password_salt, password_iterations, now)
        )
        user_id = cursor.lastrowid
        
        # Populate Default Settings
        cursor.execute(
            "INSERT INTO user_settings (user_id, sender_name, sender_title, sender_company) VALUES (?, ?, ?, ?)",
            (user_id, "Your Name", "Founder", "Your Company")
        )
        
        # Populate Default Services
        default_services = [
            ("opendesk", "OpenDesk Helpdesk", "Enterprise-grade ticketing support, installation, and migration.", "ticket backlog congestion and SLA compliance issues"),
            ("odoo", "Odoo ERP", "All-in-one suite covering invoicing, timesheets, CRM, and sales inventory.", "unifying operations, tracking rosters, and inventory sync"),
            ("claude", "Claude Integration", "Anthropic Claude model workflow integration, prompt tuning, and secure sandboxes.", "automating administrative reporting and data processing"),
            ("ai", "AI Agents & Bots", "Tailored chatbot virtual assistants for websites, WhatsApp, and auto-scheduling.", "booking appointments, answering client FAQs 24/7, and capturing cold traffic"),
            ("general", "Systema Ops Portfolio", "End-to-end custom automation solutions, digital transformation, and ERP setups.", "scaling sales processes, organizing client records, and automating manual work")
        ]
        
        for key, name, desc, pain in default_services:
            cursor.execute(
                "INSERT INTO user_services (user_id, service_key, service_name, service_description, custom_pain_point) VALUES (?, ?, ?, ?, ?)",
                (user_id, key, name, desc, pain)
            )
            
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        return -1
    finally:
        conn.close()

def verify_user(email: str, password: str):
    """Verify email & password, returning user info if correct."""
    email = email.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, email, password_hash, password_salt, password_iterations "
        "FROM users WHERE email = ?",
        (email,)
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    record = dict(row)
    password_salt = record.get("password_salt")
    password_iterations = record.get("password_iterations")

    if password_salt and password_iterations:
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            password_salt.encode("ascii"),
            int(password_iterations),
        )
        candidate_hash = binascii.hexlify(candidate).decode("ascii")
        matched = hmac.compare_digest(candidate_hash, record["password_hash"])
    else:
        matched = hmac.compare_digest(hash_password(password), record["password_hash"])

    if matched and not password_salt:
        new_hash, new_salt, new_iterations = hash_password_secure(password)
        cursor.execute(
            "UPDATE users SET password_hash = ?, password_salt = ?, password_iterations = ? "
            "WHERE id = ?",
            (new_hash, new_salt, new_iterations, record["id"]),
        )
        conn.commit()

    conn.close()
    return {"id": record["id"], "email": record["email"]} if matched else None

def get_user_settings(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_user_settings(user_id: int, sender_name: str, sender_title: str, sender_company: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE user_settings 
        SET sender_name = ?, sender_title = ?, sender_company = ?
        WHERE user_id = ?
    """, (sender_name, sender_title, sender_company, user_id))
    conn.commit()
    conn.close()

def get_user_services(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_services WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_user_service(user_id: int, service_key: str, service_name: str, service_description: str, custom_pain_point: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO user_services (user_id, service_key, service_name, service_description, custom_pain_point)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, service_key, service_name, service_description, custom_pain_point))
    conn.commit()
    conn.close()

# Initialize database tables on load
init_db()
