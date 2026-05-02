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

    # Create users table with remember_token column
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
            freeze_count INTEGER DEFAULT 0,
            trust_score INTEGER DEFAULT 85,
            response_rate INTEGER DEFAULT 98,
            rating TEXT DEFAULT '--',
            remember_token TEXT,
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
        print("✅ Default admin created: admin@student.mmu.edu.my / Admin123!")
    else:
        print("✅ Admin user already exists")

    db.close()
    print("✅ Database ready with users and notifications tables")


def init_products():
    """Initialize products table with images_blob column"""
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
            images_blob TEXT,
            status TEXT DEFAULT 'pending',
            reject_reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (seller_id) REFERENCES users(id)
        )
    ''')

    # Add missing columns for products table
    try:
        db.execute("ALTER TABLE products ADD COLUMN status TEXT DEFAULT 'pending'")
        print("Added column: status to products")
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE products ADD COLUMN reject_reason TEXT DEFAULT ''")
        print("Added column: reject_reason to products")
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE products ADD COLUMN images_blob TEXT")
        print("Added column: images_blob to products")
    except sqlite3.OperationalError:
        pass

    db.commit()
    db.close()
    print("✅ Products table ready")


def init_messages():
    """Initialize messages table for chat system"""
    db = get_db()

    db.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            product_id INTEGER,
            content TEXT,
            msg_type TEXT DEFAULT 'text',
            image TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')

    # Add missing columns
    try:
        db.execute("ALTER TABLE messages ADD COLUMN msg_type TEXT DEFAULT 'text'")
        print("Added column: msg_type to messages")
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE messages ADD COLUMN image TEXT")
        print("Added column: image to messages")
    except sqlite3.OperationalError:
        pass

    db.commit()
    db.close()
    print("✅ Messages table ready")


def init_announcements():
    """Initialize announcements table"""
    db = get_db()

    db.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    db.commit()
    db.close()
    print("✅ Announcements table ready")


def init_reviews():
    """Initialize reviews table"""
    db = get_db()

    db.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            reviewer_id INTEGER NOT NULL,
            reviewee_id INTEGER NOT NULL,
            order_id INTEGER,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (reviewer_id) REFERENCES users(id),
            FOREIGN KEY (reviewee_id) REFERENCES users(id),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    ''')

    db.commit()
    db.close()
    print("✅ Reviews table ready")


def init_orders():
    """Initialize orders table"""
    db = get_db()

    db.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            product_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            offer_price REAL,
            quantity INTEGER DEFAULT 1,
            meeting_point TEXT,
            meeting_time TEXT,
            buyer_note TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (buyer_id) REFERENCES users(id),
            FOREIGN KEY (seller_id) REFERENCES users(id)
        )
    ''')

    db.commit()
    db.close()
    print("✅ Orders table ready")


# Initialize all tables
init_db()
init_products()
init_messages()
init_announcements()
init_reviews()
init_orders()