import sqlite3
import json
import os

# 检查 SQLite 数据库是否存在
db_path = 'instance/site.db'
if not os.path.exists(db_path):
    print(f"❌ 数据库文件不存在: {db_path}")
    print("请检查路径是否正确")
    exit(1)

# 连接 SQLite 数据库
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 获取所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
tables = cursor.fetchall()

backup_data = {}

for table in tables:
    table_name = table['name']
    print(f"📦 备份表: {table_name}")
    
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    
    # 转换为字典列表
    table_data = []
    for row in rows:
        table_data.append(dict(row))
    
    backup_data[table_name] = table_data

# 保存为 JSON 备份文件
with open('backup.json', 'w', encoding='utf-8') as f:
    json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)

print(f"✅ 备份完成！共备份 {len(tables)} 个表")
print(f"📁 备份文件: backup.json")

# 显示统计信息
for table_name, data in backup_data.items():
    print(f"   - {table_name}: {len(data)} 条记录")

conn.close()