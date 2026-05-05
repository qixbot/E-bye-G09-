import re

import subprocess

import os

from datetime import datetime, timedelta

import uuid

import base64

import psycopg2  

from psycopg2 import Binary  

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, make_response
)

from werkzeug.security import generate_password_hash, check_password_hash

from werkzeug.utils import secure_filename

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from database import init_db, get_db, init_products, init_messages, init_announcements, init_reviews

app = Flask(__name__)
app.secret_key = 'e-bye-secret-key-2026-new'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024      # 100MB max upload size

app.config['MAX_FORM_MEMORY_SIZE'] = 100 * 1024 * 1024  
# Fix: allow large base64 form fields (Werkzeug >=3.0 default is only 500KB)
app.config['MAX_FORM_PARTS'] = 1000   
# Fix: allow many form parts

# ============================================================
# Helper function for emoji (was missing)
# ============================================================
def get_emoji_by_category(name):
    """Return an emoji based on product name (fallback for purchases)"""
    name_lower = str(name).lower()
    if 'book' in name_lower:
        return '📚'
    if 'gadget' in name_lower or 'phone' in name_lower or 'laptop' in name_lower:
        return '💻'
    if 'dorm' in name_lower or 'bed' in name_lower or 'furniture' in name_lower:
        return '🛏️'
    if 'fashion' in name_lower or 'shirt' in name_lower or 'shoe' in name_lower:
        return '👕'
    if 'beauty' in name_lower or 'makeup' in name_lower:
        return '💄'
    if 'sport' in name_lower:
        return '⚽'
    if 'grocery' in name_lower or 'food' in name_lower:
        return '🛒'
    if 'stationery' in name_lower or 'pen' in name_lower:
        return '✏️'
    if 'music' in name_lower:
        return '🎸'
    return '📦'

def calculate_trust_score(user, listing_count):
    """Calculate trust score based on user profile and activity"""
    trust_score = 60
    

    if user['avatar_blob']:
        trust_score += 8
    if user['bio']:
        trust_score += 8
    if user['contact']:
        trust_score += 7
    if user['full_name']:
        trust_score += 7

    # Account age bonus
    if user['created_at']:
        try:
            ca = user['created_at']
            if isinstance(ca, str):
                created_date = datetime.strptime(ca[:19], '%Y-%m-%d %H:%M:%S')
            else:
                created_date = ca  # already a datetime from psycopg2
            days_since_join = (datetime.now() - created_date.replace(tzinfo=None)).days
            if days_since_join >= 365:
                trust_score += 20
            elif days_since_join >= 180:
                trust_score += 15
            elif days_since_join >= 30:
                trust_score += 10
            elif days_since_join >= 7:
                trust_score += 5
        except:
            pass

    # Listing count bonus (max 25)
    trust_score += min(25, (listing_count // 2) * 2)

    # Activity bonus
    if user['active_hours'] and user['active_hours'] != 'Not set':
        trust_score += 10
    if user['gender']:
        trust_score += 5

    trust_score = min(trust_score, 100)
    trust_score = max(trust_score, 30)
    
    return trust_score

# jinja2 time filter
@app.template_filter('time_since')

def time_since(date):
    if not date:
        return 'New'
    now = datetime.now()
    if isinstance(date, str):
        try:
            date = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
        except:
            return 'New'
    diff = now - date
    if diff.days > 365:
        return f"{diff.days//365}y"
    elif diff.days > 30:
        return f"{diff.days//30}m"
    elif diff.days > 0:
        return f"{diff.days}d"
    elif diff.seconds > 3600:
        return f"{diff.seconds//3600}h"
    elif diff.seconds > 60:
        return f"{diff.seconds//60}m"
    return 'Just now'

def generate_video_thumbnail(video_path, thumbnail_path, time_offset=0.5):
    """Extract a frame from video at given time offset and save as JPEG."""
    cmd = [
        'ffmpeg',
        '-i', video_path,
        '-ss', str(time_offset),
        '-vframes', '1',
        '-q:v', '2',
        '-y',
        thumbnail_path
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"Thumbnail generated for {video_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error for {video_path}: {e.stderr}")
        return False

# --- Setup folder for uploaded product images ---
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize the database
init_db()
init_products()
init_messages()
init_announcements()
init_reviews()

@app.route('/')
def index():
    return render_template('welcome.html')  

# ============================================================
# Eileen's Route - Login
# ============================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember_me = request.form.get('remember_me')

        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT * FROM users WHERE LOWER(email) = LOWER(%s)', (email,))
        user = cur.fetchone()
        cur.close()
        db.close()

        if user and check_password_hash(user['password'], password):
            # ========== 1. 永久封禁检查 ==========
            if user['is_blocked'] == 1:
                flash('❌ This account is permanently blocked. Contact admin for appeal.', 'danger')
                return redirect(url_for('login'))

            # ========== 2. 冻结检查 ==========
            if user['is_frozen'] == 1 and user['frozen_until']:
                now = datetime.now()
                expire_time = None
                try:
                    expire_time = datetime.strptime(user['frozen_until'], '%Y-%m-%d %H:%M:%S')
                except:
                    pass

                if expire_time and now < expire_time:
                    diff = expire_time - now
                    days = diff.days
                    hours = diff.seconds // 3600
                    reason = user['freeze_reason'] or 'No reason provided'
                    flash(f'⚠️ ACCOUNT FROZEN\nReason: {reason}\nUnlocks in: {days}d {hours}h', 'warning')
                    return redirect(url_for('login'))
                else:
                    db_auto = get_db()
                    cur_auto = db_auto.cursor()
                    cur_auto.execute("UPDATE users SET is_frozen = 0, frozen_until = NULL, freeze_reason = NULL WHERE id = %s", (user['id'],))
                    db_auto.commit()
                    cur_auto.close()
                    db_auto.close()

            # ========== 登录成功 ==========
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['student_id'] = user['student_id']

        if remember_me:
                import secrets
                token = secrets.token_urlsafe(64)
                db = get_db()
                cur = db.cursor()
                cur.execute('UPDATE users SET remember_token = %s WHERE id = %s', (token, user['id']))
                db.commit()
                cur.close()
                db.close()
                response = redirect(url_for('home'))
                response.set_cookie('remember_token', token, max_age=30*24*60*60, httponly=True, secure=False)
                flash('✅ Login successful!', 'success')
                return response
        else:
                db = get_db()
                cur = db.cursor()
                cur.execute('UPDATE users SET remember_token = NULL WHERE id = %s', (user['id'],))
                db.commit()
                cur.close()
                db.close()
                response = redirect(url_for('home'))
                response.set_cookie('remember_token', '', expires=0)
                flash('✅ Login successful!', 'success')
                return response
    else:
            flash('Invalid email or password', 'error')

    return render_template('login.html')

from flask import request, redirect, url_for, session

@app.before_request
def auto_unfreeze_expired():
    if 'user_id' in session or 'admin_logged_in' in session:
        db = get_db()
        cur = db.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        cur.execute("""
            SELECT id, username FROM users
            WHERE is_frozen = 1 AND frozen_until IS NOT NULL AND frozen_until < %s
        """, (now,))
        expired = cur.fetchall()
        
        cur.execute("""
            UPDATE users
            SET is_frozen = 0, frozen_until = NULL, freeze_reason = NULL
            WHERE is_frozen = 1 AND frozen_until IS NOT NULL AND frozen_until < %s
        """, (now,))
        
        for user in expired:
            cur.execute("""
                INSERT INTO notifications (user_id, message, created_at)
                VALUES (%s, %s, NOW())
            """, (user['id'],
                  f"✅ Your 7-day freeze has ENDED. Your account is now ACTIVE.\n"
                  f"Your freeze count remains. Please follow community guidelines.\n"
                  f"After 3 freezes, your account will be permanently blocked."))
        
        db.commit()
        cur.close()
        db.close()

@app.before_request
def check_remember_me():
    if 'user_id' in session:
        return
    
    public_routes = ['login', 'register', 'forgot_password', 'static', 'welcome']
    if request.endpoint in public_routes:
        return
    
    token = request.cookies.get('remember_token')
    if not token:
        return
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT id, username, student_id FROM users WHERE remember_token = %s', (token,))
    user = cur.fetchone()
    cur.close()
    db.close()

    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['student_id'] = user['student_id']
        print(f"Auto-logged in user: {user['username']}")


# ============================================================
# Eileen's Route - Register
# ============================================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        gender = request.form.get('gender')

        # Security questions
        q1 = request.form.get('q1', '').strip()
        a1 = request.form.get('a1', '').strip().lower()
        q2 = request.form.get('q2', '').strip()
        a2 = request.form.get('a2', '').strip().lower()

        errors = []

        # Student ID validation
        if not student_id or len(student_id) != 10:
            errors.append('Please enter a valid Student ID (10 characters)')
        elif not student_id.replace(' ', '').isalnum():
            errors.append('Student ID must contain only letters and numbers')

        # Email validation
        if not email:
            errors.append('Email is required')
        elif not (email.endswith('@student.mmu.edu.my')):
            err = 'Only MMU email addresses are allowed (@student.mmu.edu.my)'
            errors.append(err)

        # Username validation
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters')

        # Password validation
        if not password:
            errors.append('Password is required')
        else:
            if len(password) < 8:
                errors.append('Password must be at least 8 characters')
            if not re.search(r'[A-Z]', password):
                err = 'Password must contain at least 1 uppercase letter'
                errors.append(err)
            if not re.search(r'[a-z]', password):
                err = 'Password must contain at least 1 lowercase letter'
                errors.append(err)
            if not re.search(r'[0-9]', password):
                errors.append('Password must contain at least 1 number')
            if not re.search(r'[!@#$%^&*]', password):
                err = 'Password must contain at least 1 special character'
                errors.append(err)

        # Confirm password
        if password != confirm_password:
            errors.append('Passwords do not match')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html')

        db = get_db()
        cur = db.cursor()

        # Check existing student_id or email
        cur.execute('SELECT * FROM users WHERE student_id = %s OR LOWER(email) = LOWER(%s)', (student_id, email))
        existing = cur.fetchone()
        if existing:
            cur.close()
            db.close()
            flash('Student ID or Email already registered', 'error')
            return render_template('register.html')

        # Check existing username
        cur.execute('SELECT * FROM users WHERE LOWER(username) = LOWER(%s)', (username,))
        username_exists = cur.fetchone()
        if username_exists:
            cur.close()
            db.close()
            flash('Username already taken. Please choose another one.', 'error')
            return render_template('register.html')

        # Create user
        hashed_password = generate_password_hash(password)
        cur.execute('''
            INSERT INTO users (
                student_id, email, username, password, gender,
                security_q1, security_a1, security_q2, security_a2
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (student_id, email, username, hashed_password, gender,
              q1, a1, q2, a2))
        db.commit()
        cur.close()
        db.close()

        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


# ============================================================
# Xingru's Route - Homepage
# ============================================================
@app.route('/home')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT p.*, 
        u.username as seller_name, 
        u.full_name as seller_full_name, u.id as seller_id
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'approved'
        ORDER BY p.created_at DESC
    ''')
    products_data = cur.fetchall()
    cur.close()
    db.close()

    products = []
    import json
    for row in products_data:
        product = dict(row)
        images_str = product.get('images', '')
        images_blob_str = product.get('images_blob', '[]')
        
        # Parse base64 list from images_blob
        base64_list = []
        if images_blob_str and images_blob_str != '[]':
            try:
                base64_list = json.loads(images_blob_str)
                # Keep only valid data URLs (they start with data:)
                base64_list = [img for img in base64_list if img.startswith('data:')]
            except:
                base64_list = []
        
        # For file-based images (fallback)
        if images_str:
            img_list = images_str.split(',')
            # Filter only image files for carousel (max 3)
            image_extensions = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'jfif', 'bmp'}
            image_only = []
            for f in img_list:
                f = f.strip()
                ext = f.split('.')[-1].lower()
                if ext in image_extensions:
                    image_only.append(f)
            product['images_list'] = image_only[:3]
            product['actual_total'] = len(img_list)
            product['image_1'] = image_only[0] if len(image_only) > 0 else None
            product['image_2'] = image_only[1] if len(image_only) > 1 else None
        else:
            product['images_list'] = []
            product['actual_total'] = 0
            product['image_1'] = None
            product['image_2'] = None
        
        # Store base64 list for carousel
        product['images_base64_list'] = base64_list
        # Override actual_total if base64 list is the real source
        if base64_list:
            product['actual_total'] = len(base64_list)
        products.append(product)

    return render_template('home.html',
        username=session.get('username'), latest_products=products)

# ============================================================
# ============================================================
# Xingru's Route - Search with filters
# ============================================================
# ============================================================
@app.route('/search')
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    keyword = request.args.get('q', '').strip()
    
    # Categories (comma-separated from hidden input)
    categories_raw = request.args.get('category', '')
    if categories_raw:
        categories = [c.strip() for c in categories_raw.split(',') if c.strip()]
    else:
        categories = []
    
    # Condition (multi-select, comma-separated)
    condition_raw = request.args.get('condition', '')
    if condition_raw:
        conditions = [c.strip() for c in condition_raw.split(',') if c.strip()]
    else:
        conditions = []
    
    date_range = request.args.get('date_range')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)

    # Base query
    query = """
        SELECT p.*, u.username as seller_name, u.full_name as seller_full_name, u.id as seller_id
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'approved'
    """
    params = []

    # Keyword search
    if keyword:
        query += " AND (p.name LIKE %s OR p.description LIKE %s)"
        like = f"%{keyword}%"
        params.extend([like, like])

    # Category filter
    if categories:
        placeholders = ','.join('%s' for _ in categories)
        query += f" AND p.category IN ({placeholders})"
        params.extend(categories)

    # Condition filter (multi)
    if conditions:
        placeholders = ','.join('%s' for _ in conditions)
        query += f" AND p.condition IN ({placeholders})"
        params.extend(conditions)

    # Date range – prioritise date_range if provided, else use custom dates
    if date_range and date_range.isdigit():
        days = int(date_range)
        query += " AND p.created_at >= NOW() - INTERVAL '%s days'"
        params.append(days)
    else:
        if date_from:
            query += " AND p.created_at >= %s"
            params.append(date_from)
        if date_to:
            query += " AND p.created_at <= %s"
            params.append(date_to + " 23:59:59")

    # Price range
    if min_price is not None:
        query += " AND p.price >= %s"
        params.append(min_price)
    if max_price is not None:
        query += " AND p.price <= %s"
        params.append(max_price)

    # Sorting
    sort_by = request.args.get('sort', 'newest')
    if sort_by == 'newest':
        order_clause = "ORDER BY p.created_at DESC"
    elif sort_by == 'oldest':
        order_clause = "ORDER BY p.created_at ASC"
    elif sort_by == 'price_asc':
        order_clause = "ORDER BY p.price ASC, p.created_at DESC"
    elif sort_by == 'price_desc':
        order_clause = "ORDER BY p.price DESC, p.created_at DESC"
    elif sort_by == 'condition_asc':
        order_clause = "ORDER BY CASE TRIM(LOWER(p.condition)) " \
                    "WHEN 'like_new' THEN 1 " \
                    "WHEN 'good' THEN 2 " \
                    "WHEN 'fair' THEN 3 " \
                    "ELSE 4 END ASC, p.created_at DESC"
    elif sort_by == 'condition_desc':
        order_clause = "ORDER BY CASE TRIM(LOWER(p.condition)) " \
                    "WHEN 'like_new' THEN 1 " \
                    "WHEN 'good' THEN 2 " \
                    "WHEN 'fair' THEN 3 " \
                    "ELSE 4 END DESC, p.created_at DESC"
    else:
        order_clause = "ORDER BY p.created_at DESC"
    query += " " + order_clause

    db = get_db()
    cur = db.cursor()
    cur.execute(query, params)
    products_data = cur.fetchall()
    cur.close()
    db.close()

    # Process each product (same as home route, with base64 support)
    import json
    products = []
    for row in products_data:
        product = dict(row)
        images_str = product.get('images', '')
        images_blob_str = product.get('images_blob', '[]')
        
        # Parse base64 list from images_blob
        base64_list = []
        if images_blob_str and images_blob_str != '[]':
            try:
                base64_list = json.loads(images_blob_str)
                # Keep only valid data URLs (they start with data:)
                base64_list = [img for img in base64_list if img.startswith('data:')]
            except:
                base64_list = []
        
        # For file-based images (fallback)
        if images_str:
            img_list = images_str.split(',')
            image_extensions = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'jfif', 'bmp'}
            image_only = ['/static/uploads/' + f.strip() for f in img_list
                          if f.strip().split('.')[-1].lower() in image_extensions]
            product['images_list'] = image_only[:3]
            product['actual_total'] = len(img_list)
            product['image_1'] = image_only[0] if image_only else None
            product['image_2'] = image_only[1] if len(image_only) > 1 else None
        else:
            product['images_list'] = []
            product['actual_total'] = 0
            product['image_1'] = None
            product['image_2'] = None
        
        # Store base64 list for carousel
        product['images_base64_list'] = base64_list
        # Override actual_total if base64 list is the real source
        if base64_list:
            product['actual_total'] = len(base64_list)
        products.append(product)

    return render_template('search.html', products=products)

# ============================================================
# AVATAR ROUTES - Store as BLOB in database
# ============================================================
# Eileen's Route - Avatar image
@app.route('/avatar-image')
def avatar_image():
    """Serve avatar image from database BLOB - PERSISTENT storage"""
    if 'user_id' not in session:
        return '', 404

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT avatar_blob FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()

    if user and user['avatar_blob']:

        avatar_data = bytes(user['avatar_blob']) if hasattr(user['avatar_blob'], 'tobytes') else user['avatar_blob']
        response = make_response(avatar_data)
        response.headers.set('Content-Type', 'image/jpeg')
        response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
        return response
    return '', 404

# ============================================================
# Eileen's Route - Update avatar image
# ============================================================
@app.route('/update-profile-avatar', methods=['POST'])
def update_profile_avatar():
    """Upload avatar and store directly as BLOB in database"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400

    # Read image as binary data directly into database
    image_data = file.read()

    # Limit image size to 2MB
    if len(image_data) > 2 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Image too large (max 2MB)'}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute('UPDATE users SET avatar_blob = %s WHERE id = %s', (image_data, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

# ============================================================
# Added by Xingru - public route to serve avatar by user_id (for displaying other users' avatars)
# ============================================================
@app.route('/user-avatar/<int:user_id>')
def user_avatar(user_id):
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT avatar_blob FROM users WHERE id = %s', (user_id,))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    if user and user['avatar_blob']:
        avatar_data = bytes(user['avatar_blob']) if hasattr(user['avatar_blob'], 'tobytes') else user['avatar_blob']
        response = make_response(avatar_data)
        response.headers.set('Content-Type', 'image/jpeg')
        response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
        return response
    return '', 404

def make_blob_response(blob_data, content_type='image/jpeg'):
    """Convert PostgreSQL BYTEA (memoryview) to Flask response"""
    if blob_data is None:
        return None
    # Convert memoryview to bytes if needed
    if hasattr(blob_data, 'tobytes'):
        blob_data = blob_data.tobytes()
    elif isinstance(blob_data, memoryview):
        blob_data = bytes(blob_data)
    response = make_response(blob_data)
    response.headers.set('Content-Type', content_type)
    response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
    return response

# ============================================================
# COVER ROUTES - Store as BLOB in database
# ============================================================
# Eileen's Route - Upload custom cover image
@app.route('/cover-image')
def cover_image():
    """Serve cover image from database BLOB - PERSISTENT storage"""
    if 'user_id' not in session:
        return '', 404

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT cover_blob FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()

    if user and user['cover_blob']:
        cover_data = bytes(user['cover_blob']) if hasattr(user['cover_blob'], 'tobytes') else user['cover_blob']
        response = make_response(cover_data)
        response.headers.set('Content-Type', 'image/jpeg')
        response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
        return response
    return '', 404

@app.route('/update-cover', methods=['POST'])

def update_cover():
    """Upload cover and store directly as BLOB in database"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if 'cover_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['cover_image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    # Read image as binary data directly into database
    image_data = file.read()

    # Limit image size to 5MB
    if len(image_data) > 5 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Image too large (max 5MB)'}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute('UPDATE users SET cover_blob = %s WHERE id = %s', 
                (image_data, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})


# ============================================================
# BACKGROUND ROUTES - Store as TEXT in database
# ============================================================
# Eileen's Route - Save custom background image
@app.route('/save-background-preset', methods=['POST'])
def save_background_preset():
    """Save background preset (color/gradient) - PERSISTENT storage"""
    if 'user_id' not in session:
        return jsonify({'success': False}), 401

    data = request.get_json()
    bg_type = data.get('bg_type', 'default')
    bg_value = data.get('bg_value')

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        UPDATE users SET background_type = %s, background_value = %s WHERE id = %s
    ''', (bg_type, bg_value, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

# ============================================================
# Eileen's Route - Upload custom background image
# ============================================================
@app.route('/upload-background', methods=['POST'])
def upload_background():
    """Upload custom background image and store as data URL in database"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if 'bg_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['bg_image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    # Read image as binary data
    image_data = file.read()

    if len(image_data) > 5 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Image too large (max 5MB)'}), 400

    # Convert binary to data URL for storage
    mime_type = file.content_type or 'image/jpeg'
    bg_value = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('utf-8')}"

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        UPDATE users SET background_type = %s, background_value = %s WHERE id = %s
    ''', ('image', bg_value, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    return jsonify({
        'success': True,
        'bg_value': bg_value
    })


@app.route('/api/user/background')
def api_user_background():
    """Get user background data for cross-device sync"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT background_type, background_value
        FROM users WHERE id = %s
    ''', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()

    if user:
        return jsonify({
            'success': True,
            'background_type': user['background_type'],
            'background_value': user['background_value']
        })
    return jsonify({'success': False, 'error': 'User not found'}), 404


# ============================================================
# API ENDPOINTS
# ============================================================
# Eileen's Route - Api for purchase
@app.route('/api/user/purchases')
def api_user_purchases():
    if 'user_id' not in session:
        return jsonify([])
    
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT o.id, o.product_id, o.offer_price as price,
               o.status, o.meeting_point as meetup_location, o.created_at,
               p.name,
               u.username as seller_name
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON p.seller_id = u.id
        WHERE o.buyer_id = %s
        ORDER BY o.created_at DESC
    ''', (session['user_id'],))
    rows = cur.fetchall()
    cur.close()
    db.close()
    
    purchases = []
    for row in rows:
        item = dict(row)
        item['emoji'] = get_emoji_by_category(item['name'])
        purchases.append(item)
    
    return jsonify(purchases)


# Eileen's Route - Api for listing
@app.route('/api/user/listings')
def api_user_listings():
    """Get user's product listings with first image from blob or disk"""
    if 'user_id' not in session:
        return jsonify([])
    
    import json as _json

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT p.id, p.name, p.price, p.status, p.created_at, 
               p.images, p.images_blob, p.condition,
               CASE p.category
                   WHEN 'books' THEN '📚'
                   WHEN 'gadgets' THEN '💻'
                   WHEN 'dorm' THEN '🛏️'
                   WHEN 'fashion' THEN '👕'
                   WHEN 'beauty' THEN '💄'
                   WHEN 'sports' THEN '⚽'
                   WHEN 'groceries' THEN '🛒'
                   WHEN 'stationery' THEN '✏️'
                   WHEN 'music' THEN '🎸'
                   ELSE '📦'
               END as emoji
        FROM products p
        WHERE p.seller_id = %s
        ORDER BY p.created_at DESC
    """, (session['user_id'],))
    rows = cur.fetchall()
    cur.close()
    db.close()
    
    listings = []
    
    for row in rows:
        item = dict(row)
        first_image = None
        is_video = False

        # Priority 1: Use images_blob (base64) - most reliable source
        images_blob = item.get('images_blob')
        if images_blob:
            try:
                blob_list = _json.loads(images_blob) if isinstance(images_blob, str) else images_blob
                if isinstance(blob_list, list) and len(blob_list) > 0:
                    first_blob = blob_list[0]
                    if isinstance(first_blob, str) and first_blob.startswith('data:'):
                        first_image = first_blob
                        is_video = first_blob.startswith('data:video/')
            except Exception as e:
                print(f"Error parsing images_blob for listing: {e}")

        # Priority 2: Fallback to disk files
        if not first_image and item.get('images'):
            img_str = item['images']
            if img_str:
                img_list = [x.strip() for x in img_str.split(',') if x.strip()]
                if img_list:
                    first_image = '/static/uploads/' + img_list[0]
                    ext = img_list[0].split('.')[-1].lower()
                    is_video = ext in ['mp4', 'webm', 'mov', 'avi', 'mkv']

        # Remove heavy blob from response to keep it lightweight
        item.pop('images_blob', None)
        item['first_image'] = first_image
        item['first_image_is_video'] = is_video
        listings.append(item)
    
    return jsonify(listings)

# ============================================================
# OFFER SYSTEM API ROUTES
# ============================================================

@app.route('/api/product/<int:product_id>/offers')
def get_product_offers(product_id):
    """Get all offers for a product (seller only)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    # Verify product belongs to user
    cur.execute('SELECT seller_id FROM products WHERE id = %s', (product_id,))
    product = cur.fetchone()
    if not product or product['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'error': 'Unauthorized'}), 403
    
    cur.execute('''
        SELECT o.*, u.username as buyer_name
        FROM offers o
        JOIN users u ON o.buyer_id = u.id
        WHERE o.product_id = %s
        ORDER BY o.created_at DESC
    ''', (product_id,))
    offers = cur.fetchall()
    cur.close()
    db.close()
    
    # Add offer_count to product for listing display
    offer_count = len(offers)
    
    result = []
    for offer in offers:
        offer_dict = dict(offer)
        result.append(offer_dict)
    
    return jsonify(result)


@app.route('/api/product/<int:product_id>/offer-count')
def get_product_offer_count(product_id):
    """Get offer count for a product"""
    if 'user_id' not in session:
        return jsonify({'count': 0})
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT COUNT(*) AS count FROM offers WHERE product_id = %s', (product_id,))
    row = cur.fetchone()
    count = row['count'] if row else 0
    cur.close()
    db.close()
    
    return jsonify({'count': count})


@app.route('/api/product/<int:product_id>/offers/send', methods=['POST'])
def send_offer(product_id):
    """Send an offer for a product (buyer)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    offer_price = data.get('offer_price')
    message = data.get('message', '')
    
    if not offer_price or float(offer_price) <= 0:
        return jsonify({'success': False, 'error': 'Invalid offer price'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    # Get product info
    cur.execute('SELECT id, name, price, seller_id FROM products WHERE id = %s AND status = "approved"', (product_id,))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    # Check if buyer is not the seller
    if product['seller_id'] == session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'You cannot make an offer on your own product'}), 400
    
    # Check if offer already exists
    cur.execute('SELECT id FROM offers WHERE product_id = %s AND buyer_id = %s AND status = "pending"', (product_id, session['user_id']))
    existing = cur.fetchone()
    
    if existing:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'You already have a pending offer for this product'}), 400
    
    # Create offer
    cur.execute('''
        INSERT INTO offers (product_id, buyer_id, offer_price, original_price, message, status)
        VALUES (%s, %s, %s, %s, %s, 'pending')
    ''', (product_id, session['user_id'], float(offer_price), product['price'], message))
    
    # Create notification for seller
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at)
        VALUES (%s, %s, NOW())
    ''', (product['seller_id'],
          f"New offer of RM {float(offer_price):.2f} on your item: {product['name']}"))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'message': 'Offer sent successfully'})


@app.route('/api/offer/<int:offer_id>/accept', methods=['POST'])
def accept_offer(offer_id):
    """Accept an offer (seller)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Get offer details
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id, p.id as product_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found'}), 404
    
    # Verify seller
    if offer['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Update offer status
    cur.execute('UPDATE offers SET status = "accepted" WHERE id = %s', (offer_id,))
    
    # Mark product as sold
    cur.execute('UPDATE products SET status = "sold" WHERE id = %s', (offer['product_id'],))
    
    # Create notification for buyer
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at)
        VALUES (%s, %s, NOW())
    ''', (offer['buyer_id'],
          f"Your offer of RM {offer['offer_price']:.2f} for {offer['product_name']} has been accepted!"))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})


@app.route('/api/offer/<int:offer_id>/reject', methods=['POST'])
def reject_offer(offer_id):
    """Reject an offer (seller)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Get offer details
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found'}), 404
    
    # Verify seller
    if offer['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Update offer status
    cur.execute('UPDATE offers SET status = "rejected" WHERE id = %s', (offer_id,))
    
    # Create notification for buyer
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at)
        VALUES (%s, %s, NOW())
    ''', (offer['buyer_id'],
          f"Your offer of RM {offer['offer_price']:.2f} for {offer['product_name']} was rejected."))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})


@app.route('/api/offer/<int:offer_id>/counter', methods=['POST'])
def counter_offer(offer_id):
    """Counter an offer (seller)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    counter_price = data.get('counter_price')
    
    if not counter_price or float(counter_price) <= 0:
        return jsonify({'success': False, 'error': 'Invalid counter price'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    # Get offer details
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found'}), 404
    
    # Verify seller
    if offer['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Create counter offer (insert new offer or update)
    cur.execute('''
        UPDATE offers 
        SET counter_price = %s, status = 'countered'
        WHERE id = %s
    ''', (float(counter_price), offer_id))
    
    # Create notification for buyer
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at)
        VALUES (%s, %s, NOW())
    ''', (offer['buyer_id'],
          f"Seller countered your offer for {offer['product_name']}: RM {float(counter_price):.2f}"))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})


@app.route('/api/offer/<int:offer_id>/accept-counter', methods=['POST'])
def accept_counter_offer(offer_id):
    """Accept a counter offer (buyer)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Get offer details
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found'}), 404
    
    # Verify buyer
    if offer['buyer_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Update offer with counter price as accepted
    cur.execute('''
        UPDATE offers 
        SET offer_price = counter_price, status = 'accepted', counter_price = NULL
        WHERE id = %s
    ''', (offer_id,))
    
    # Mark product as sold
    cur.execute('UPDATE products SET status = "sold" WHERE id = %s', (offer['product_id'],))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

# ============================================================
# PRODUCT API FOR EDIT/DELETE
# ============================================================
# Eileen's Route - Get product
@app.route('/api/product/<int:product_id>')

def api_get_product(product_id):
    """Get product details for editing"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT id, name, price, description, condition, category, images, images_blob, status
        FROM products
        WHERE id = %s AND seller_id = %s
    ''', (product_id, session['user_id']))
    product = cur.fetchone()
    cur.close()
    db.close()

    if not product:
        return jsonify({'error': 'Product not found'}), 404

    import json as _json
    result = dict(product)

    # Normalize images_blob → always a JSON string (list of base64 data URIs)
    blob = result.get('images_blob')
    if blob:
        try:
            parsed = _json.loads(blob) if isinstance(blob, str) else blob
            if isinstance(parsed, list):
                result['images_blob'] = _json.dumps(parsed)
            elif isinstance(parsed, str) and parsed.startswith('data:'):
                result['images_blob'] = _json.dumps([parsed])
            else:
                result['images_blob'] = None
        except Exception:
            result['images_blob'] = None
    else:
        result['images_blob'] = None

    return jsonify(result)

# ============================================================
# Serve individual product image by product_id + index
# Used by _product_card.html so we don't embed base64 in HTML attrs
# ============================================================
@app.route('/api/product-image/<int:product_id>/<int:index>')

def api_product_image(product_id, index):
    """Serve a single product image as binary (avoids putting base64 in HTML)"""
    import json as _json
    import base64
    
    db = get_db()
    cur = db.cursor()

    cur.execute('SELECT images_blob, images FROM products WHERE id = %s', (product_id,))
    row = cur.fetchone()
    cur.close()
    db.close()

    if not row:
        return '', 404

    # Try images_blob first
    if row.get('images_blob'):
        try:
            blob_list = _json.loads(row['images_blob']) if isinstance(row['images_blob'], str) else row['images_blob']
            if isinstance(blob_list, list) and index < len(blob_list):
                data_uri = blob_list[index]
                if isinstance(data_uri, str) and data_uri.startswith('data:'):
                    header, b64data = data_uri.split(',', 1)
                    mime_type = header.split(';')[0].split(':')[1]
                    img_bytes = base64.b64decode(b64data)
                    response = make_response(img_bytes)
                    response.headers.set('Content-Type', mime_type)
                    response.headers.set('Cache-Control', 'public, max-age=604800')
                    return response
        except Exception as e:
            print(f"Error serving product image: {e}")

    # Fallback: disk file
    if row.get('images'):
        parts = [p.strip() for p in row['images'].split(',') if p.strip()]
        if parts and index < len(parts):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], parts[index])
            if os.path.exists(filepath):
                from flask import send_file
                return send_file(filepath)

    return '', 404
# ============================================================
# Eileen's Route - Update product
# ============================================================
@app.route('/api/product/<int:product_id>/update', methods=['PUT'])

def api_update_product(product_id):
    """Update product details"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json()

    name = data.get('name', '').strip()
    price = data.get('price', 0)
    description = data.get('description', '').strip()
    condition = data.get('condition', '')
    category = data.get('category', '')

    errors = []
    if not name:
        errors.append('Name is required')
    if price <= 0:
        errors.append('Valid price is required')
    if not description:
        errors.append('Description is required')

    if errors:
        return jsonify({'success': False, 'error': ', '.join(errors)}), 400

    db = get_db()
    cur = db.cursor()

    # Verify product belongs to user
    cur.execute('SELECT id FROM products WHERE id = %s AND seller_id = %s', (product_id, session['user_id']))
    product = cur.fetchone()
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404

    # Update product (status becomes pending again for admin review)
    cur.execute('''
        UPDATE products
        SET name = %s, price = %s, description = %s, condition = %s, category = %s, status = 'pending'
        WHERE id = %s
    ''', (name, price, description, condition, category, product_id))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

# ============================================================
# Eileen's route - update product full
# ============================================================
@app.route('/api/product/<int:product_id>/update-full', methods=['POST'])
def api_update_product_full(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Session expired. Please login again.'}), 401

    db = get_db()
    cur = db.cursor()
    
    # Verify product belongs to user
    cur.execute('SELECT id, images FROM products WHERE id = %s AND seller_id = %s', 
                (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404

    name = request.form.get('name', '').strip()
    price = request.form.get('price', 0)
    description = request.form.get('description', '').strip()
    condition = request.form.get('condition', '')
    category = request.form.get('category', '')
    images_blob_json = request.form.get('images_blob', '')

    if not name or not price or not description:
        return jsonify({'success': False, 'error': 'Name, price and description required'}), 400

    try:
        price = float(price)
    except:
        return jsonify({'success': False, 'error': 'Invalid price'}), 400

    # Server-side media count limit
    import json, base64, uuid
    MAX_MEDIA = 12
    if images_blob_json:
        try:
            blob_check = json.loads(images_blob_json)
            if isinstance(blob_check, list) and len(blob_check) > MAX_MEDIA:
                return jsonify({'success': False,
                                'error': f'Maximum {MAX_MEDIA} media files allowed.'}), 400
        except Exception:
            pass

    # Process Base64 data and save to disk
    saved_filenames = []

    if images_blob_json:
        try:
            blob_list = json.loads(images_blob_json)
            for idx, blob in enumerate(blob_list):
                if not isinstance(blob, str) or not blob.startswith('data:'):
                    continue
                header, b64data = blob.split(',', 1)
                mime_type = header.split(';')[0].split(':')[1]
                ext_map = {
                    'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif', 'image/webp': 'webp',
                    'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov'
                }
                ext = ext_map.get(mime_type, 'bin')
                if ext == 'bin':
                    continue
                file_data = base64.b64decode(b64data)
                unique_name = f"product_{product_id}_{uuid.uuid4().hex}.{ext}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
                with open(save_path, 'wb') as f:
                    f.write(file_data)
                saved_filenames.append(unique_name)
        except Exception as e:
            print(f"Error processing images_blob: {e}")
            saved_filenames = []

    images_str = ','.join(saved_filenames)

    cur.execute('''
        UPDATE products
        SET name = %s, price = %s, description = %s, condition = %s, category = %s,
            images = %s, images_blob = %s, status = 'pending'
        WHERE id = %s
    ''', (name, price, description, condition, category,
          images_str, images_blob_json, product_id))
    
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})


@app.route('/api/product/<int:product_id>/upload-images', methods=['POST'])
def upload_product_images(product_id):
    """Upload new images for a product"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Verify product belongs to user
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT id FROM products WHERE id = %s AND seller_id = %s', 
                (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    # Get existing images
    existing_images = request.form.get('existing_images', '[]')
    import json
    existing = json.loads(existing_images)
    
    # Upload new images
    new_files = request.files.getlist('new_images')
    for file in new_files:
        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
            filename = secure_filename(f"product_{product_id}_{uuid.uuid4().hex}.{ext}")
            file.save(os.path.join('static/uploads', filename))
            existing.append(filename)
    
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'all_images': existing})

# ============================================================
# Eileen's Route - My profile
# ============================================================
@app.route('/my-profile')
def my_profile():

    if 'user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))

    db = get_db()
    user_id = session['user_id']
    cur = db.cursor()

    cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    user = cur.fetchone()

    if not user:
        session.clear()
        flash('User not found', 'error')
        return redirect(url_for('login'))

    cur.execute('SELECT COUNT(*) FROM products WHERE seller_id = %s', (user_id,))
    listing_count = cur.fetchone()['count'] 

    sold_count = 0
    try:
        cur.execute('SELECT COUNT(*) FROM orders WHERE seller_id = %s AND status = "completed"', (user_id,))
        sold_count = cur.fetchone()['count']  
    except:
        pass

    trust_score = calculate_trust_score(user, listing_count)

    # ========== calculate response_rate ==========
    response_rate = 50
    if listing_count > 0:
        response_rate += 15
    
    if user['bio'] and user['contact']:
        response_rate += 10
    if user['active_hours'] and user['active_hours'] != 'Not set':
        response_rate += 10
    if user['avatar_blob']:
        response_rate += 5
    
    response_rate = min(response_rate, 98)
    response_rate = max(response_rate, 40)
    # ========================================

    cur.close()
    db.close()

    return render_template(
        'my_profile.html',
        user=user,
        listing_count=listing_count,
        sold_count=sold_count,
        trust_score=trust_score,
        response_rate=response_rate  
    )

# ============================================================
# Eileen's Route - Edit Profile
# ============================================================
@app.route('/edit_profile', methods=['GET'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()

    cur.execute('SELECT COUNT(*) FROM products WHERE seller_id = %s', (session['user_id'],))
    listing_count = cur.fetchone()['count']  

    trust_score = calculate_trust_score(user, listing_count)

    response_rate = 50
    if listing_count > 0:
        response_rate += 15
    
    if user['bio'] and user['contact']:
        response_rate += 10
    if user['active_hours'] and user['active_hours'] != 'Not set':
        response_rate += 10
    if user['avatar_blob']:
        response_rate += 5
    
    response_rate = min(response_rate, 98)
    response_rate = max(response_rate, 40)

    cur.close()
    db.close()

    return render_template(
        'edit_profile.html',
        user=user,
        listing_count=listing_count,
        sold_count=0,
        trust_score=trust_score,
        response_rate=response_rate
    )

# ============================================================
# Check if user is admin - API endpoint
# ============================================================
@app.route('/api/user/is-admin')
def api_user_is_admin():
    """Check if current user is an admin"""
    if 'user_id' not in session:
        return jsonify({'is_admin': False}), 401
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT is_admin FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    if user and user['is_admin'] == 1:
        return jsonify({'is_admin': True})
    return jsonify({'is_admin': False})


# ============================================================
# Switch to Admin Dashboard
# ============================================================
@app.route('/switch-to-admin')
def switch_to_admin():
    """Switch from user session to admin session"""
    if 'user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT is_admin, email, username FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    if user and user['is_admin'] == 1:
        # Set admin session
        session['admin_logged_in'] = True
        session['admin_email'] = user['email']
        session['admin_username'] = user['username']
        flash('Switched to Admin mode', 'success')
        return redirect(url_for('admin_dashboard'))
    else:
        flash('You do not have admin privileges', 'error')
        return redirect(url_for('edit_profile'))
    
# ============================================================
# Eileen's Route - Update Profile
# ============================================================
@app.route('/update-profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    username = request.form.get('username')
    full_name = request.form.get('full_name')
    bio = request.form.get('bio')
    contact = request.form.get('contact')
    gender = request.form.get('gender')
    active_hours = request.form.get('active_hours')

    db = get_db()
    cur = db.cursor()

    # Check if username already taken
    cur.execute('SELECT id FROM users WHERE username = %s AND id != %s', (username, session['user_id']))
    existing = cur.fetchone()
    if existing:
        cur.close()
        db.close()
        flash('Username already taken', 'error')
        return redirect(url_for('edit_profile'))

    # Update all fields
    cur.execute("""
        UPDATE users
        SET username = %s, full_name = %s, bio = %s,
            contact = %s, gender = %s, active_hours = %s
        WHERE id = %s
    """, (username, full_name, bio, contact, gender, active_hours, session['user_id']))

    db.commit()
    cur.close()
    db.close()

    session['username'] = username
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('edit_profile'))


# ============================================================
# Eileen's Route - Change Password
# ============================================================
@app.route('/change-password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()

    if not user:
        cur.close()
        db.close()
        flash('User not found', 'error')
        return redirect(url_for('edit_profile'))

    if not check_password_hash(user['password'], current_password):
        cur.close()
        db.close()
        flash('Current password is incorrect', 'error')
        return redirect(url_for('edit_profile'))

    if new_password != confirm_password:
        cur.close()
        db.close()
        flash('New passwords do not match', 'error')
        return redirect(url_for('edit_profile'))

    hashed = generate_password_hash(new_password)
    cur.execute('UPDATE users SET password = %s WHERE id = %s', (hashed, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    flash('Password changed successfully!', 'success')
    return redirect(url_for('edit_profile'))


# ============================================================
# Eileen's Route - Delete Account
# ============================================================
@app.route('/delete-account', methods=['POST'])
def delete_account():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    password = request.form.get('password')
    confirm_text = request.form.get('confirm_text')

    if confirm_text != 'DELETE':
        flash('Please type DELETE to confirm', 'error')
        return redirect(url_for('edit_profile'))

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()

    if not check_password_hash(user['password'], password):
        cur.close()
        db.close()
        flash('Password is incorrect', 'error')
        return redirect(url_for('edit_profile'))

    cur.execute('DELETE FROM products WHERE seller_id = %s', (session['user_id'],))
    cur.execute('DELETE FROM orders WHERE buyer_id = %s OR seller_id = %s', (session['user_id'], session['user_id']))
    cur.execute('DELETE FROM notifications WHERE user_id = %s', (session['user_id'],))
    cur.execute('DELETE FROM users WHERE id = %s', (session['user_id'],))
    db.commit()
    cur.close()
    db.close()

    session.clear()

    # In delete_account function, after deleting user data
    # Also clear any remember_token cookie
    response = redirect(url_for('login'))
    response.set_cookie('remember_token', '', expires=0)

    flash('Your account has been permanently deleted', 'info')
    return response


# ============================================================
# Eileen's Route - Verify Password
# ============================================================
@app.route('/verify-password', methods=['POST'])
def verify_password():
    if 'user_id' not in session:
        return jsonify({'valid': False}), 401

    data = request.get_json()
    password = data.get('password', '')

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT password FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()

    if user and check_password_hash(user['password'], password):
        return jsonify({'valid': True})
    else:
        return jsonify({'valid': False})


# ============================================================
# Eileen's Route - Forgot Password
# ============================================================
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        step = request.form.get('step')

        # Step 1: verify email
        if step == '1':
            email = request.form.get('fp_email', '').strip()
            if not email:
                flash('Please enter your email.', 'error')
                return render_template('forgot_password.html')
            if not email.endswith('@student.mmu.edu.my'):
                flash('Only @student.mmu.edu.my emails are allowed.', 'error')
                return render_template('forgot_password.html')

            db = get_db()
            cur = db.cursor()
            cur.execute('SELECT id, security_q1, security_q2 FROM users WHERE email = %s', (email,))
            user = cur.fetchone()
            cur.close()
            db.close()

            if not user:
                flash('No account found with that email.', 'error')
                return render_template('forgot_password.html')

            session['fp_email'] = email
            session['fp_q1'] = user['security_q1']
            session['fp_q2'] = user['security_q2']
            return render_template(
                'forgot_password.html',
                step=2,
                q1=user['security_q1'],
                q2=user['security_q2']
            )

        # Step 2: verify security answers
        elif step == '2':
            email = session.get('fp_email')
            if not email:
                flash('Session expired. Please start again.', 'error')
                return render_template('forgot_password.html')

            a1_input = request.form.get('fp_a1', '').strip().lower()
            a2_input = request.form.get('fp_a2', '').strip().lower()

            db = get_db()
            cur = db.cursor()
            cur.execute('SELECT id, security_a1, security_a2 FROM users WHERE email = %s', (email,))
            user = cur.fetchone()
            cur.close()
            db.close()

            if not user:
                flash('User not found.', 'error')
                return render_template('forgot_password.html')

            if (a1_input != user['security_a1'] or
                a2_input != user['security_a2']):
                flash('One or both answers are incorrect.', 'error')
                return render_template(
                    'forgot_password.html',
                    step=2,
                    q1=session.get('fp_q1'),
                    q2=session.get('fp_q2')
                )

            session['fp_verified'] = True
            return render_template('forgot_password.html', step=3)

        # Step 3: save new password
        elif step == '3':
            if not session.get('fp_verified'):
                flash('Please complete identity verification first.', 'error')
                return render_template('forgot_password.html')

            email = session.get('fp_email')
            new_password = request.form.get('fp_pw', '')
            confirm_password = request.form.get('fp_cpw', '')

            errors = []
            if len(new_password) < 8:
                errors.append('Password must be at least 8 characters')
            if not re.search(r'[A-Z]', new_password):
                err = 'Password must contain at least 1 uppercase letter'
                errors.append(err)
            if not re.search(r'[a-z]', new_password):
                err = 'Password must contain at least 1 lowercase letter'
                errors.append(err)
            if not re.search(r'[0-9]', new_password):
                errors.append('Password must contain at least 1 number')
            if not re.search(r'[!@#$%^&*]', new_password):
                err = 'Password must contain at least 1 special character'
                errors.append(err)
            if new_password != confirm_password:
                errors.append('Passwords do not match')

            if errors:
                for e in errors:
                    flash(e, 'error')
                return render_template('forgot_password.html', step=3)

            hashed = generate_password_hash(new_password)
            db = get_db()
            cur = db.cursor()
            cur.execute('UPDATE users SET password = %s WHERE email = %s', (hashed, email))
            db.commit()
            cur.close()
            db.close()

            session.pop('fp_email', None)
            session.pop('fp_q1', None)
            session.pop('fp_q2', None)
            session.pop('fp_verified', None)

            flash('Password reset successfully!', 'success')
            return redirect(url_for('login'))

    return render_template('forgot_password.html')


# ============================================================
# Eileen's Route - Admin Login
# ============================================================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember_me = request.form.get('remember_me') 

        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s AND is_admin = 1', (email,))
        user = cur.fetchone()
        cur.close()
        db.close()

        # ✅ user 现在是字典，用字符串键名访问
        if user and check_password_hash(user['password'], password):  # 用 'password' 不是 5
            session['admin_logged_in'] = True
            session['admin_email'] = user['email']
            session['admin_username'] = user['username']
            
            if remember_me:
                import secrets
                token = secrets.token_urlsafe(64)
                db = get_db()
                cur = db.cursor()
                cur.execute('UPDATE users SET remember_token = %s WHERE id = %s', (token, user['id']))
                db.commit()
                cur.close()
                db.close()
                response = redirect(url_for('admin_dashboard'))
                response.set_cookie('admin_remember_token', token, 
                                    max_age=30*24*60*60, httponly=True, secure=False)
                flash('Admin login successful!', 'success')
                return response
            else:
                db = get_db()
                cur = db.cursor()
                cur.execute('UPDATE users SET remember_token = NULL WHERE id = %s', (user['id'],))
                db.commit()
                cur.close()
                db.close()
                response = redirect(url_for('admin_dashboard'))
                response.set_cookie('admin_remember_token', '', expires=0)
                flash('Admin login successful!', 'success')
                return response
        else:
            flash('Invalid admin credentials', 'error')

    return render_template('admin_login.html')

@app.before_request
def check_admin_remember_me():
    if session.get('admin_logged_in'):
        return
    
    public_routes = [
        'login', 'admin_login', 'register', 'forgot_password', 'static', 'welcome']
    if request.endpoint in public_routes:
        return
    
    token = request.cookies.get('admin_remember_token')
    if not token:
        return
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT id, email, username, is_admin FROM users WHERE remember_token = %s AND is_admin = 1', (token,))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    if user:
        session['admin_logged_in'] = True
        session['admin_email'] = user['email']      # 修复：用字典键名
        session['admin_username'] = user['username'] # 修复：用字典键名
        print(f"Auto-logged in admin: {user['username']}")
        
@app.route('/logout')
def logout():
    # Clear admin token if exists
    if session.get('admin_logged_in'):
        db = get_db()
        cur = db.cursor()
        cur.execute('UPDATE users SET remember_token = NULL WHERE email = %s', (session.get('admin_email'),))
        db.commit()
        cur.close()
        db.close()
        response = redirect(url_for('login'))
        response.set_cookie('admin_remember_token', '', expires=0)
        session.clear()
        flash('Admin logged out', 'info')
        return response
    
    # Clear user token if exists
    if session.get('user_id'):
        db = get_db()
        cur = db.cursor()
        cur.execute('UPDATE users SET remember_token = NULL WHERE id = %s', (session['user_id'],))
        db.commit()
        cur.close()
        db.close()
        response = redirect(url_for('login'))
        response.set_cookie('remember_token', '', expires=0)
    
    session.clear()
    flash('Logged out', 'info')
    return redirect(url_for('login'))

# ============================================================
# Keting's Route - Admin Dashboard
# ============================================================
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        flash('Please login as admin first', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT COUNT(*) FROM products")
    total_products = cur.fetchone()['count']  

    # Total registered users
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()['count']

    # Approved products count
    cur.execute("SELECT COUNT(*) FROM products WHERE status = 'approved'")
    approved_count = cur.fetchone()['count']

    # Pending products count
    cur.execute("SELECT COUNT(*) FROM products WHERE status = 'pending'")
    pending_count = cur.fetchone()['count']

    # Active sellers count (users with at least one product)
    cur.execute("SELECT COUNT(DISTINCT seller_id) FROM products")
    seller_count = cur.fetchone()['count']

    cur.close()
    db.close()

    return render_template("admin_dashboard.html",
                           total_users=total_users,
                           approved_count=approved_count,
                           pending_count=pending_count,
                           seller_count=seller_count)


@app.route('/admin/users')
def admin_users():
    if not session.get('admin_logged_in'):
        flash('Please login as admin first', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    cur.execute('''
    SELECT r.*, u.username as reported_username,
           rp.username as reporter_username
    FROM reports r
    JOIN users u ON r.reported_user_id = u.id
    JOIN users rp ON r.reporter_id = rp.id
    WHERE r.status = 'pending'
    ORDER BY r.created_at DESC
                ''')
    reports = cur.fetchall()
    cur.close()
    
    db.close()
    return render_template("admin_users.html", users=users, reports=reports)


@app.route('/admin/products')
def admin_products():
    if not session.get('admin_logged_in'):
        flash('Please login as admin first', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'pending' ORDER BY p.created_at DESC
    ''')
    pending = cur.fetchall()

    cur.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'approved' ORDER BY p.created_at DESC
    ''')
    approved = cur.fetchall()

    cur.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'rejected' ORDER BY p.created_at DESC
    ''')
    rejected = cur.fetchall()
    
    # Convert database rows to Python dictionaries
    pending = [dict(row) for row in pending]
    approved = [dict(row) for row in approved]
    rejected = [dict(row) for row in rejected]

    cur.close()
    db.close()

    return render_template("admin_product.html",
                           pending_list=pending,
                           approved_list=approved,
                           rejected_list=rejected)


# Approve product
@app.route('/admin/product/approve/<int:pid>')
def approve_product(pid):
    if not session.get('admin_logged_in'):
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        UPDATE products
        SET status = 'approved', reject_reason = ''
        WHERE id = %s
    ''', (pid,))

    db.commit()
    cur.close()
    db.close()

    flash("Product approved successfully, now visible on homepage", "success")
    return redirect(url_for('admin_products'))


# Reject product with reason
@app.route('/admin/product/reject/<int:pid>', methods=['POST'])
def reject_product(pid):
    if not session.get('admin_logged_in'):
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_login'))

    reject_reason = request.form.get('reject_reason', '').strip()
    if not reject_reason:
        flash("Please provide a reason for rejection", "error")
        return redirect(url_for('admin_products'))

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        UPDATE products
        SET status = 'rejected', reject_reason = %s
        WHERE id = %s
    ''', (reject_reason, pid))

    db.commit()
    cur.close()
    db.close()

    flash("Product rejected successfully", "success")
    return redirect(url_for('admin_products'))


# Admin API - Get product info for modal
@app.route('/admin/api/product/<int:pid>')
def admin_get_product_info(pid):
    if not session.get('admin_logged_in'):
        return {"error": "no permission"}, 403

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.id = %s
    ''', (pid,))
    product = cur.fetchone()
    cur.close()
    db.close()

    if not product:
        return {"error": "not found"}, 404

    product_dict = dict(product)

    # Parse images_blob (JSON array of base64 data URIs)
    import json as _json
    images_list = []
    if product_dict.get('images_blob'):
        try:
            images_list = _json.loads(product_dict['images_blob'])
        except Exception:
            # Fallback: treat as single item
            images_list = [product_dict['images_blob']]

    # Fallback: if no base64 blobs, try to build URLs from disk filenames
    if not images_list and product_dict.get('images'):
        for fname in product_dict['images'].split(','):
            fname = fname.strip()
            if fname:
                images_list.append(f"/static/uploads/{fname}")

    product_dict['images_list'] = images_list
    return product_dict


# Freeze user for 7 days(limited 3 times)
@app.route("/admin/user/<int:user_id>/freeze", methods=["POST"])
def freeze_7day(user_id):
    if not session.get("admin_logged_in"):
        flash("Unauthorized", "error")
        return redirect(url_for("admin_login"))

    reason = request.form.get('reason', 'No reason provided').strip()
    now = datetime.now()
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute("SELECT freeze_count, is_blocked FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    
    if not user:
        cur.close()
        db.close()
        flash("User not found", "error")
        return redirect(url_for("admin_users"))
    
    if user['is_blocked'] == 1:
        cur.close()
        db.close()
        flash("User is already permanently blocked", "error")
        return redirect(url_for("admin_users"))
    
    freeze_count = user['freeze_count'] if user['freeze_count'] else 0
    
    if freeze_count >= 3:
        cur.execute("UPDATE users SET is_blocked = 1, is_frozen = 0 WHERE id = %s", (user_id,))
        cur.execute("""
            INSERT INTO notifications (user_id, message, created_at)
            VALUES (%s, %s, NOW())
        """, (user_id,
              f"🚫 Your account has been PERMANENTLY BLOCKED after 3 freezes.\n"
              f"Reason: Your account reached the maximum freeze limit (3/3).\n"
              f"If you believe this is a mistake, please contact admin."))
        db.commit()
        cur.close()
        db.close()
        flash("User permanently blocked after 3 freezes.", "warning")
        return redirect(url_for("admin_users"))
    
    frozen_end_time = now + timedelta(days=7)
    time_str = frozen_end_time.strftime("%Y-%m-%d %H:%M:%S")
    
    cur.execute("""
        UPDATE users
        SET is_frozen = 1, frozen_until = %s, freeze_reason = %s, freeze_count = freeze_count + 1
        WHERE id = %s
    """, (time_str, reason, user_id))

    cur.execute("""
        INSERT INTO notifications (user_id, message, created_at)
        VALUES (%s, %s, NOW())
    """, (user_id,
          f"⚠️ Your account has been frozen for 7 days (Freeze {freeze_count + 1}/3).\n"
          f"Reason: {reason}\n"
          f"Auto unfreeze: {time_str}\n"
          f"After 3 freezes, your account will be permanently blocked."))

    db.commit()
    cur.close()
    db.close()
    
    flash(f"User frozen (Freeze {freeze_count + 1}/3). Notification sent.", "success")
    return redirect(url_for("admin_users"))

# Block user permanently
@app.route('/admin/user/<int:user_id>/block', methods=['POST'])
def block_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    reason = request.form.get('reason', 'No reason provided')
    
    db = get_db()
    cur = db.cursor()

    cur.execute("UPDATE users SET is_blocked = 1, is_frozen = 0 WHERE id = %s", (user_id,))
    cur.execute("""
        INSERT INTO notifications (user_id, message, created_at)
        VALUES (%s, %s, NOW())
    """, (user_id,
          f"🚫 Your account has been PERMANENTLY BLOCKED by admin.\n"
          f"Reason: {reason}\n"
          f"If you believe this is a mistake, please contact admin."))

    db.commit()
    cur.close()
    db.close()
    
    flash("User permanently blocked. Notification sent.", "success")
    return redirect(url_for('admin_users'))


@app.route("/admin/unfreeze/<int:user_id>", methods=["POST"])
def unfreeze_user(user_id):
    if not session.get("admin_logged_in"):
        flash("Unauthorized", "error")
        return redirect(url_for("admin_login"))

    reason = request.form.get('reason', 'Manual unfreeze').strip()

    db = get_db()
    cur = db.cursor()
    
    cur.execute("""
        UPDATE users
        SET is_frozen = 0, frozen_until = NULL, freeze_reason = NULL,
            freeze_count = CASE WHEN freeze_count > 0 THEN freeze_count - 1 ELSE 0 END
        WHERE id = %s
    """, (user_id,))
    
    cur.execute("""
        INSERT INTO notifications (user_id, message, created_at)
        VALUES (%s, %s, NOW())
    """, (user_id,
          f"🔓 Your account has been manually unfrozen by admin.\n"
          f"Reason: {reason}\n"
          f"Your freeze count has been reduced by 1.\n"
          f"After 3 freezes, your account will be permanently blocked."))

    db.commit()
    cur.close()
    db.close()

    flash("User unfrozen. Freeze count reduced by 1. Notification sent.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/unblock/<int:user_id>", methods=["POST"])
def unblock_user(user_id):
    if not session.get("admin_logged_in"):
        flash("Unauthorized", "error")
        return redirect(url_for("admin_login"))

    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE users SET is_blocked = 0, freeze_count = 0 WHERE id = %s", (user_id,))
    cur.execute("""
        INSERT INTO notifications (user_id, message, created_at)
        VALUES (%s, %s, NOW())
    """, (user_id,
          f"✅ Your account has been UNBLOCKED by admin.\n"
          f"Your freeze count has been reset to 0.\n"
          f"Welcome back! Please follow the community guidelines."))
    db.commit()
    cur.close()
    db.close()

    flash("User unblocked. Notification sent.", "success")
    return redirect(url_for("admin_users"))


@app.route('/admin/report/<int:report_id>/<action>', methods=['POST'])
def handle_report(report_id, action):
    if not session.get('admin_logged_in'):
        return jsonify({'success': False}), 403

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM reports WHERE id = %s", (report_id,))
    report = cur.fetchone()
    
    if not report:
        cur.close()
        db.close()
        return jsonify({'success': False}), 404

    if action == 'dismiss':
        cur.execute("UPDATE reports SET status = 'dismissed' WHERE id = %s", (report_id,))
        cur.execute("""
            INSERT INTO notifications (user_id, message, created_at)
            VALUES (%s, %s, NOW())
        """, (report['reporter_id'],
              f"📋 Your report has been reviewed and DISMISSED by admin.\nNo action was taken."))
              
    elif action == 'block':
        cur.execute("UPDATE users SET is_blocked = 1 WHERE id = %s", (report['reported_user_id'],))
        cur.execute("UPDATE reports SET status = 'resolved' WHERE id = %s", (report_id,))
        
        cur.execute("""
            INSERT INTO notifications (user_id, message, created_at)
            VALUES (%s, %s, NOW())
        """, (report['reported_user_id'],
              f"🚫 Your account has been BLOCKED due to user reports.\nIf you believe this is a mistake, please contact admin."))
        
        cur.execute("""
            INSERT INTO notifications (user_id, message, created_at)
            VALUES (%s, %s, NOW())
        """, (report['reporter_id'],
              f"✅ Your report has been reviewed. The reported user has been BLOCKED.\nThank you!"))

    db.commit()
    cur.close()
    db.close()
    return jsonify({'success': True})



# ============================================================
# Keting's Route - Chat List
# ============================================================
# ==================== Keting's Chat Routes ====================
@app.route('/chat/send', methods=['POST'])
def chat_send():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    data = request.get_json()
    receiver_id = data.get('receiver_id')
    product_id = data.get('product_id', 0)
    content = data.get('content', '').strip()

    if not receiver_id or not content:
        return jsonify({'success': False, 'error': 'Missing data'})

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        INSERT INTO messages (sender_id, receiver_id, product_id, content, created_at)
        VALUES (%s, %s, %s, %s, NOW())
    ''', (session['user_id'], int(receiver_id), int(product_id) if product_id else None, content))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})


# ========== 多发图片（你的）==========
@app.route('/chat/send-images', methods=['POST'])
def chat_send_images():
    if 'user_id' not in session:
        return jsonify({'success': False}), 401

    receiver_id = request.form.get('receiver_id')
    content = request.form.get('content', '').strip()
    files = request.files.getlist('images')

    if not receiver_id or not files:
        return jsonify({'success': False}), 400

    filenames = []
    for file in files[:3]:
        filename = secure_filename("chat_" + str(session['user_id']) + "_" + uuid.uuid4().hex + ".jpg")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        filenames.append(filename)

    db = get_db()
    cur = db.cursor()
    cur.execute('''
    INSERT INTO messages (sender_id, receiver_id, content, image, created_at)
    VALUES (%s, %s, %s, %s, NOW())
    ''', (session['user_id'], int(receiver_id), content, ','.join(filenames)))
    db.commit()
    cur.close()
    db.commit()
    db.close()

    return jsonify({'success': True})


# ========== 单发图片（组员的）==========
@app.route('/chat/send-image', methods=['POST'])
def chat_send_image():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    receiver_id = request.form.get('receiver_id')
    product_id = request.form.get('product_id', 0)
    file = request.files.get('image')

    if not receiver_id or not file:
        return jsonify({'success': False, 'error': 'Missing data'}), 400

    filename = secure_filename("chat_" + str(session['user_id']) + "_" + uuid.uuid4().hex + ".jpg")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    db = get_db()
    cur = db.cursor()
    cur.execute('''
    INSERT INTO messages (sender_id, receiver_id, product_id, content, image, created_at)
    VALUES (%s, %s, %s, %s, %s, NOW())
    ''', (session['user_id'], int(receiver_id), int(product_id) if product_id else None, '', filename))
    db.commit()
    cur.close()
    db.commit()
    db.close()

    return jsonify({'success': True})

@app.route('/chat/<int:other_user_id>')
@app.route('/chat/<int:other_user_id>/<int:product_id>')
def chat_page(other_user_id, product_id=None):
    if 'user_id' not in session:
        flash("Please login first", "error")
        return redirect(url_for('login'))

    db = get_db()
    cur = db.cursor()
    
    # 更新当前用户最后上线时间
    cur.execute('UPDATE users SET last_seen = %s WHERE id = %s',
           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['user_id']))
    db.commit()
    
    # 对方用户信息
    cur.execute('SELECT * FROM users WHERE id = %s', (other_user_id,))
    other_user = cur.fetchone()
    if not other_user:
        cur.close()
        db.close()
        flash("User not found", "error")
        return redirect(url_for('home'))

    # 关联商品信息
    product_info = None
    if product_id:
        cur.execute('''
            SELECT p.*, u.username as seller_name
            FROM products p JOIN users u ON p.seller_id = u.id
            WHERE p.id = %s
        ''', (product_id,))
        product_info = cur.fetchone()

    # 历史消息
    cur.execute('''
        SELECT * FROM messages
        WHERE (sender_id = %s AND receiver_id = %s)
           OR (sender_id = %s AND receiver_id = %s)
        ORDER BY created_at ASC
    ''', (session['user_id'], other_user_id, other_user_id, session['user_id']))
    messages = cur.fetchall()

    # 标记对方消息为已读
    cur.execute('''
        UPDATE messages SET is_read = 1
        WHERE sender_id = %s AND receiver_id = %s AND is_read = 0
    ''', (other_user_id, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    return render_template('chat_page.html',
                           other_user=other_user,
                           product_info=product_info,
                           messages=messages)


@app.route('/api/chat/messages/<int:other_user_id>')
def chat_get_messages(other_user_id):
    if 'user_id' not in session:
        return jsonify([])

    since = request.args.get('since', 0, type=int)
    
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT * FROM messages
        WHERE ((sender_id = %s AND receiver_id = %s)
            OR (sender_id = %s AND receiver_id = %s))
          AND id > %s
        ORDER BY created_at ASC
    ''', (session['user_id'], other_user_id, other_user_id, session['user_id'], since))
    messages = cur.fetchall()
    cur.close()
    db.close()

    return jsonify([dict(row) for row in messages])

@app.route('/report-user/<int:user_id>', methods=['POST'])
def report_user(user_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    reason = data.get('reason', '').strip()
    details = data.get('details', '').strip()
    
    if not reason:
        return jsonify({'success': False, 'error': 'Reason required'}), 400
    
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        INSERT INTO reports (reporter_id, reported_user_id, reason, details)
        VALUES (%s, %s, %s, %s)
    ''', (session['user_id'], user_id, reason, details))
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

@app.route('/api/user/<int:user_id>/status')
def user_status(user_id):
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT last_seen FROM users WHERE id = %s', (user_id,))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    if not user:
        return jsonify({'online': False, 'last_seen': ''})
    
    last_seen = user['last_seen']
    if last_seen:
        try:
            if isinstance(last_seen, str):
                last_dt = datetime.strptime(last_seen[:19], '%Y-%m-%d %H:%M:%S')
            else:
                last_dt = last_seen
            diff = (datetime.now() - last_dt).seconds
            online = diff < 300
        except:
            online = False
    else:
        online = False
    
    return jsonify({
        'online': online,
        'last_seen': str(last_seen)[:19] if last_seen else 'Unknown'
    })



@app.route('/chatlist')
def chat_list():
    if 'user_id' not in session:
        flash("Please login first", "error")
        return redirect(url_for('login'))

    db = get_db()
    user_id = session['user_id']
    cur = db.cursor()

    # 用户聊天列表 - 关键修复：使用 avatar_blob 而不是 avatar
    cur.execute('''
        SELECT u.id, u.username, u.full_name, u.avatar_blob,
               m.content as last_message, m.image as last_image,
               m.created_at as last_time,
               m.is_read, m.sender_id,
               (SELECT COUNT(*) FROM messages
                WHERE sender_id = u.id AND receiver_id = %s AND is_read = 0) as unread_count
        FROM users u
        JOIN (
            SELECT CASE WHEN sender_id = %s THEN receiver_id ELSE sender_id END as other_id,
                   MAX(id) as max_id
            FROM messages
            WHERE sender_id = %s OR receiver_id = %s
            GROUP BY other_id
        ) latest ON u.id = latest.other_id
        JOIN messages m ON m.id = latest.max_id
        ORDER BY m.created_at DESC
    ''', (user_id, user_id, user_id, user_id))
    chats = cur.fetchall()
    
    chat_list_data = []
    for chat in chats:
        chat = dict(chat)
        if chat.get('last_image'):
            chat['last_message'] = '(Picture)'
        elif chat.get('last_message') and 'Tap to view product' in (chat.get('last_message') or ''):
            chat['last_message'] = '(Product)'
        chat_list_data.append(chat)

    # 未读通知数
    cur.execute("SELECT COUNT(*) AS count FROM notifications WHERE user_id = %s AND is_read = 0", (user_id,))
    unread_notifications = cur.fetchone()['count']

    # 未读评论数（暂用0）
    unread_reviews = 0
    
    cur.close()
    db.close()

    return render_template('user_chatlist.html', 
                           chats=chat_list_data,
                           unread_notifications=unread_notifications,
                           unread_reviews=unread_reviews)

# 系统公告列表
@app.route('/announcements')
def announcements():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM announcements ORDER BY created_at DESC')
    anns = cur.fetchall()
    cur.close()
    db.close()
    return render_template('announcements.html', announcements=anns)


# 管理员发公告
@app.route('/admin/announcement/add', methods=['POST'])
def add_announcement():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    if title and content:
        db = get_db()
        cur = db.cursor()
        cur.execute('INSERT INTO announcements (title, content) VALUES (%s, %s)', (title, content))
        db.commit()
        cur.close()
        db.close()
    return redirect(url_for('admin_dashboard'))


# 导航栏未读数量 API
@app.route('/api/unread-count')
def unread_count():
    if 'user_id' not in session:
        return jsonify({'chat': 0, 'notifications': 0})

    user_id = session['user_id']
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT COUNT(*) AS count FROM messages WHERE receiver_id = %s AND is_read = 0", (user_id,))
    chat_unread = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) AS count FROM notifications WHERE user_id = %s AND is_read = 0", (user_id,))
    notif_unread = cur.fetchone()['count']

    cur.close()
    db.close()
    return jsonify({'chat': chat_unread, 'notifications': notif_unread})

# ============================================================
# Xingru's Route - Upload Product
# ============================================================
@app.route('/upload', methods=['GET', 'POST'])

def upload_product():
    if 'user_id' not in session:
        flash("You must be logged in to post an item.", "error")
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form.get('item_name', '').strip()
        price = request.form.get('item_price', '').strip()
        description = request.form.get('item_desc', '').strip()
        condition = request.form.get('item_condition')
        category = request.form.get('item_category')
        seller_id = session['user_id']

        errors = []
        if not name:
            errors.append("Item name is required.")
        if not price:
            errors.append("Price is required.")
        elif not price.replace('.', '').isdigit() or float(price) < 0:
            errors.append("Please enter a valid price (positive number).")
        if not description:
            errors.append("Description is required.")
        if not category or category == "":
            errors.append("Please select a category.")
        if not condition:
            errors.append("Please select a condition.")

        price_val = None
        try:
            price_val = float(price)
            if price_val < 0:
                errors.append("Price cannot be negative.")
            elif price_val > 9999999:
                errors.append("Price cannot exceed RM 9,999,999.")
            else:
                price_val = round(price_val, 2)
        except ValueError:
            errors.append("Please enter a valid price.")

        import base64
        import json

        MIME_MAP = {
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
            'gif': 'image/gif', 'webp': 'image/webp', 'bmp': 'image/bmp',
            'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/mp4',
        }

        files = request.files.getlist('product_images')
        images_base64 = []
        image_filenames = []

        for file in files:
            if not file or not file.filename:
                continue

            # Read all data first
            file_data = file.read()

            # Skip empty or oversized files (50MB per file)
            if not file_data or len(file_data) > 50 * 1024 * 1024:
                continue

            # Determine extension and mime type
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
            mime_type = MIME_MAP.get(ext, 'image/jpeg')

            # Build base64 data URI
            base64_str = base64.b64encode(file_data).decode('utf-8')
            images_base64.append(f"data:{mime_type};base64,{base64_str}")

            # Also save to disk as backup (for product detail page)
            filename = secure_filename(file.filename)
            if not filename or filename.strip() == '':
                filename = f"media_{uuid.uuid4().hex}.{ext}"
            # Ensure unique filename to avoid collisions
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            with open(save_path, 'wb') as f:
                f.write(file_data)
            image_filenames.append(unique_filename)
        
        if not images_base64:
            errors.append("Please upload at least one photo or video.")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template('upload.html')

        images_json = json.dumps(images_base64)
        images_string = ",".join(image_filenames)
        
        db = get_db()
        cur = db.cursor()
        cur.execute('''
            INSERT INTO products (seller_id, name, price, description, condition, category, images, images_blob, created_at, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
        ''', (seller_id, name, price_val, description, condition, category, images_string, images_json, 'pending'))
        db.commit()
        cur.close()
        db.close()

        flash("Your item has been submitted for admin approval.", "success")
        return redirect(url_for('home'))

    return render_template('upload.html')

# ============================================================
# Xingru's Route - Testing (Clear products)
# ============================================================
@app.route('/clear-products')
def clear_products():
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM products")
    # Reset sequence in PostgreSQL: ALTER SEQUENCE products_id_seq RESTART WITH 1
    try:
        cur.execute("ALTER SEQUENCE products_id_seq RESTART WITH 1")
    except:
        pass
    db.commit()
    cur.close()
    db.close()
    return "All products deleted."


# ============================================================
# Xingru's Route - Product Details
# ============================================================
@app.route('/product/<int:product_id>')
def product_detail(product_id):
    if 'user_id' not in session:
        flash('Please login to view product details.', 'error')
        return redirect(url_for('login'))

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT p.*, u.username as seller_name, u.full_name as seller_full_name,
            u.avatar_blob as seller_avatar, u.id as seller_id, u.created_at as user_joined
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.id = %s AND p.status = 'approved'
    ''', (product_id,))
    product = cur.fetchone()
    cur.close()
    db.close()

    if not product:
        flash('Product not found or not yet approved.', 'error')
        return redirect(url_for('home'))

    import json
    images_blob_str = product.get('images_blob', '[]')
    images = []
    if images_blob_str and images_blob_str != '[]':
        try:
            images = json.loads(images_blob_str)
            # Keep only valid base64 data URLs
            images = [img for img in images if img.startswith('data:')]
        except:
            pass
    # Fallback to file-based images if no base64
    if not images and product.get('images'):
        images = product['images'].split(',') if product['images'] else []

    return render_template('product.html', product=product, images=images)


# ============================================================
# Xingru's Route - Temporary route for testing product page only
# ============================================================
@app.route('/user/<int:user_id>')
def user_profile(user_id):
    if 'user_id' not in session:
        flash('Please login to view profiles.', 'error')
        return redirect(url_for('login'))
    flash('Profile page is under construction.', 'info')
    return redirect(url_for('home'))


if __name__ == '__main__':
    app.run(debug=True)