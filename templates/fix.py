import re

# 读取 app.py
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 替换 %s 为 ?
content = content.replace('%s', '?')

# 写回文件
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ All %s replaced with ?")