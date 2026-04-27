import sqlite3

from werkzeug.security import generate_password_hash

DATABASE = 'ebyte.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database with all required tables and columns for cross-device sync"""
    db = get_db()

    # 1. Create users table (if not exists)
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            full_name TEXT,
            password TEXT NOT NULL,
            gender TEXT,
            contact TEXT,
            bio TEXT,
            avatar TEXT,
            cover_image TEXT,
            bg_type TEXT DEFAULT 'default',
            bg_image TEXT,
            active_hours TEXT,
            security_q1 TEXT,
            security_a1 TEXT,
            security_q2 TEXT,
            security_a2 TEXT,
            is_admin INTEGER DEFAULT 0,
            is_frozen INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,  
            frozen_until TIMESTAMP,
            freeze_reason TEXT,
            rating TEXT DEFAULT '—',
            trust_score INTEGER DEFAULT 85,
            response_rate INTEGER DEFAULT 98,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. Create notifications table (if not exists)
    db.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    db.commit()

    # ========== 3. Database Migration: Add missing columns ==========
    cursor = db.execute("PRAGMA table_info(users)")
    existing_columns = [col[1] for col in cursor.fetchall()]

    # All required columns for cross-device synchronization
    required_columns = {
        'cover_image': 'TEXT',         
        'avatar': 'TEXT',          
        'bg_type': "TEXT DEFAULT 'default'",
        'bg_image': 'TEXT',             
        'trust_score': "INTEGER DEFAULT 85",
        'response_rate': "INTEGER DEFAULT 98",
        'rating': "TEXT DEFAULT '—'"
    }

    # Add missing columns one by one
    for col_name, col_def in required_columns.items():
        if col_name not in existing_columns:
            try:
                db.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_def}')
                print(f"✅ Added missing column: {col_name}")
            except Exception as e:
                print(f"⚠️ Could not add column {col_name}: {e}")

    db.commit()

    # 4. Create default admin user (if not exists)
    admin_email = 'admin@student.mmu.edu.my'
    admin_password = generate_password_hash('Admin123!')
    
    existing_admin = db.execute(
        'SELECT * FROM users WHERE email = ?', (admin_email,)
    ).fetchone()
    
    if not existing_admin:
        db.execute('''
            INSERT INTO users (student_id, email, username, password, is_admin)
            VALUES (?, ?, ?, ?, ?)
        ''', ('ADMIN001', admin_email, 'Administrator', admin_password, 1))
        db.commit()
        print("✅ Default admin created: admin@student.mmu.edu.my / Admin123!")
    else:
        print("✅ Admin user already exists")
    
    db.close()
    print("✅ Database ready with all required tables and columns for cross-device sync.")


def init_products():
    """Initialize products table"""
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT,
            condition TEXT,
            category TEXT,
            images TEXT, 
            status TEXT DEFAULT 'pending',
            reject_reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (seller_id) REFERENCES users(id)
        )
    ''')

    # Check and add missing columns
    cursor = db.execute("PRAGMA table_info(products)")
    existing_columns = [col[1] for col in cursor.fetchall()]

    if 'status' not in existing_columns:
        try:
            db.execute("ALTER TABLE products ADD COLUMN status TEXT DEFAULT 'pending'")
            print("✅ Added missing column: status")
        except Exception as e:
            print(f"⚠️ Could not add column status: {e}")

    if 'reject_reason' not in existing_columns:
        try:
            db.execute("ALTER TABLE products ADD COLUMN reject_reason TEXT DEFAULT ''")
            print("✅ Added missing column: reject_reason")
        except Exception as e:
            print(f"⚠️ Could not add column reject_reason: {e}")

    db.commit()
    db.close()
    print("✅ Database ready with products table.")
