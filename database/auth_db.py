# database/auth_db.py
import sqlite3
import os
import hashlib
import binascii
from datetime import datetime

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
    
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    """Hash a password using PBKDF2 HMAC SHA256 with a static salt."""
    salt = b"SystemaOpsLeadPulseSaltSecured"
    pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return binascii.hexlify(pwdhash).decode('ascii')

def create_user(email: str, password: str) -> int:
    """Create a new user and populate default settings/services."""
    email = email.strip().lower()
    pwd_hash = hash_password(password)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, pwd_hash, now)
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
    pwd_hash = hash_password(password)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, email FROM users WHERE email = ? AND password_hash = ?",
        (email, pwd_hash)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

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
