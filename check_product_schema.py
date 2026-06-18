import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# 查看 products 表
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'products'
    ORDER BY ordinal_position;
""")

print("📊 products 表的字段：")
for row in cur.fetchall():
    print(f"  {row[0]} → {row[1]}")

# 查看 locations 表（如果有）
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'locations'
    ORDER BY ordinal_position;
""")

print("\n📊 locations 表的字段：")
for row in cur.fetchall():
    print(f"  {row[0]} → {row[1]}")

cur.close()
conn.close()