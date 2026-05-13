import os
import psycopg2
import time
import logging
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash
from contextlib import contextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    DATABASE_URL = "postgresql://postgres.pqfxyvjtwqpadddjkpdx:NQxhRLN6fmTQwHHc@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres"

# 全局连接池
_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        from psycopg2 import pool
        _pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL, connect_timeout=10, sslmode='require')
        print("✅ Connection pool ready (max 10 connections)")
    return _pool

def get_db():
    """获取数据库连接 - 从连接池获取"""
    try:
        conn = _get_pool().getconn()
        conn.cursor_factory = RealDictCursor
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

def return_db(conn):
    """归还连接到池子"""
    if conn and _pool:
        try:
            _get_pool().putconn(conn)
        except:
            pass

def get_db_with_retry(retries=3, delay=2):
    for i in range(retries):
        try:
            return get_db()
        except Exception as e:
            if i == retries - 1:
                raise
            logger.warning(f"Connection attempt {i+1} failed, retrying...")
            time.sleep(delay)
    return get_db()

def add_missing_notification_columns():
    conn = get_db_with_retry()
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'general'")
        print("✅ Added 'type' column to notifications")
    except Exception as e:
        print(f"Note: type column already exists or error: {e}")
    try:
        cur.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS related_id INTEGER")
        print("✅ Added 'related_id' column to notifications")
    except Exception as e:
        print(f"Note: related_id column already exists or error: {e}")
    try:
        cur.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS is_read INTEGER DEFAULT 0")
        print("✅ Added 'is_read' column to notifications")
    except Exception as e:
        print(f"Note: is_read column already exists or error: {e}")
    conn.commit()
    cur.close()
    return_db(conn)
    print("✅ Notification columns check completed")

def init_db():
    conn = None
    try:
        conn = get_db_with_retry()
        cur = conn.cursor()

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
                last_seen TIMESTAMP,
                last_read_ann TIMESTAMP,
                avg_service_rating DECIMAL(3,2) DEFAULT 0,
                avg_shipping_rating DECIMAL(3,2) DEFAULT 0,
                avg_quality_rating DECIMAL(3,2) DEFAULT 0,
                avg_overall_rating DECIMAL(3,2) DEFAULT 0,
                total_reviews INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                message TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                type TEXT DEFAULT 'general',
                related_id INTEGER,
                product_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

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

        cur.execute('''
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id),
                reviewer_id INTEGER NOT NULL REFERENCES users(id),
                reviewee_id INTEGER NOT NULL REFERENCES users(id),
                order_id INTEGER,
                rating_service INTEGER DEFAULT 0,
                rating_shipping INTEGER DEFAULT 0,
                rating_quality INTEGER DEFAULT 0,
                rating_overall INTEGER DEFAULT 0,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                reporter_id INTEGER NOT NULL REFERENCES users(id),
                reported_user_id INTEGER NOT NULL REFERENCES users(id),
                reason TEXT NOT NULL,
                details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

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

        try:
            cur.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS product_id INTEGER")
            print("✅ Added 'product_id' column to notifications")
        except Exception as e:
            print(f"Note: Could not add product_id column: {e}")

        try:
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS last_reminder_sent TIMESTAMP")
            print("✅ Added 'last_reminder_sent' column to orders")
        except Exception as e:
            print(f"Note: Could not add last_reminder_sent column: {e}")

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
        cur.close()
        return_db(conn)
        print("✅ All tables ready in PostgreSQL")
        
    except Exception as e:
        logger.error(f"init_db failed: {e}")
        if conn:
            return_db(conn)
        raise

def add_review_columns():
    conn = get_db_with_retry()
    cur = conn.cursor()
    
    user_columns = [
        ('avg_service_rating', 'DECIMAL(3,2) DEFAULT 0'),
        ('avg_shipping_rating', 'DECIMAL(3,2) DEFAULT 0'),
        ('avg_quality_rating', 'DECIMAL(3,2) DEFAULT 0'),
        ('avg_overall_rating', 'DECIMAL(3,2) DEFAULT 0'),
        ('total_reviews', 'INTEGER DEFAULT 0'),
    ]
    
    for col_name, col_def in user_columns:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            print(f"✅ Added column {col_name} to users")
        except Exception as e:
            print(f"Could not add {col_name}: {e}")
    
    review_columns = [
        ('rating_service', 'INTEGER DEFAULT 0'),
        ('rating_shipping', 'INTEGER DEFAULT 0'),
        ('rating_quality', 'INTEGER DEFAULT 0'),
        ('rating_overall', 'INTEGER DEFAULT 0'),
    ]
    
    for col_name, col_def in review_columns:
        try:
            cur.execute(f"ALTER TABLE reviews ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            print(f"✅ Added column {col_name} to reviews")
        except Exception as e:
            print(f"Could not add {col_name}: {e}")
    
    conn.commit()
    cur.close()
    return_db(conn)
    print("✅ Review columns added successfully")

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

def init_reports():
    pass

if __name__ == '__main__':
    add_review_columns()
    add_missing_notification_columns()