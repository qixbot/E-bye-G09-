[1mdiff --git a/database.py b/database.py[m
[1mindex fad954a..ea40dea 100644[m
[1m--- a/database.py[m
[1m+++ b/database.py[m
[36m@@ -67,8 +67,83 @@[m [mdef init_db():[m
         )[m
     ''')[m
 [m
[32m+[m[32m<<<<<<< HEAD[m
     # Products table[m
     cur.execute('''[m
[32m+[m[32m=======[m
[32m+[m[32m    # Create offers table (for offer system)[m
[32m+[m[32m    db.execute('''[m
[32m+[m[32m        CREATE TABLE IF NOT EXISTS offers ([m
[32m+[m[32m            id INTEGER PRIMARY KEY AUTOINCREMENT,[m
[32m+[m[32m            product_id INTEGER NOT NULL,[m
[32m+[m[32m            buyer_id INTEGER NOT NULL,[m
[32m+[m[32m            offer_price REAL NOT NULL,[m
[32m+[m[32m            original_price REAL,[m
[32m+[m[32m            message TEXT,[m
[32m+[m[32m            counter_price REAL,[m
[32m+[m[32m            status TEXT DEFAULT 'pending',[m
[32m+[m[32m            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,[m
[32m+[m[32m            FOREIGN KEY (product_id) REFERENCES products(id),[m
[32m+[m[32m            FOREIGN KEY (buyer_id) REFERENCES users(id)[m
[32m+[m[32m        )[m
[32m+[m[32m    ''')[m
[32m+[m
[32m+[m[32m    # Add missing columns for existing databases[m
[32m+[m[32m    columns_to_add = [[m
[32m+[m[32m        ('full_name', 'TEXT'),[m
[32m+[m[32m        ('contact', 'TEXT'),[m
[32m+[m[32m        ('bio', 'TEXT'),[m
[32m+[m[32m        ('avatar_blob', 'BLOB'),[m
[32m+[m[32m        ('cover_blob', 'BLOB'),[m
[32m+[m[32m        ('background_type', "TEXT DEFAULT 'default'"),[m
[32m+[m[32m        ('background_value', 'TEXT'),[m
[32m+[m[32m        ('active_hours', 'TEXT'),[m
[32m+[m[32m        ('frozen_until', 'TIMESTAMP'),[m
[32m+[m[32m        ('freeze_reason', 'TEXT'),[m
[32m+[m[32m        ('freeze_count', 'INTEGER DEFAULT 0'),[m
[32m+[m[32m        ('trust_score', 'INTEGER DEFAULT 85'),[m
[32m+[m[32m        ('response_rate', 'INTEGER DEFAULT 98'),[m
[32m+[m[32m        ('rating', "TEXT DEFAULT '--'"),[m
[32m+[m[32m        ('remember_token', 'TEXT')[m
[32m+[m[32m    ][m
[32m+[m
[32m+[m[32m    for col_name, col_def in columns_to_add:[m
[32m+[m[32m        try:[m
[32m+[m[32m            db.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")[m
[32m+[m[32m            print(f"Added column: {col_name}")[m
[32m+[m[32m        except sqlite3.OperationalError:[m
[32m+[m[32m            pass[m
[32m+[m
[32m+[m[32m    db.commit()[m
[32m+[m
[32m+[m[32m    # Create default admin user[m
[32m+[m[32m    admin_email = 'admin@student.mmu.edu.my'[m
[32m+[m[32m    admin_password = generate_password_hash('Admin123!')[m
[32m+[m
[32m+[m[32m    existing_admin = db.execute([m
[32m+[m[32m        'SELECT * FROM users WHERE email = ?', (admin_email,)[m
[32m+[m[32m    ).fetchone()[m
[32m+[m
[32m+[m[32m    if not existing_admin:[m
[32m+[m[32m        db.execute('''[m
[32m+[m[32m            INSERT INTO users (student_id, email, username, password, is_admin)[m
[32m+[m[32m            VALUES (?, ?, ?, ?, ?)[m
[32m+[m[32m        ''', ('ADMIN001', admin_email, 'Administrator', admin_password, 1))[m
[32m+[m[32m        db.commit()[m
[32m+[m[32m        print("✅ Default admin created: admin@student.mmu.edu.my / Admin123!")[m
[32m+[m[32m    else:[m
[32m+[m[32m        print("✅ Admin user already exists")[m
[32m+[m
[32m+[m[32m    db.close()[m
[32m+[m[32m    print("✅ Database ready with users and notifications tables")[m
[32m+[m
[32m+[m
[32m+[m[32mdef init_products():[m
[32m+[m[32m    """Initialize products table (without images_blob)"""[m
[32m+[m[32m    db = get_db()[m
[32m+[m
[32m+[m[32m    db.execute('''[m
[32m+[m[32m>>>>>>> 07504f0 (feat: Fix my_profile product editing + add admin Remember Me)[m
         CREATE TABLE IF NOT EXISTS products ([m
             id SERIAL PRIMARY KEY,[m
             seller_id INTEGER NOT NULL REFERENCES users(id),[m
[36m@@ -85,8 +160,34 @@[m [mdef init_db():[m
         )[m
     ''')[m
 [m
[32m+[m[32m<<<<<<< HEAD[m
     # Messages table[m
     cur.execute('''[m
[32m+[m[32m=======[m
[32m+[m[32m    # Add missing columns for products table[m
[32m+[m[32m    products_cols = [[m
[32m+[m[32m        ('status', "TEXT DEFAULT 'pending'"),[m
[32m+[m[32m        ('reject_reason', "TEXT DEFAULT ''"),[m
[32m+[m[32m        ('images_blob', 'TEXT'),[m
[32m+[m[32m    ][m
[32m+[m[32m    for col_name, col_def in products_cols:[m
[32m+[m[32m        try:[m
[32m+[m[32m            db.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_def}")[m
[32m+[m[32m            print(f"Added column: {col_name} to products")[m
[32m+[m[32m        except sqlite3.OperationalError:[m
[32m+[m[32m            pass[m
[32m+[m
[32m+[m[32m    db.commit()[m
[32m+[m[32m    db.close()[m
[32m+[m[32m    print("✅ Products table ready")[m
[32m+[m
[32m+[m
[32m+[m[32mdef init_messages():[m
[32m+[m[32m    """Initialize messages table for chat system"""[m
[32m+[m[32m    db = get_db()[m
[32m+[m
[32m+[m[32m    db.execute('''[m
[32m+[m[32m>>>>>>> 07504f0 (feat: Fix my_profile product editing + add admin Remember Me)[m
         CREATE TABLE IF NOT EXISTS messages ([m
             id SERIAL PRIMARY KEY,[m
             sender_id INTEGER NOT NULL REFERENCES users(id),[m
[36m@@ -100,6 +201,7 @@[m [mdef init_db():[m
         )[m
     ''')[m
 [m
[32m+[m[32m<<<<<<< HEAD[m
     # Offers table[m
     cur.execute('''[m
         CREATE TABLE IF NOT EXISTS offers ([m
[36m@@ -114,6 +216,13 @@[m [mdef init_db():[m
             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP[m
         )[m
     ''')[m
[32m+[m[32m=======[m
[32m+[m[32m    try:[m
[32m+[m[32m        db.execute("ALTER TABLE messages ADD COLUMN msg_type TEXT DEFAULT 'text'")[m
[32m+[m[32m        print("Added column: msg_type to messages")[m
[32m+[m[32m    except sqlite3.OperationalError:[m
[32m+[m[32m        pass[m
[32m+[m[32m>>>>>>> 07504f0 (feat: Fix my_profile product editing + add admin Remember Me)[m
 [m
     # Announcements table[m
     cur.execute('''[m
