# set_admin.py
import sys
import os

# 添加当前目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import get_db
from werkzeug.security import generate_password_hash

def set_admin():
    print("Connecting to database...")
    db = get_db()
    cur = db.cursor()
    
    email = 'EILEEN.KERK.HUI@student.mmu.edu.my'
    
    # 检查用户是否存在
    cur.execute("SELECT id, email, is_admin FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    
    if user:
        print(f"Found user: {user['email']}, current is_admin={user['is_admin']}")
        cur.execute("UPDATE users SET is_admin = 1 WHERE id = %s", (user['id'],))
        db.commit()
        print(f"✅ {email} is now ADMIN!")
    else:
        print(f"User {email} not found, creating new admin user...")
        hashed_password = generate_password_hash('Uyhzv3q@')
        cur.execute('''
            INSERT INTO users (student_id, email, username, password, is_admin)
            VALUES (%s, %s, %s, %s, %s)
        ''', ('ADMIN001', email, 'Eileen', hashed_password, 1))
        db.commit()
        print(f"✅ Admin user {email} created!")
    
    # 验证
    cur.execute("SELECT id, email, is_admin FROM users WHERE email = %s", (email,))
    result = cur.fetchone()
    print(f"Verification: {result}")
    
    cur.close()
    db.close()
    print("Done!")

if __name__ == '__main__':
    set_admin()