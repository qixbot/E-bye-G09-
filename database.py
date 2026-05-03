import os
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash

# Read database URL from environment variable (safer)
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    # Fallback for local testing – replace with your actual Supabase URL (but don't commit to git!)
    DATABASE_URL = "postgresql://postgres.pqfxyvjtwqpadddjkpdx:NQxhRLN6fmTQwHHc@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"

def get_db():
    """Return a PostgreSQL database connection"""
    conn = psycopg2.connect(DATABASE_URL)
    # Use RealDictCursor so rows behave like dictionaries (similar to sqlite3.Row)
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

<<<<<<< HEAD
    # Products table
    cur.execute('''
=======
    # Create offers table (for offer system)
    db.execute('''
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            offer_price REAL NOT NULL,
            original_price REAL,
            message TEXT,
            counter_price REAL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (buyer_id) REFERENCES users(id)
        )
    ''')

    # Add missing columns for existing databases
    columns_to_add = [
        ('full_name', 'TEXT'),
        ('contact', 'TEXT'),
        ('bio', 'TEXT'),
        ('avatar_blob', 'BLOB'),
        ('cover_blob', 'BLOB'),
        ('background_type', "TEXT DEFAULT 'default'"),
        ('background_value', 'TEXT'),
        ('active_hours', 'TEXT'),
        ('frozen_until', 'TIMESTAMP'),
        ('freeze_reason', 'TEXT'),
        ('freeze_count', 'INTEGER DEFAULT 0'),
        ('trust_score', 'INTEGER DEFAULT 85'),
        ('response_rate', 'INTEGER DEFAULT 98'),
        ('rating', "TEXT DEFAULT '--'"),
        ('remember_token', 'TEXT')
    ]

    for col_name, col_def in columns_to_add:
        try:
            db.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
            print(f"Added column: {col_name}")
        except sqlite3.OperationalError:
            pass

    db.commit()

    # Create default admin user
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
    print("✅ Database ready with users and notifications tables")


def init_products():
    """Initialize products table (without images_blob)"""
    db = get_db()

    db.execute('''
>>>>>>> 07504f0 (feat: Fix my_profile product editing + add admin Remember Me)
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

<<<<<<< HEAD
    # Messages table
    cur.execute('''
=======
    # Add missing columns for products table
    products_cols = [
        ('status', "TEXT DEFAULT 'pending'"),
        ('reject_reason', "TEXT DEFAULT ''"),
        ('images_blob', 'TEXT'),
    ]
    for col_name, col_def in products_cols:
        try:
            db.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_def}")
            print(f"Added column: {col_name} to products")
        except sqlite3.OperationalError:
            pass

    db.commit()
    db.close()
    print("✅ Products table ready")


def init_messages():
    """Initialize messages table for chat system"""
    db = get_db()

    db.execute('''
>>>>>>> 07504f0 (feat: Fix my_profile product editing + add admin Remember Me)
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

<<<<<<< HEAD
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
=======
    try:
        db.execute("ALTER TABLE messages ADD COLUMN msg_type TEXT DEFAULT 'text'")
        print("Added column: msg_type to messages")
    except sqlite3.OperationalError:
        pass
>>>>>>> 07504f0 (feat: Fix my_profile product editing + add admin Remember Me)

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

    # Insert default admin user (if not exists)
    admin_email = 'admin@student.mmu.edu.my'
    admin_password = generate_password_hash('Admin123!')
    cur.execute("SELECT id FROM users WHERE email = %s", (admin_email,))
    if not cur.fetchone():
        cur.execute('''
            INSERT INTO users (student_id, email, username, password, is_admin)
            VALUES (%s, %s, %s, %s, %s)
        ''', ('ADMIN001', admin_email, 'Administrator', admin_password, 1))
        conn.commit()
        print("✅ Default admin created")
    else:
        print("✅ Admin user already exists")

    cur.close()
    conn.close()
    print("✅ All tables ready in PostgreSQL")

# Keep the other init functions (init_products, init_messages, etc.) but remove their table creation
# because we already created all tables above. Alternatively, just call init_db() once at startup.

# For simplicity, you can remove init_products(), init_messages(), etc., and only use init_db().

# But to keep compatibility with existing app.py calls, define empty functions or just let init_db() do all.

def init_products():
    pass  # already done in init_db()

def init_messages():
    pass

def init_announcements():
    pass

def init_reviews():
    pass

def init_orders():
    pass