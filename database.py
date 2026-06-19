import os
import time
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# Database Configuration
# ============================================================

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

if not DATABASE_URL:
    DATABASE_URL = "postgresql://neondb_owner:npg_u83MPYKgCjXf@ep-patient-term-ao77run5-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
    logger.info("Using default DATABASE_URL (Neon PostgreSQL)")


def get_db():
    """Get database connection"""
    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            connect_timeout=3,
            keepalives=1,
            keepalives_idle=2,
            keepalives_interval=1,
            keepalives_count=2
        )
        conn.cursor_factory = RealDictCursor
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise


def get_db_with_retry(retries=3, delay=2):
    """带重试的连接函数"""
    for i in range(retries):
        try:
            return get_db()
        except Exception as e:
            if i == retries - 1:
                raise
            logger.warning(f"Connection attempt {i+1} failed, retrying in {delay}s: {e}")
            time.sleep(delay)
    return get_db()


def execute_query(sql: str, params: tuple = None, fetch_one: bool = False, fetch_all: bool = False):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(sql, params or ())
        
        if fetch_one:
            return cur.fetchone()
        elif fetch_all:
            return cur.fetchall()
        else:
            conn.commit()
            return cur.rowcount
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def add_column_if_not_exists(table: str, column: str, column_def: str) -> bool:
    """添加列（如果不存在）"""
    try:
        execute_query(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {column_def}")
        logger.info(f"✅ Added column '{column}' to {table}")
        return True
    except Exception as e:
        logger.warning(f"Could not add column '{column}' to {table}: {e}")
        return False


def init_db():
    """初始化数据库（快速检查）"""
    conn = None
    try:
        print("🔄 Checking database...")
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'users'
            ) as exists_flag
        """)
        result = cur.fetchone()
        table_exists = result['exists_flag'] if result else False
        
        if table_exists:
            print("✅ Database already initialized, skipping...")
            cur.close()
            conn.close()
            return
        
        print("📦 Creating database tables...")
        
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
                campus TEXT,
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
                approved_at TIMESTAMP,
                approved_by INTEGER,
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
                seller_id INTEGER REFERENCES users(id),
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
                product_id INTEGER,
                reason TEXT NOT NULL,
                details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS cart_items (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, product_id)
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
                last_reminder_sent TIMESTAMP,
                product_image TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )
        ''')
        
        cur.execute("CREATE INDEX IF NOT EXISTS idx_products_status ON products(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_products_seller_id ON products(seller_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_buyer_id ON orders(buyer_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_seller_id ON orders(seller_id)")
        
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
        conn.close()
        print("✅ All tables ready in Neon PostgreSQL")
        
    except Exception as e:
        logger.error(f"init_db failed: {e}")
        if conn:
            conn.close()
        raise


def add_missing_columns():
    """添加所有缺失的列"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        user_columns = [
            ('avg_service_rating', 'DECIMAL(3,2) DEFAULT 0'),
            ('avg_shipping_rating', 'DECIMAL(3,2) DEFAULT 0'),
            ('avg_quality_rating', 'DECIMAL(3,2) DEFAULT 0'),
            ('avg_overall_rating', 'DECIMAL(3,2) DEFAULT 0'),
            ('total_reviews', 'INTEGER DEFAULT 0'),
            ('campus', 'TEXT'),
        ]
        for col_name, col_def in user_columns:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
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
            except Exception as e:
                print(f"Could not add {col_name}: {e}")
        
        notif_columns = [
            ('type', "TEXT DEFAULT 'general'"),
            ('related_id', 'INTEGER'),
            ('is_read', 'INTEGER DEFAULT 0'),
            ('product_id', 'INTEGER'),
        ]
        for col_name, col_def in notif_columns:
            try:
                cur.execute(f"ALTER TABLE notifications ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            except Exception as e:
                print(f"Could not add {col_name}: {e}")
        
        order_columns = [
            ('meeting_time', 'TEXT'),
            ('updated_at', 'TIMESTAMP'),
            ('product_image', 'TEXT'),
        ]
        for col_name, col_def in order_columns:
            try:
                cur.execute(f"ALTER TABLE orders ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            except Exception as e:
                print(f"Could not add {col_name}: {e}")
        
        conn.commit()
        print("✅ All missing columns added successfully")
    except Exception as e:
        logger.error(f"add_missing_columns failed: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def test_connection():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        print("✅ Database connected")
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def get_cart_count(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM cart_items WHERE user_id = %s', (user_id,))
    count = cur.fetchone()['count']
    cur.close()
    conn.close()
    return count

# 兼容性函数
def init_products(): pass
def init_messages(): pass
def init_announcements(): pass
def init_reviews(): pass
def init_orders(): pass
def init_reports(): pass


if __name__ == '__main__':
    print("Testing database connection...")
    if test_connection():
        print("\nInitializing database...")
        init_db()
        add_missing_columns()
        print("\n✅ All done! Database is ready.")
    else:
        print("\n❌ Cannot initialize database.")