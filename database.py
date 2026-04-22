import sqlite3
from werkzeug.security import generate_password_hash

DATABASE = 'ebyte.db'
# Eileen Part
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    db = get_db()

    # create user table 
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT,
            gender TEXT,
            contact TEXT,
            bio TEXT,
            avatar TEXT,
            cover_image TEXT,
            active_hours TEXT,
            security_q1 TEXT,
            security_a1 TEXT,
            security_q2 TEXT,
            security_a2 TEXT,
            is_admin INTEGER DEFAULT 0,
            is_frozen INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    db.commit()

    # Eileen Part
    #CREATE Default admin
    admin_email = 'admin@student.mmu.edu.my'
    admin_password = generate_password_hash('Admin123!')
    
    existing = db.execute(
        'SELECT * FROM users WHERE email = ?', (admin_email,)
        ).fetchone()
    
    if not existing:
        db.execute('''
            INSERT INTO users (student_id, email, username, password, is_admin)
            VALUES (?, ?, ?, ?, ?)
        ''', ('ADMIN001', admin_email, 'Administrator', admin_password, 1))
        db.commit()
        print("✅ Default admin created: admin@student.mmu.edu.my / Admin123!")
    else:
        print("Admin user already exists")
    
    db.close()
    print("Database ready WITH user table")


#keting's part
def init_notifications():
    db = get_db()
    #Notification Table: Stores notifications for all users (freeze/ban/bargain/order)
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
    db.close()

init_notifications()

#Xingru's part
def init_products():
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
            status TEXT DEFAULT 'for_sale',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (seller_id) REFERENCES users(id)
        )
    ''')
    
    # Add status column if not exists (for approval workflow)
    try:
        db.execute("ALTER TABLE products ADD COLUMN status TEXT DEFAULT 'pending'")
    except sqlite3.OperationalError:
        pass  # column already exists
    
    db.commit()
    db.close()
    print("Database ready WITH products table")