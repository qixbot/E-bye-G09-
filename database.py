import os

import psycopg2

from psycopg2 import pool

import time

import logging

from psycopg2.extras import RealDictCursor

from werkzeug.security import generate_password_hash

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    DATABASE_URL = "postgresql://postgres.pqfxyvjtwqpadddjkpdx:NQxhRLN6fmTQwHHc@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres"

connection_pool = None

def init_connection_pool():
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = psycopg2.pool.SimpleConnectionPool(
                1, 10,           # min 1, max 10 (leaves room for other connections)
                DATABASE_URL,
                connect_timeout=30,
                keepalives=1,
                keepalives_idle=5,
                keepalives_interval=2,
                keepalives_count=2,
                sslmode='require'
            )
            logger.info("✅ Connection pool created (max: 10 connections)")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise
    return connection_pool

def get_db():
    """Get a connection from the pool (must be paired with return_db)."""
    global connection_pool
    if connection_pool is None:
        init_connection_pool()
    try:
        conn = connection_pool.getconn()
        conn.cursor_factory = RealDictCursor
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

def get_db_with_retry(retries=3, delay=2):
    """Get connection with retry on pool exhaustion."""
    for i in range(retries):
        try:
            return get_db()
        except Exception as e:
            if "max clients reached" in str(e) and i < retries - 1:
                wait = delay * (i + 1)
                logger.warning(f"Pool full, retry {i+1}/{retries} in {wait}s...")
                time.sleep(wait)
                continue
            elif i == retries - 1:
                raise
            time.sleep(delay)
    return get_db()

def return_db(conn):
    """Return connection to the pool (MUST be called after each get_db)."""
    global connection_pool
    if connection_pool and conn:
        try:
            connection_pool.putconn(conn)
        except Exception as e:
            logger.error(f"Error returning connection: {e}")
            try:
                conn.close()
            except:
                pass

def close_all_connections():
    global connection_pool
    if connection_pool:
        connection_pool.closeall()
        logger.info("All database connections closed")

# ----- Context manager for safe usage -----
from contextlib import contextmanager

@contextmanager
def db_connection():
    """Context manager that yields a connection and automatically returns it."""
    conn = get_db_with_retry()
    try:
        yield conn
    finally:
        return_db(conn)

@contextmanager
def db_cursor():
    """Context manager that yields a cursor and automatically returns connection."""
    with db_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor, conn
        finally:
            cursor.close()

# ----- Ensure missing columns exist -----
def ensure_columns():
    """Add any missing columns (e.g., rating_service) to prevent 500 errors."""
    with db_connection() as conn:
        cur = conn.cursor()
        # Reviews table columns
        review_cols = [
            ('rating_service', 'INTEGER DEFAULT 0'),
            ('rating_shipping', 'INTEGER DEFAULT 0'),
            ('rating_quality', 'INTEGER DEFAULT 0'),
            ('rating_overall', 'INTEGER DEFAULT 0'),
        ]
        for col, dtype in review_cols:
            cur.execute(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='reviews' AND column_name='{col}'
            """)
            if not cur.fetchone():
                cur.execute(f"ALTER TABLE reviews ADD COLUMN {col} {dtype}")
                logger.info(f"Added column {col} to reviews")
        # Users table additional columns
        user_cols = [
            ('avg_service_rating', 'DECIMAL(3,2) DEFAULT 0'),
            ('avg_shipping_rating', 'DECIMAL(3,2) DEFAULT 0'),
            ('avg_quality_rating', 'DECIMAL(3,2) DEFAULT 0'),
            ('avg_overall_rating', 'DECIMAL(3,2) DEFAULT 0'),
            ('total_reviews', 'INTEGER DEFAULT 0'),
        ]
        for col, dtype in user_cols:
            cur.execute(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='users' AND column_name='{col}'
            """)
            if not cur.fetchone():
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
                logger.info(f"Added column {col} to users")
        conn.commit()
        cur.close()

# ----- Table initialization -----
def init_db():
    """Create all tables if they don't exist."""
    with db_connection() as conn:
        cur = conn.cursor()

        # Users
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

        # Notifications
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

        # Products
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

        # Messages
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

        # Offers
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

        # Announcements
        cur.execute('''
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Reviews
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

        # Reports
        cur.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                reporter_id INTEGER NOT NULL REFERENCES users(id),
                reported_user_id INTEGER NOT NULL REFERENCES users(id),
                product_id INTEGER,
                reason TEXT NOT NULL,
                details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Orders
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
                last_reminder_sent TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )
        ''')

        # Default admin
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

    # Ensure missing columns exist
    ensure_columns()

# Compatibility stubs
def init_products(): pass
def init_messages(): pass
def init_announcements(): pass
def init_reviews(): pass
def init_orders(): pass
def init_reports(): pass

if __name__ == '__main__':
    init_connection_pool()
    init_db()