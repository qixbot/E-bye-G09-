import psycopg2

NEW_DB = "postgresql://neondb_owner:npg_6iyxMHpXf7ho@ep-odd-meadow-at6yas04-pooler.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require"

conn = psycopg2.connect(NEW_DB)
cur = conn.cursor()
cur.execute("ALTER TABLE offers ADD COLUMN IF NOT EXISTS seller_id INTEGER REFERENCES users(id)")
conn.commit()
cur.close()
conn.close()
print("✅ seller_id 列添加成功")
