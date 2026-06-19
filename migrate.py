import psycopg2
from psycopg2.extras import RealDictCursor
import os
import sys

OLD_DB = "postgresql://neondb_owner:npg_6iyxMHpXf7ho@ep-odd-meadow-at6yas04-pooler.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require"
NEW_DB = "postgresql://neondb_owner:npg_u83MPYKgCjXf@ep-patient-term-ao77run5-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

insert_order = ['users', 'products', 'messages', 'offers', 'announcements',
                'reviews', 'reports', 'cart_items', 'orders', 'notifications']

def get_conn(url):
    conn = psycopg2.connect(url)
    conn.cursor_factory = RealDictCursor
    return conn

print("=" * 50)
print("Step 1: 在新数据库建表...")
print("=" * 50)
os.environ['DATABASE_URL'] = NEW_DB
sys.path.insert(0, '.')
from database import init_db
init_db()
print("✅ 建表完成\n")

print("=" * 50)
print("Step 2: 连接数据库...")
print("=" * 50)
try:
    old_conn = get_conn(OLD_DB)
    old_cur = old_conn.cursor()
    print("✅ 旧数据库连接成功")
except Exception as e:
    print(f"❌ 旧数据库连接失败: {e}")
    sys.exit(1)

try:
    new_conn = get_conn(NEW_DB)
    new_cur = new_conn.cursor()
    print("✅ 新数据库连接成功\n")
except Exception as e:
    print(f"❌ 新数据库连接失败: {e}")
    sys.exit(1)

print("=" * 50)
print("Step 3: 读取旧数据库全部数据...")
print("=" * 50)
all_data = {}
for table in insert_order:
    try:
        old_cur.execute(f"SELECT * FROM {table}")
        rows = old_cur.fetchall()
        all_data[table] = [dict(row) for row in rows]
        print(f"  📥 {table}: {len(rows)} 条")
    except Exception as e:
        all_data[table] = []
        print(f"  ⚠️  {table}: 读取失败 - {e}")

old_cur.close()
old_conn.close()
print("✅ 旧数据库读取完毕\n")

print("=" * 50)
print("Step 4: 清空新数据库...")
print("=" * 50)
try:
    new_cur.execute("TRUNCATE TABLE notifications, cart_items, orders, reports, reviews, offers, messages, products, users, announcements RESTART IDENTITY CASCADE")
    new_conn.commit()
    print("✅ 清空完成\n")
except Exception as e:
    new_conn.rollback()
    print(f"❌ 清空失败: {e}")
    sys.exit(1)

print("=" * 50)
print("Step 5: 插入数据...")
print("=" * 50)

for table in insert_order:
    rows = all_data.get(table, [])
    if not rows:
        print(f"  ⏭️  {table}: 空表，跳过")
        continue

    cols = list(rows[0].keys())
    cols_str = ', '.join([f'"{c}"' for c in cols])
    placeholders = ', '.join(['%s'] * len(cols))

    success_count = 0
    fail_count = 0
    for row in rows:
        try:
            values = [row[c] for c in cols]
            new_cur.execute(
                f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                values
            )
            new_conn.commit()
            success_count += 1
        except Exception as row_err:
            new_conn.rollback()
            fail_count += 1
            print(f"    ❌ {table} 失败一行: {row_err}")

    if fail_count == 0:
        print(f"  ✅ {table}: {success_count}/{len(rows)} 条全部成功")
    else:
        print(f"  ⚠️  {table}: {success_count} 成功, {fail_count} 失败")

print("\n" + "=" * 50)
print("Step 6: 重置 ID sequences...")
print("=" * 50)
for table in insert_order:
    try:
        new_cur.execute(f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', 'id'),
                COALESCE((SELECT MAX(id) FROM {table}), 1)
            )
        """)
        new_conn.commit()
        print(f"  ✅ {table} 完成")
    except Exception as e:
        print(f"  ⚠️  {table} 跳过: {e}")

new_cur.close()
new_conn.close()

print("\n" + "=" * 50)
print("✅ 全部迁移完成！")
print("=" * 50)
print("\n接下来：")
print("1. 去 Render → Environment → 更新 DATABASE_URL 为新连接字符串")
print("2. 点 Manual Deploy")