import cloudinary
import cloudinary.uploader
import os

# Cloudinary 配置
cloudinary.config(
    cloud_name="dqajjowkm",
    api_key="921829476574145",
    api_secret="Z3GKYx_A3NlxdHODYPECXcw8n4"  # 用完整正确的值
)

def upload_avatar(file):
    """上传头像到 Cloudinary"""
    try:
        result = cloudinary.uploader.upload(
            file,
            folder="e-bye/avatars",
            transformation=[
                {'width': 400, 'height': 400, 'crop': 'fill', 'gravity': 'face'},
                {'quality': 'auto'}
            ]
        )
        return result.get('secure_url')
    except Exception as e:
        print(f"Avatar upload error: {e}")
        return None

def upload_cover(file):
    """上传封面图到 Cloudinary"""
    try:
        result = cloudinary.uploader.upload(
            file,
            folder="e-bye/covers",
            transformation=[
                {'width': 1200, 'height': 400, 'crop': 'fill'},
                {'quality': 'auto'}
            ]
        )
        return result.get('secure_url')
    except Exception as e:
        print(f"Cover upload error: {e}")
        return None

def upload_product_image(file):
    """上传产品图片到 Cloudinary"""
    try:
        result = cloudinary.uploader.upload(
            file,
            folder="e-bye/products",
            transformation=[
                {'quality': 'auto'},
                {'fetch_format': 'auto'}
            ]
        )
        return result.get('secure_url')
    except Exception as e:
        print(f"Product image upload error: {e}")
        return None

def upload_chat_image(file):
    """上传聊天图片到 Cloudinary"""
    try:
        result = cloudinary.uploader.upload(
            file,
            folder="e-bye/chat",
            transformation=[
                {'width': 800, 'height': 800, 'crop': 'limit'},
                {'quality': 'auto'}
            ]
        )
        return result.get('secure_url')
    except Exception as e:
        print(f"Chat image upload error: {e}")
        return None