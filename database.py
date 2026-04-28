import sqlite3

from werkzeug.security import generate_password_hash

DATABASE = 'ebyte.db'

def get_db():
    """Get database connection with row factory"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with all required tables and columns"""
    db = get_db()

    # Create users table with BLOB columns for storing ALL images directly in database
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
            avatar_blob BLOB,
            cover_blob BLOB,
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
            trust_score INTEGER DEFAULT 85,
            response_rate INTEGER DEFAULT 98,
            rating TEXT DEFAULT '—',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create notifications table
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

    # Add missing columns for existing databases (safe migration)
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
        ('trust_score', 'INTEGER DEFAULT 85'),
        ('response_rate', 'INTEGER DEFAULT 98'),
        ('rating', "TEXT DEFAULT '—'")
    ]

    for col_name, col_def in columns_to_add:
        try:
            db.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
            print(f"Added column: {col_name}")
        except sqlite3.OperationalError:
            pass  # Column already exists

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
        print("Default admin created: admin@student.mmu.edu.my / Admin123!")
    else:
        print("Admin user already exists")

    db.close()
    print("Database ready")


def init_products():
    """Initialize products table with all required columns"""
    db = get_db()

    # Create products table (fixed: removed duplicate columns)
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

    # Add missing columns (safe for existing databases)
    try:
        db.execute("ALTER TABLE products ADD COLUMN status TEXT DEFAULT 'pending'")
        print("Added column: status")
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE products ADD COLUMN reject_reason TEXT DEFAULT ''")
        print("Added column: reject_reason")
    except sqlite3.OperationalError:
        pass

    db.commit()
    db.close()
    print("Products table ready")


# Initialize
init_db()
init_products()
