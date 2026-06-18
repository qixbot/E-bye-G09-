import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# 添加 avatar_url 列
try:
    cur.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT;")
    print("✅ avatar_url 列已添加")
except Exception as e:
    print(f"⚠️ avatar_url 添加失败（可能已存在）: {e}")

# 添加 cover_url 列
try:
    cur.execute("ALTER TABLE users ADD COLUMN cover_url TEXT;")
    print("✅ cover_url 列已添加")
except Exception as e:
    print(f"⚠️ cover_url 添加失败（可能已存在）: {e}")

conn.commit()
cur.close()
conn.close()