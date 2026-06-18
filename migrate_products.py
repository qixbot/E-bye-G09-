import os
import json
import psycopg2
from dotenv import load_dotenv
from cloudinary_helper import upload_image

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

def migrate_products():
    print("🔁 开始迁移产品图片到 Cloudinary...")
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # 1. 先添加 product_images_url 列（存储 Cloudinary URL 的 JSON 数组）
    try:
        cur.execute("ALTER TABLE products ADD COLUMN product_images_url TEXT;")
        print("✅ product_images_url 列已添加")
    except Exception as e:
        print(f"⚠️ product_images_url 添加失败（可能已存在）: {e}")
    
    conn.commit()
    
    # 2. 获取所有有图片的产品
    cur.execute("""
        SELECT id, name, images_blob 
        FROM products 
        WHERE images_blob IS NOT NULL 
        AND images_blob != ''
        AND images_blob != '[]'
        AND images_blob != 'null'
    """)
    products = cur.fetchall()
    
    print(f"📊 找到 {len(products)} 个有图片的产品")
    
    success_count = 0
    fail_count = 0
    total_images = 0
    
    for product in products:
        product_id = product[0]
        name = product[1]
        images_blob = product[2]
        
        try:
            # 解析 JSON
            if isinstance(images_blob, str):
                image_list = json.loads(images_blob)
            else:
                image_list = images_blob
            
            if not isinstance(image_list, list) or len(image_list) == 0:
                continue
            
            cloudinary_urls = []
            
            for idx, img_data in enumerate(image_list):
                try:
                    # 如果是 base64 data URI
                    if isinstance(img_data, str) and img_data.startswith('data:'):
                        # 提取 base64 数据
                        header, b64data = img_data.split(',', 1)
                        import base64
                        file_data = base64.b64decode(b64data)
                        
                        print(f"📤 上传产品 {product_id} ({name}) 图片 {idx+1}/{len(image_list)}...")
                        url = upload_image(file_data, folder=f"e-bye/products/{product_id}")
                        
                        if url:
                            cloudinary_urls.append(url)
                            total_images += 1
                            print(f"  ✅ 图片 {idx+1} 上传成功")
                        else:
                            print(f"  ❌ 图片 {idx+1} 上传失败")
                    else:
                        # 如果是 URL 或文件路径，直接上传文件
                        print(f"📤 上传产品 {product_id} ({name}) 图片 {idx+1}/{len(image_list)}...")
                        url = upload_image(img_data, folder=f"e-bye/products/{product_id}")
                        if url:
                            cloudinary_urls.append(url)
                            total_images += 1
                            print(f"  ✅ 图片 {idx+1} 上传成功")
                        else:
                            print(f"  ❌ 图片 {idx+1} 上传失败")
                            
                except Exception as e:
                    print(f"  ❌ 图片 {idx+1} 上传失败: {e}")
                    continue
            
            if cloudinary_urls:
                # 保存为 JSON 数组
                urls_json = json.dumps(cloudinary_urls)
                cur.execute(
                    "UPDATE products SET product_images_url = %s WHERE id = %s",
                    (urls_json, product_id)
                )
                conn.commit()
                success_count += 1
                print(f"✅ 产品 {product_id} ({name}) 迁移完成 ({len(cloudinary_urls)} 张图片)")
            else:
                fail_count += 1
                print(f"❌ 产品 {product_id} ({name}) 没有成功上传的图片")
                
        except Exception as e:
            fail_count += 1
            print(f"❌ 产品 {product_id} ({name}) 迁移失败: {e}")
    
    print(f"\n📊 产品图片迁移完成！")
    print(f"  成功产品: {success_count}")
    print(f"  失败产品: {fail_count}")
    print(f"  总图片数: {total_images}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    migrate_products()