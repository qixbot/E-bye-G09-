import os

import psycopg2

from psycopg2.extras import RealDictCursor

from werkzeug.security import generate_password_hash

# Read database URL from environment variable (safer)
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    # Fallback for local testing
    DATABASE_URL = "postgresql://postgres.pqfxyvjtwqpadddjkpdx:NQxhRLN6fmTQwHHc@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"

def get_db():
    """Return a PostgreSQL database connection with dictionary cursor"""
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = RealDictCursor 
    return conn

def init_db():
    """Initialize all tables in PostgreSQL"""
    conn = get_db()
    cur = conn.cursor()

    # Users table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            student_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            full_name TEXT,
            password TEXT NOT NULL,
            gender TEXT,
            contact TEXT,
            bio TEXT,
            avatar_blob BYTEA,
            cover_blob BYTEA,
            background_type TEXT DEFAULT 'default',
            background_value TEXT,
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
            freeze_count INTEGER DEFAULT 0,
            trust_score INTEGER DEFAULT 85,
            response_rate INTEGER DEFAULT 98,
            rating TEXT DEFAULT '--',
            remember_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Notifications table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Products table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            seller_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT,
            condition TEXT,
            category TEXT,
            images TEXT,
            images_blob TEXT,
            status TEXT DEFAULT 'pending',
            reject_reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Messages table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            sender_id INTEGER NOT NULL REFERENCES users(id),
            receiver_id INTEGER NOT NULL REFERENCES users(id),
            product_id INTEGER REFERENCES products(id),
            content TEXT,
            msg_type TEXT DEFAULT 'text',
            image TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Offers table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS offers (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id),
            buyer_id INTEGER NOT NULL REFERENCES users(id),
            offer_price REAL NOT NULL,
            original_price REAL,
            message TEXT,
            counter_price REAL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Announcements table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Reviews table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id),
            reviewer_id INTEGER NOT NULL REFERENCES users(id),
            reviewee_id INTEGER NOT NULL REFERENCES users(id),
            order_id INTEGER,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Orders table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            order_number TEXT UNIQUE NOT NULL,
            product_id INTEGER NOT NULL REFERENCES products(id),
            buyer_id INTEGER NOT NULL REFERENCES users(id),
            seller_id INTEGER NOT NULL REFERENCES users(id),
            offer_price REAL,
            quantity INTEGER DEFAULT 1,
            meeting_point TEXT,
            meeting_time TEXT,
            buyer_note TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    ''')

    conn.commit()

    # Create default admin user
    admin_email = 'admin@student.mmu.edu.my'
    admin_password = generate_password_hash('Admin123!')
    cur.execute("SELECT id FROM users WHERE email = %s", (admin_email,))
    if not cur.fetchone():
        cur.execute('''
            INSERT INTO users (student_id, email, username, password, is_admin)
            VALUES (%s, %s, %s, %s, %s)
        ''', ('ADMIN001', admin_email, 'Administrator', admin_password, 1))
        conn.commit()
        print("✅ Default admin created: admin@student.mmu.edu.my / Admin123!")
    else:
        print("✅ Admin user already exists")

    cur.close()
    conn.close()
    print("✅ All tables ready in PostgreSQL")

# Keep empty functions for compatibility with app.py calls
def init_products():
    pass

def init_messages():
    pass

def init_announcements():
    pass

def init_reviews():
    pass

def init_orders():
    pass