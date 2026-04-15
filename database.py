import sqlite3

DATABASE = 'ebyte.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            gender TEXT,
            active_hours TEXT,
            avatar TEXT,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.commit()
    db.close()
    print("Database ready WITH user table")

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
    #Add freeze/ban fields to the users table）
    try:
        db.execute("ALTER TABLE users ADD COLUMN is_frozen INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        # 字段已存在，跳过
        pass
    
    try:
        db.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        # 字段已存在，跳过
        pass
    
    db.commit()
    db.close()

init_notifications()