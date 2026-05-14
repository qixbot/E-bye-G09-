#!/usr/bin/env python
# set_admin.py - 将指定用户设置为管理员

import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 导入数据库模块
from database import get_db, get_db_with_retry

def set_admin(email):
    """将指定邮箱的用户设置为管理员"""
    try:
        db = get_db_with_retry()
        cur = db.cursor()
        
        # 先检查用户是否存在
        cur.execute("SELECT id, username, email, is_admin FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        
        if not user:
            print(f"❌ User with email '{email}' not found!")
            return False
        
        if user['is_admin'] == 1:
            print(f"⚠️ User {user['username']} ({email}) is already an admin!")
            return True
        
        # 设置为管理员
        cur.execute("UPDATE users SET is_admin = 1 WHERE email = %s", (email,))
        db.commit()
        
        print(f"✅ Admin set successfully!")
        print(f"   User: {user['username']}")
        print(f"   Email: {email}")
        print(f"   Status: Now an administrator")
        
        cur.close()
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Error setting admin: {e}")
        if 'db' in locals() and db:
            db.close()
        return False

def list_admins():
    """列出所有管理员"""
    try:
        db = get_db_with_retry()
        cur = db.cursor()
        
        cur.execute("SELECT id, username, email, is_admin FROM users WHERE is_admin = 1")
        admins = cur.fetchall()
        
        print("\n📋 Current Administrators:")
        print("-" * 50)
        for admin in admins:
            print(f"   ID: {admin['id']} | Username: {admin['username']} | Email: {admin['email']}")
        
        cur.close()
        db.close()
        return admins
        
    except Exception as e:
        print(f"❌ Error listing admins: {e}")
        return []

if __name__ == "__main__":
    # 使用方式
    if len(sys.argv) > 1:
        email = sys.argv[1]
        print(f"Setting admin for: {email}")
        set_admin(email)
    else:
        # 默认邮箱
        default_email = "EILEEN.KERK.HUI@student.mmu.edu.my"
        print(f"No email provided. Using default: {default_email}")
        set_admin(default_email)
    
    # 显示当前所有管理员
    list_admins()