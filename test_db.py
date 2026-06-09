import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
url = os.environ.get('DATABASE_URL')

try:
    conn = psycopg2.connect(url, connect_timeout=10)
    print("✅ Connected to Neon!")
    conn.close()
except Exception as e:
    print(f"❌ Failed: {e}")