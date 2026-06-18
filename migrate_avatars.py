import os
import psycopg2
from dotenv import load_dotenv
from cloudinary_helper import upload_image

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

def migrate_avatars():
    print("🔁 开始迁移头像到 Cloudinary...")
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # 获取所有有头像的用户
    cur.execute("""
        SELECT id, username, avatar_blob 
        FROM users 
        WHERE avatar_blob IS NOT NULL 
        AND avatar_blob != ''
    """)
    users = cur.fetchall()
    
    print(f"📊 找到 {len(users)} 个有头像的用户")
    
    success_count = 0
    fail_count = 0
    
    for user in users:
        user_id = user[0]
        username = user[1]
        blob_data = user[2]
        
        try:
            # 如果是 memoryview，转成 bytes
            if hasattr(blob_data, 'tobytes'):
                blob_data = blob_data.tobytes()
            elif isinstance(blob_data, memoryview):
                blob_data = bytes(blob_data)
            
            print(f"📤 上传 {username} 的头像...")
            url = upload_image(blob_data, folder="e-bye/avatars")
            
            if url:
                cur.execute(
                    "UPDATE users SET avatar_url = %s WHERE id = %s",
                    (url, user_id)
                )
                conn.commit()
                success_count += 1
                print(f"✅ {username} 迁移成功")
            else:
                fail_count += 1
                print(f"❌ {username} 上传失败")
                
        except Exception as e:
            fail_count += 1
            print(f"❌ {username} 迁移失败: {e}")
    
    print(f"\n📊 头像迁移完成！成功: {success_count}, 失败: {fail_count}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    migrate_avatars()