import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("❌ 请设置 DATABASE_URL 环境变量")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'users'
    ORDER BY ordinal_position;
""")

rows = cur.fetchall()
print("📊 users 表的字段：")
for row in rows:
    print(f"  {row[0]} → {row[1]}")

cur.close()
conn.close()