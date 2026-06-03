import re
import subprocess
import os
from datetime import datetime, timedelta
import uuid
import base64
import json
import secrets
import random

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

# Initialize SQLite database (creates tables if missing)
init_db()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024      # 100MB max upload size
app.config['MAX_FORM_MEMORY_SIZE'] = 100 * 1024 * 1024  
app.config['MAX_FORM_PARTS'] = 1000   

# ============================================================
# Helper functions
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

    # 修复：正确计算用户加入天数
    if user['created_at']:
        try:
            ca = user['created_at']
            if isinstance(ca, str):
                created_date = datetime.strptime(ca[:19], '%Y-%m-%d %H:%M:%S')
            else:
                created_date = ca
            
            # 确保时区处理正确
            if hasattr(created_date, 'tzinfo') and created_date.tzinfo is not None:
                created_date = created_date.replace(tzinfo=None)
            
            now = datetime.now()
            days_since_join = (now - created_date).days
            
            # 根据天数加分
            if days_since_join >= 365:
                trust_score += 20
            elif days_since_join >= 180:
                trust_score += 15
            elif days_since_join >= 30:
                trust_score += 10
            elif days_since_join >= 7:
                trust_score += 5
            # 新用户不加分，也不减分
                
        except Exception as e:
            print(f"Error calculating days since join: {e}")
            # 出错时默认不加分

    trust_score += min(25, (listing_count // 2) * 2)

    if user['active_hours'] and user['active_hours'] != 'Not set':
        trust_score += 10
    if user['gender']:
        trust_score += 5

    trust_score = min(trust_score, 100)
    trust_score = max(trust_score, 30)
    
    return trust_score

def create_notification(user_id, message, notif_type='general', related_id=None, product_id=None):
    """统一的创建通知函数"""
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, product_id, is_read)
            VALUES (%s, %s, NOW(), %s, %s, %s, 0)
        ''', (user_id, message, notif_type, related_id, product_id))
        db.commit()
        cur.close()
        db.close()
        return True
    except Exception as e:
        print(f"Create notification error: {e}")
        return False

@app.template_filter('time_since')
def time_since(date):
    if not date:
        return 'Just joined'
    now = datetime.now()
    if isinstance(date, str):
        try:
            date = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
        except:
            return 'Just joined'
    
    # 确保没有时区问题
    if hasattr(date, 'tzinfo') and date.tzinfo is not None:
        date = date.replace(tzinfo=None)
    
    diff = now - date
    
    if diff.days > 365:
        return f"{diff.days//365} year{'s' if diff.days//365 > 1 else ''}"
    elif diff.days > 30:
        return f"{diff.days//30} month{'s' if diff.days//30 > 1 else ''}"
    elif diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''}"
    elif diff.days == 0:
        return 'Just joined'
    else:
        return 'Just joined'
    
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

@app.template_filter('campus_abbr')
def campus_abbr(campus):
    if not campus:
        return ''
    if 'Cyberjaya' in campus:
        return 'CYBER'
    if 'Melaka' in campus:
        return 'MLK'
    return ''

# Setup folder for uploaded product images
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize the database
init_products()
init_messages()
init_announcements()
init_reviews()

# ============================================================
# Routes
# ============================================================
@app.route('/')
def index():
    return render_template('welcome.html')  
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember_me = request.form.get('remember_me')
        
        if not email.endswith('@student.mmu.edu.my'):
            flash('Only @student.mmu.edu.my email addresses are allowed', 'error')
            return render_template('login.html')
        
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT * FROM users WHERE LOWER(email) = LOWER(%s)', (email,))
        user = cur.fetchone()
        cur.close()
        db.close()
        
        if user and check_password_hash(user['password'], password):
            if user['is_blocked'] == 1:
                flash('❌ This account is permanently blocked. Contact admin for appeal.', 'danger')
                return redirect(url_for('login'))

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
            
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['student_id'] = user['student_id']

            if remember_me:
                token = secrets.token_urlsafe(64)
                db = get_db()
                cur = db.cursor()
                cur.execute('UPDATE users SET remember_token = %s WHERE id = %s', (token, user['id']))
                db.commit()
                cur.close()
                db.close()
                response = redirect(url_for('home'))
                response.set_cookie('remember_token', token, max_age=30*24*60*60, httponly=True, secure=False)
                flash('Login successful!', 'success')
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
                flash('Login successful!', 'success')
                return response
        else:
            flash('Invalid email or password', 'error')
            return render_template('login.html')

    return render_template('login.html')

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
def check_upcoming_meetings():
    if 'user_id' not in session:
        return
    user_id = session['user_id']
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT id, order_number, meeting_point, meeting_time
        FROM orders
        WHERE (buyer_id = %s OR seller_id = %s)
          AND status IN ('confirmed', 'delivered')
          AND DATE(meeting_time) <= CURRENT_DATE + INTERVAL '1 day'
          AND DATE(meeting_time) >= CURRENT_DATE
          AND (last_reminder_sent IS NULL OR last_reminder_sent < CURRENT_DATE)
        LIMIT 1
    ''', (user_id, user_id))
    orders_to_remind = cur.fetchall()
    for ord in orders_to_remind:
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
            VALUES (%s, %s, NOW(), 'order', %s, 0)
        ''', (user_id,
              f"📅 Reminder: Order #{ord['order_number']} has a meetup scheduled for {ord['meeting_time']} at {ord['meeting_point']}. Please be on time!",
              ord['id']))
    db.commit()
    cur.close()
    db.close()

@app.before_request
def check_remember_me():
    if 'user_id' in session:
        return
    
    public_routes = ['login', 'register', 'forgot_password', 'static', 'welcome', 'admin_login']
    if request.endpoint in public_routes:
        return
    
    token = request.cookies.get('remember_token')
    if not token:
        return
    
    try:
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
    except Exception as e:
        print(f"Error in check_remember_me: {e}")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        gender = request.form.get('gender')

        q1 = request.form.get('q1', '').strip()
        a1 = request.form.get('a1', '').strip().lower()
        q2 = request.form.get('q2', '').strip()
        a2 = request.form.get('a2', '').strip().lower()

        errors = []

        if not student_id or len(student_id) != 10:
            errors.append('Please enter a valid Student ID (10 characters)')
        elif not student_id.replace(' ', '').isalnum():
            errors.append('Student ID must contain only letters and numbers')

        if not email:
            errors.append('Email is required')
        elif not (email.endswith('@student.mmu.edu.my')):
            err = 'Only MMU email addresses are allowed (@student.mmu.edu.my)'
            errors.append(err)

        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters')

        if not password:
            errors.append('Password is required')
        else:
            if len(password) < 8:
                errors.append('Password must be at least 8 characters')
            if not re.search(r'[A-Z]', password):
                errors.append('Password must contain at least 1 uppercase letter')
            if not re.search(r'[a-z]', password):
                errors.append('Password must contain at least 1 lowercase letter')
            if not re.search(r'[0-9]', password):
                errors.append('Password must contain at least 1 number')
            if not re.search(r'[!@#$%^&*]', password):
                errors.append('Password must contain at least 1 special character')

        if password != confirm_password:
            errors.append('Passwords do not match')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html')

        db = get_db()
        cur = db.cursor()

        cur.execute('SELECT * FROM users WHERE student_id = %s OR LOWER(email) = LOWER(%s)', (student_id, email))
        existing = cur.fetchone()
        if existing:
            cur.close()
            db.close()
            flash('Student ID or Email already registered', 'error')
            return render_template('register.html')

        cur.execute('SELECT * FROM users WHERE LOWER(username) = LOWER(%s)', (username,))
        username_exists = cur.fetchone()
        if username_exists:
            cur.close()
            db.close()
            flash('Username already taken. Please choose another one.', 'error')
            return render_template('register.html')

        hashed_password = generate_password_hash(password)
        cur.execute('''
            INSERT INTO users (
                student_id, email, username, password, gender,
                security_q1, security_a1, security_q2, security_a2
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (student_id, email, username, hashed_password, gender,
              q1, a1, q2, a2))
        
        db.commit()
        
        cur.execute('SELECT id FROM users WHERE email = %s', (email,))
        new_user = cur.fetchone()
        
        if new_user:
            create_notification(
                user_id=new_user['id'],
                message='🎉 Welcome to E-bye! Complete your profile to increase your trust score.',
                notif_type='welcome'
            )
        
        cur.close()
        db.close()

        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/home')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT p.*, u.username as seller_name, u.full_name as seller_full_name, u.id as seller_id, u.campus as seller_campus
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.status IN ('approved') AND u.is_blocked = 0
        ORDER BY p.created_at DESC
    ''')
    products_data = cur.fetchall()
    cur.close()
    db.close()

    products = []
    for row in products_data:
        product = dict(row)
        images_str = product.get('images', '')
        images_blob_str = product.get('images_blob', '[]')
        
        base64_list = []
        if images_blob_str and images_blob_str != '[]':
            try:
                base64_list = json.loads(images_blob_str)
                base64_list = [img for img in base64_list if img.startswith('data:')]
            except:
                base64_list = []
        
        if images_str:
            img_list = images_str.split(',')
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
        
        product['images_base64_list'] = base64_list
        if base64_list:
            product['actual_total'] = len(base64_list)
        products.append(product)

    return render_template('home.html',
        username=session.get('username'), latest_products=products)

@app.route('/search')
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    keyword = request.args.get('q', '').strip()
    
    campus_raw = request.args.get('campus', '')
    if campus_raw:
        campuses = [c.strip() for c in campus_raw.split(',') if c.strip() and c != 'all']
    else:
        campuses = []

    categories_raw = request.args.get('category', '')
    if categories_raw:
        categories = [c.strip() for c in categories_raw.split(',') if c.strip()]
    else:
        categories = []
    
    condition_raw = request.args.get('condition', '')
    if condition_raw:
        conditions = [c.strip() for c in condition_raw.split(',') if c.strip()]
    else:
        conditions = []
    
    status_raw = request.args.get('status', '')
    if status_raw:
        statuses = [s.strip() for s in status_raw.split(',') if s.strip()]
    else:
        statuses = ['approved', 'sold', 'reserved']
    
    date_range = request.args.get('date_range')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)

    query = """
        SELECT p.*, u.username as seller_name, u.full_name as seller_full_name, u.id as seller_id, u.campus as seller_campus
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.status IN ({})
          AND u.is_blocked = 0
    """.format(','.join(['%s']*len(statuses)))
    
    params = []
    params.extend(statuses)

    if keyword:
        # Make the keyword space‑flexible for all fields
        flexible_keyword = keyword.replace(' ', '%')
        like_flex = f"%{flexible_keyword}%"
        query += """ AND (p.name ILIKE %s 
                        OR p.description ILIKE %s
                        OR u.username ILIKE %s
                        OR u.full_name ILIKE %s)"""
        params.extend([like_flex, like_flex, like_flex, like_flex])

    if campuses:
        campus_conditions = []
        for c in campuses:
            campus_conditions.append("u.campus ILIKE %s")
            params.append(f"%{c}%")
        query += " AND (" + " OR ".join(campus_conditions) + ")"

    if categories:
        placeholders = ','.join(['%s'] * len(categories))
        query += f" AND p.category IN ({placeholders})"
        params.extend(categories)

    if conditions:
        placeholders = ','.join(['%s'] * len(conditions))
        query += f" AND p.condition IN ({placeholders})"
        params.extend(conditions)

    if date_range and date_range.isdigit():
        days = int(date_range)
        query += " AND p.created_at >= NOW() - (%s * INTERVAL '1 day')"
        params.append(days)
    else:
        if date_from:
            query += " AND p.created_at >= %s"
            params.append(date_from)
        if date_to:
            query += " AND p.created_at <= %s"
            params.append(date_to + " 23:59:59")

    if min_price is not None:
        query += " AND p.price >= %s"
        params.append(min_price)
    if max_price is not None:
        query += " AND p.price <= %s"
        params.append(max_price)

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

    products = []
    for row in products_data:
        product = dict(row)
        images_str = product.get('images', '')
        images_blob_str = product.get('images_blob', '[]')
        
        base64_list = []
        if images_blob_str and images_blob_str != '[]':
            try:
                base64_list = json.loads(images_blob_str)
                base64_list = [img for img in base64_list if img.startswith('data:')]
            except:
                base64_list = []
        
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
        
        product['images_base64_list'] = base64_list
        if base64_list:
            product['actual_total'] = len(base64_list)
        products.append(product)

    user_results = []
    if keyword:
        db_u = get_db()
        cur_u = db_u.cursor()
        # transform the keyword for user search: replace spaces with %
        user_like = f"%{keyword.replace(' ', '%')}%"

        cur_u.execute("""
            SELECT id, username, full_name FROM users
            WHERE is_blocked = 0
            AND (username ILIKE %s OR full_name ILIKE %s)
            ORDER BY username ASC
            LIMIT 50
        """, (user_like, user_like))
        user_results = cur_u.fetchall()
        cur_u.close()
        db_u.close()

    return render_template('search.html', products=products, user_results=user_results)

@app.route('/avatar-image')
def avatar_image():
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

@app.route('/update-profile-avatar', methods=['POST'])
def update_profile_avatar():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400

    image_data = file.read()

    if len(image_data) > 2 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Image too large (max 2MB)'}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute('UPDATE users SET avatar_blob = %s WHERE id = %s', (image_data, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

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
    if blob_data is None:
        return None
    if hasattr(blob_data, 'tobytes'):
        blob_data = blob_data.tobytes()
    elif isinstance(blob_data, memoryview):
        blob_data = bytes(blob_data)
    response = make_response(blob_data)
    response.headers.set('Content-Type', content_type)
    response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
    return response

@app.route('/cover-image')
def cover_image():
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
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if 'cover_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['cover_image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    image_data = file.read()

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

@app.route('/save-background-preset', methods=['POST'])
def save_background_preset():
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

@app.route('/upload-background', methods=['POST'])
def upload_background():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if 'bg_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['bg_image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    image_data = file.read()

    if len(image_data) > 5 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Image too large (max 5MB)'}), 400

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
@app.route('/api/user/purchases')
def api_user_purchases():
    if 'user_id' not in session:
        return jsonify([])
    
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT o.id, o.product_id, o.offer_price as price,
               o.status, o.meeting_point as meetup_location, o.created_at,
               p.name, p.images, p.images_blob,
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
        
        # gain product picture
        product_image = None
        images_blob = item.get('images_blob')
        if images_blob:
            try:
                blob_list = json.loads(images_blob) if isinstance(images_blob, str) else images_blob
                if isinstance(blob_list, list) and len(blob_list) > 0:
                    first_blob = blob_list[0]
                    if isinstance(first_blob, str) and first_blob.startswith('data:'):
                        product_image = first_blob
            except Exception as e:
                print(f"Error parsing images_blob for purchase: {e}")
        
        if not product_image and item.get('images'):
            img_str = item['images']
            if img_str:
                img_list = [x.strip() for x in img_str.split(',') if x.strip()]
                if img_list:
                    product_image = '/static/uploads/' + img_list[0]
        
        item['product_image'] = product_image
        # 移除大字段
        item.pop('images_blob', None)
        item.pop('images', None)
        purchases.append(item)
    
    return jsonify(purchases)

@app.route('/api/user/listings')
def api_user_listings():
    if 'user_id' not in session:
        return jsonify([])
    
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

        images_blob = item.get('images_blob')
        if images_blob:
            try:
                blob_list = json.loads(images_blob) if isinstance(images_blob, str) else images_blob
                if isinstance(blob_list, list) and len(blob_list) > 0:
                    first_blob = blob_list[0]
                    if isinstance(first_blob, str) and first_blob.startswith('data:'):
                        first_image = first_blob
                        is_video = first_blob.startswith('data:video/')
            except Exception as e:
                print(f"Error parsing images_blob for listing: {e}")

        if not first_image and item.get('images'):
            img_str = item['images']
            if img_str:
                img_list = [x.strip() for x in img_str.split(',') if x.strip()]
                if img_list:
                    first_image = '/static/uploads/' + img_list[0]
                    ext = img_list[0].split('.')[-1].lower()
                    is_video = ext in ['mp4', 'webm', 'mov', 'avi', 'mkv']

        item.pop('images_blob', None)
        item['first_image'] = first_image
        item['first_image_is_video'] = is_video
        listings.append(item)
    
    return jsonify(listings)

@app.route('/api/order/<int:order_id>/confirm', methods=['POST'])
def api_confirm_order(order_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    meeting_point = data.get('meeting_point')
    meeting_time = data.get('meeting_time')
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('SELECT * FROM orders WHERE id = %s AND seller_id = %s', 
                (order_id, session['user_id']))
    order = cur.fetchone()
    
    if not order:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Order not found'}), 404
    
    cur.execute('''
        UPDATE orders 
        SET meeting_point = %s, meeting_time = %s, status = 'confirmed', updated_at = NOW()
        WHERE id = %s
    ''', (meeting_point, meeting_time, order_id))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'order', %s, 0)
    ''', (order['buyer_id'], 
          f" Order #{order['order_number']} has been CONFIRMED by seller! Meeting at: {meeting_point} on {meeting_time}",
          order_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

@app.route('/api/product/<int:product_id>/offers')
def get_product_offers(product_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
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
    
    result = []
    for offer in offers:
        offer_dict = dict(offer)
        result.append(offer_dict)
    
    return jsonify(result)

@app.route('/api/product/<int:product_id>/offer-count')
def get_product_offer_count(product_id):
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
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    offer_price = data.get('offer_price')
    message = data.get('message', '')
    
    if not offer_price or float(offer_price) <= 0:
        return jsonify({'success': False, 'error': 'Invalid offer price'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute("SELECT id, name, price, seller_id FROM products WHERE id = %s AND status = 'approved'", (product_id,))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    if product['seller_id'] == session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'You cannot make an offer on your own product'}), 400
    
    cur.execute("SELECT id FROM offers WHERE product_id = %s AND buyer_id = %s AND status = 'pending'", (product_id, session['user_id']))
    existing = cur.fetchone()
    
    if existing:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'You already have a pending offer for this product'}), 400
    
    cur.execute('''
        INSERT INTO offers (product_id, buyer_id, offer_price, original_price, message, status)
        VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING id
    ''', (product_id, session['user_id'], float(offer_price), product['price'], message))
    new_offer_id = cur.fetchone()['id']
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (product['seller_id'],
          f"💰 New offer of RM {float(offer_price):.2f} on your listing \"{product['name']}\". Go to My Listings → Offers to accept or decline.",
          'new_offer', new_offer_id))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (session['user_id'],
          f"Your offer of RM {float(offer_price):.2f} for \"{product['name']}\" has been sent to the seller. You'll be notified when they respond.",
          'offer_sent', new_offer_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'message': 'Offer sent successfully', 'offer_id': new_offer_id})

@app.route('/api/offer/<int:offer_id>/accept', methods=['POST'])
def api_accept_offer(offer_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = get_db()
    cur = db.cursor()

    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id, p.id as product_id, p.price as original_price
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()

    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found'}), 404

    if offer['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    cur.execute("UPDATE offers SET status = 'accepted' WHERE id = %s", (offer_id,))

    accept_price = float(offer['offer_price'])
    product_price = float(offer['original_price'])

    message = f"🎉 Offer ACCEPTED! Your offer of RM {accept_price:.2f} for \"{offer['product_name']}\" has been accepted by the seller. "
    if accept_price < product_price:
        message += f"Click 'Proceed to Checkout' to purchase at the agreed price (RM {accept_price:.2f})"
    else:
        message += f"Click 'Proceed to Checkout' to purchase at the original price (RM {product_price:.2f})"

    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['buyer_id'], message, 'offer_accepted', offer_id))

    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['seller_id'],
          f"You accepted the offer of RM {accept_price:.2f} for \"{offer['product_name']}\". Waiting for buyer to confirm checkout.",
          'offer_accept_confirm', offer_id))

    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True, 'offer_id': offer['id'], 'offer_price': offer['offer_price'],
                    'product_price': product_price, 'product_name': offer['product_name']})

@app.route('/api/offer/<int:offer_id>/reject', methods=['POST'])
def api_reject_offer(offer_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
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
    
    if offer['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    cur.execute("UPDATE offers SET status = 'rejected' WHERE id = %s", (offer_id,))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['buyer_id'],
          f"❌ Offer DECLINED. Your offer of RM {offer['offer_price']:.2f} for \"{offer['product_name']}\" was not accepted by the seller.",
          'offer_rejected', offer_id))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['seller_id'],
          f"🚫 You declined the offer of RM {offer['offer_price']:.2f} for \"{offer['product_name']}\".",
          'offer_reject_confirm', offer_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

@app.route('/api/offer/<int:offer_id>/counter', methods=['POST'])
def counter_offer(offer_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    counter_price = data.get('counter_price')
    
    if not counter_price or float(counter_price) <= 0:
        return jsonify({'success': False, 'error': 'Invalid counter price'}), 400
    
    db = get_db()
    cur = db.cursor()
    
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
    
    if offer['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    cur.execute('''
        UPDATE offers 
        SET counter_price = %s, status = 'countered'
        WHERE id = %s
    ''', (float(counter_price), offer_id))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['buyer_id'],
          f"Counter offer received! Seller countered your offer for \"{offer['product_name']}\" with RM {float(counter_price):.2f}. Go to My Profile → Purchases to accept or decline.",
          'offer_countered', offer_id))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['seller_id'],
          f" You sent a counter offer of RM {float(counter_price):.2f} for \"{offer['product_name']}\". Waiting for buyer's response.",
          'counter_sent', offer_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})
@app.route('/api/offer/<int:offer_id>/accept-counter', methods=['POST'])
def accept_counter_offer(offer_id):
    """Buyer accepts seller's counter offer"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json() or {}
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id, p.price as product_price
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.buyer_id = %s
    ''', (offer_id, session['user_id']))
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found'}), 404
    
    if offer['status'] != 'countered':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'No counter offer available'}), 400
    
    agreed_price = float(offer['counter_price'])
    
    cur.execute('''
        UPDATE offers 
        SET offer_price = %s, status = 'accepted', counter_price = NULL
        WHERE id = %s
    ''', (agreed_price, offer_id))
    
    # Notify seller
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'offer_accepted', %s, 0)
    ''', (offer['seller_id'],
          f"🎉 Buyer accepted your counter offer of RM {agreed_price:.2f} for \"{offer['product_name']}\". Waiting for checkout.",
          offer_id))
    
    # Notify buyer
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'offer_accepted', %s, 0)
    ''', (session['user_id'],
          f" Counter offer accepted! RM {agreed_price:.2f} for \"{offer['product_name']}\". Click 'Proceed to Checkout' to confirm your order.",
          offer_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'offer_id': offer_id, 'accepted_price': agreed_price})

@app.route('/api/offer/<int:offer_id>/reject-counter', methods=['POST'])
def reject_counter_offer(offer_id):
    """Buyer rejects seller's counter offer"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.buyer_id = %s AND o.status = 'countered'
    ''', (offer_id, session['user_id']))
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found or not countered'}), 404
    
    # 将状态改回 pending，清除 counter_price
    cur.execute("UPDATE offers SET status = 'pending', counter_price = NULL WHERE id = %s", (offer_id,))
    
    # 通知卖家
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'offer_rejected', %s, 0)
    ''', (offer['seller_id'],
          f"❌ Buyer rejected your counter offer of RM {offer['counter_price']:.2f} for \"{offer['product_name']}\". The original offer is still pending.",
          offer_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

@app.route('/api/user/offers')
def api_user_offers():
    if 'user_id' not in session:
        return jsonify([])
    
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT o.*, p.name as product_name, p.price as original_price, p.images_blob,
               u.username as seller_name, u.id as seller_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON p.seller_id = u.id
        WHERE o.buyer_id = %s
        ORDER BY o.created_at DESC
    ''', (session['user_id'],))
    rows = cur.fetchall()
    cur.close()
    db.close()
    
    result = []
    for row in rows:
        item = dict(row)
        product_image = None
        if item.get('images_blob'):
            try:
                blob_list = json.loads(item['images_blob']) if isinstance(item['images_blob'], str) else item['images_blob']
                if blob_list and len(blob_list) > 0:
                    product_image = blob_list[0]
            except:
                pass
        item['product_image'] = product_image
        item.pop('images_blob', None)
        result.append(item)
    
    return jsonify(result)

# 添加在 app.py 的 API ENDPOINTS 部分

@app.route('/api/current-user-id')
def api_current_user_id():
    if 'user_id' not in session:
        return jsonify({'user_id': None})
    return jsonify({'user_id': session['user_id']})

@app.route('/api/offer/<int:offer_id>/cancel', methods=['POST'])
def cancel_offer(offer_id):
    """买家取消自己的 pending offer"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('SELECT * FROM offers WHERE id = %s AND buyer_id = %s AND status = "pending"', 
                (offer_id, session['user_id']))
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found or cannot be cancelled'}), 404
    
    cur.execute('UPDATE offers SET status = "cancelled" WHERE id = %s', (offer_id,))
    
    # 获取产品信息以发送通知给卖家
    cur.execute('SELECT seller_id, name FROM products WHERE id = %s', (offer['product_id'],))
    product = cur.fetchone()
    
    if product:
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
            VALUES (%s, %s, NOW(), 'offer_cancelled', %s, 0)
        ''', (product['seller_id'],
              f"Buyer cancelled their offer of RM {offer['offer_price']:.2f} for \"{product['name']}\".",
              offer_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

@app.route('/api/offer/<int:offer_id>/cancel-counter', methods=['POST'])
def cancel_counter_offer(offer_id):
    """Buyer cancels their own counter offer, reverts to pending"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Check if offer exists and belongs to the buyer, and is in 'countered' status
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.buyer_id = %s AND o.status = 'countered'
    ''', (offer_id, session['user_id']))
    
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found or cannot be cancelled'}), 404
    
    # Revert to pending status and clear counter_price
    cur.execute("UPDATE offers SET status = 'pending', counter_price = NULL WHERE id = %s", (offer_id,))
    
    # Notify seller
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'offer_cancelled', %s, 0)
    ''', (offer['seller_id'],
          f" Buyer cancelled their counter offer for \"{offer['product_name']}\". The original offer of RM {offer['offer_price']:.2f} is still pending.",
          offer_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

@app.route('/api/offer/<int:offer_id>/create-order', methods=['POST'])
def api_create_order_from_offer(offer_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    meetup_locations = data.get('meetup_locations', [])
    
    if not meetup_locations:
        return jsonify({'success': False, 'error': 'Please select meetup locations'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id, p.price as product_price
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.buyer_id = %s AND o.status = 'accepted'
    ''', (offer_id, session['user_id']))
    
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found or not accepted'}), 404
    
    order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    
    cur.execute('''
        INSERT INTO orders (order_number, product_id, buyer_id, seller_id, offer_price,
                           meeting_point, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW()) RETURNING id
    ''', (order_number, offer['product_id'], offer['buyer_id'], offer['seller_id'],
          offer['offer_price'], ','.join(meetup_locations)))
    
    order_id = cur.fetchone()['id']
    
    cur.execute("UPDATE offers SET status = 'ordered' WHERE id = %s", (offer_id,))
    
    cur.execute("UPDATE products SET status = 'sold' WHERE id = %s", (offer['product_id'],))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['seller_id'],
          f"🛒 NEW ORDER #{order_number}! {session['username']} has placed an order for \"{offer['product_name']}\" at RM {offer['offer_price']:.2f}. Go to My Orders to confirm.",
          'order_created', order_id))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (session['user_id'],
          f"📋 Order #{order_number} created successfully for \"{offer['product_name']}\" at RM {offer['offer_price']:.2f}. Meetup: {', '.join(meetup_locations)}. Waiting for seller to confirm.",
          'order_created', order_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'order_id': order_id, 'order_number': order_number})

@app.route('/api/offer/<int:offer_id>/details', methods=['GET'])
def api_offer_details(offer_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT o.id, o.offer_price, o.status, o.counter_price,
               p.id as product_id, p.name as product_name, p.price as product_price,
               p.condition as product_condition, p.status as product_status,
               p.images_blob, p.images, p.seller_id, o.buyer_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()
    cur.close()
    db.close()
    
    if not offer:
        return jsonify({'success': False, 'error': 'Offer not found'}), 404
    
    product_image = None
    if offer.get('images_blob'):
        try:
            blob_list = json.loads(offer['images_blob']) if isinstance(offer['images_blob'], str) else offer['images_blob']
            if blob_list and len(blob_list) > 0:
                product_image = blob_list[0]
        except:
            pass
    
    if not product_image and offer.get('images'):
        img_str = offer['images']
        if img_str:
            img_list = [x.strip() for x in img_str.split(',') if x.strip()]
            if img_list:
                product_image = '/static/uploads/' + img_list[0]
    
    return jsonify({
        'success': True,
        'offer_id': offer['id'],
        'offer_price': float(offer['offer_price']),
        'status': offer['status'],
        'counter_price': float(offer['counter_price']) if offer['counter_price'] else None,
        'product_id': offer['product_id'],
        'product_name': offer['product_name'],
        'product_price': float(offer['product_price']),
        'product_condition': offer['product_condition'],
        'product_status': offer['product_status'],
        'product_image': product_image,
        'seller_id': offer['seller_id'],
        'buyer_id': offer['buyer_id']
    })

@app.route('/api/buy-now', methods=['POST'])
def api_buy_now():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    product_id = data.get('product_id')
    meetup_locations = data.get('meetup_locations', [])
    meeting_dates = data.get('meeting_dates', [])
    meeting_dates_str = ','.join(meeting_dates) if meeting_dates else ''

    if not product_id or not meetup_locations:
        return jsonify({'success': False, 'error': 'Missing required data'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute("SELECT id, name, price, seller_id FROM products WHERE id = %s AND status = 'approved'", (product_id,))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    if product['seller_id'] == session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'You cannot buy your own product'}), 400
    
    order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    
    cur.execute('''
        INSERT INTO orders (order_number, product_id, buyer_id, seller_id, offer_price,
                            meeting_point, meeting_time, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW())
        RETURNING id
    ''', (order_number, product_id, session['user_id'], product['seller_id'],
          product['price'], ','.join(meetup_locations), meeting_dates_str))
    
    order_id = cur.fetchone()['id']
    
    cur.execute("UPDATE products SET status = 'reserved' WHERE id = %s", (product_id,))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (product['seller_id'],
          f"🛒 BUY NOW — Order #{order_number}! {session['username']} purchased \"{product['name']}\" for RM {product['price']:.2f}. Preferred meetup: {', '.join(meetup_locations)}. Go to My Orders to confirm.",
          'order_created', order_id))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (session['user_id'],
          f"✅ Order #{order_number} placed for \"{product['name']}\" at RM {product['price']:.2f}. Meetup: {', '.join(meetup_locations)}. Waiting for seller to confirm.",
          'order_created', order_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'order_id': order_id, 'order_number': order_number})

@app.route('/notifications')
def notifications_page():
    if 'user_id' not in session:
        flash("Please login first", "error")
        return redirect(url_for('login'))
    return render_template('notifications.html')

@app.route('/api/notifications/unread')
def get_unread_notifications():
    if 'user_id' not in session:
        return jsonify([]), 401
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT * FROM notifications 
        WHERE user_id = %s AND is_read = 0
        ORDER BY created_at DESC
        LIMIT 50
    ''', (session['user_id'],))
    
    notifications = cur.fetchall()
    cur.close()
    db.close()
    
    return jsonify([dict(n) for n in notifications])

@app.route('/api/notifications/all')
def get_all_notifications():
    if 'user_id' not in session:
        return jsonify([]), 401
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT * FROM notifications 
        WHERE user_id = %s
          AND created_at >= NOW() - INTERVAL '7 days'
        ORDER BY created_at DESC
        LIMIT 100
    ''', (session['user_id'],))
    
    notifications = cur.fetchall()
    cur.close()
    db.close()
    
    return jsonify([dict(n) for n in notifications])

@app.route('/api/notifications/mark-read', methods=['POST'])
def mark_notifications_read():
    if 'user_id' not in session:
        return jsonify({'success': False}), 401
    
    data = request.get_json()
    notification_ids = data.get('notification_ids', [])
    
    db = get_db()
    cur = db.cursor()
    
    if notification_ids:
        placeholders = ','.join(['%s'] * len(notification_ids))
        cur.execute(f'''
            UPDATE notifications SET is_read = 1 
            WHERE user_id = %s AND id IN ({placeholders})
        ''', [session['user_id']] + notification_ids)
    else:
        cur.execute('UPDATE notifications SET is_read = 1 WHERE user_id = %s', (session['user_id'],))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

@app.route('/api/product/<int:product_id>')
def api_get_product(product_id):
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

    result = dict(product)

    blob = result.get('images_blob')
    if blob:
        try:
            parsed = json.loads(blob) if isinstance(blob, str) else blob
            if isinstance(parsed, list):
                result['images_blob'] = json.dumps(parsed)
            elif isinstance(parsed, str) and parsed.startswith('data:'):
                result['images_blob'] = json.dumps([parsed])
            else:
                result['images_blob'] = None
        except Exception:
            result['images_blob'] = None
    else:
        result['images_blob'] = None

    return jsonify(result)

@app.route('/api/product-image/<int:product_id>/<int:index>')
def api_product_image(product_id, index):
    import base64 as b64
    
    db = get_db()
    cur = db.cursor()

    cur.execute('SELECT images_blob, images FROM products WHERE id = %s', (product_id,))
    row = cur.fetchone()
    cur.close()
    db.close()

    if not row:
        return '', 404

    if row.get('images_blob'):
        try:
            blob_list = json.loads(row['images_blob']) if isinstance(row['images_blob'], str) else row['images_blob']
            if isinstance(blob_list, list) and index < len(blob_list):
                data_uri = blob_list[index]
                if isinstance(data_uri, str) and data_uri.startswith('data:'):
                    header, b64data = data_uri.split(',', 1)
                    mime_type = header.split(';')[0].split(':')[1]
                    img_bytes = b64.b64decode(b64data)
                    response = make_response(img_bytes)
                    response.headers.set('Content-Type', mime_type)
                    response.headers.set('Cache-Control', 'public, max-age=604800')
                    return response
        except Exception as e:
            print(f"Error serving product image: {e}")

    if row.get('images'):
        parts = [p.strip() for p in row['images'].split(',') if p.strip()]
        if parts and index < len(parts):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], parts[index])
            if os.path.exists(filepath):
                from flask import send_file
                return send_file(filepath)

    return '', 404

@app.route('/api/product/<int:product_id>/update', methods=['PUT'])
def api_update_product(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = get_db()
    cur = db.cursor()

    cur.execute('SELECT id, status FROM products WHERE id = %s AND seller_id = %s', (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    if product['status'] == 'sold':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Sold products cannot be edited'}), 400

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
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': ', '.join(errors)}), 400

    cur.execute('''
        UPDATE products
        SET name = %s, price = %s, description = %s, condition = %s, category = %s, status = 'pending'
        WHERE id = %s
    ''', (name, price, description, condition, category, product_id))

    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

@app.route('/api/product/<int:product_id>/update-full', methods=['POST'])
def api_update_product_full(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Session expired. Please login again.'}), 401

    db = get_db()
    cur = db.cursor()
    
    cur.execute('SELECT id, images, status FROM products WHERE id = %s AND seller_id = %s', 
                (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    if product['status'] == 'sold':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Sold products cannot be edited'}), 400

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

    MAX_MEDIA = 12
    if images_blob_json:
        try:
            blob_check = json.loads(images_blob_json)
            if isinstance(blob_check, list) and len(blob_check) > MAX_MEDIA:
                return jsonify({'success': False,
                                'error': f'Maximum {MAX_MEDIA} media files allowed.'}), 400
        except Exception:
            pass

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
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT id FROM products WHERE id = %s AND seller_id = %s', 
                (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    existing_images = request.form.get('existing_images', '[]')
    existing = json.loads(existing_images)
    
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

@app.route('/api/product/<int:product_id>/delete', methods=['DELETE'])
def api_delete_product(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('SELECT id, status FROM products WHERE id = %s AND seller_id = %s', 
                (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    if product['status'] == 'sold':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Sold products cannot be deleted'}), 400
    
    cur.execute('DELETE FROM products WHERE id = %s', (product_id,))
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

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

    cur.execute('SELECT COUNT(*) AS count FROM products WHERE seller_id = %s', (user_id,))
    listing_count = cur.fetchone()['count'] 

    sold_count = 0
    try:
        cur.execute("SELECT COUNT(*) AS count FROM orders WHERE seller_id = %s AND status = 'completed'", (user_id,))
        sold_count = cur.fetchone()['count']  
    except:
        pass

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
        'my_profile.html',
        user=user,
        listing_count=listing_count,
        sold_count=sold_count,
        trust_score=trust_score,
        response_rate=response_rate  
    )

@app.route('/edit_profile', methods=['GET'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()

    cur.execute('SELECT COUNT(*) AS count FROM products WHERE seller_id = %s', (session['user_id'],))
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

    sold_count = 0
    try:
        cur.execute("SELECT COUNT(*) AS count FROM orders WHERE seller_id = %s AND status = 'completed'", (session['user_id'],))
        sold_count = cur.fetchone()['count']
    except:
        pass

    cur.close()
    db.close()

    return render_template(
        'edit_profile.html',
        user=user,
        listing_count=listing_count,
        sold_count=sold_count,
        trust_score=trust_score,
        response_rate=response_rate
    )

@app.route('/api/user/is-admin')
def api_user_is_admin():
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

@app.route('/switch-to-admin')
def switch_to_admin():
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
        session['admin_logged_in'] = True
        session['admin_email'] = user['email']
        session['admin_username'] = user['username']
        flash('Switched to Admin mode', 'success')
        return redirect(url_for('admin_dashboard'))
    else:
        flash('You do not have admin privileges', 'error')
        return redirect(url_for('edit_profile'))
    
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
    campus = request.form.get('campus')
    
    if not campus:
        flash('📍 Please select your campus (Melaka or Cyberjaya)', 'error')
        return redirect(url_for('edit_profile'))

    db = get_db()
    cur = db.cursor()

    cur.execute('SELECT id FROM users WHERE username = %s AND id != %s', (username, session['user_id']))
    existing = cur.fetchone()
    if existing:
        cur.close()
        db.close()
        flash('Username already taken', 'error')
        return redirect(url_for('edit_profile'))

    cur.execute("""
        UPDATE users
        SET username = %s, full_name = %s, bio = %s,
            contact = %s, gender = %s, active_hours = %s, campus = %s
        WHERE id = %s
    """, (username, full_name, bio, contact, gender, active_hours, campus, session['user_id']))

    db.commit()
    cur.close()
    db.close()

    session['username'] = username
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('edit_profile'))

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

    response = redirect(url_for('login'))
    response.set_cookie('remember_token', '', expires=0)

    flash('Your account has been permanently deleted', 'info')
    return response

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

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        step = request.form.get('step')

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
                errors.append('Password must contain at least 1 uppercase letter')
            if not re.search(r'[a-z]', new_password):
                errors.append('Password must contain at least 1 lowercase letter')
            if not re.search(r'[0-9]', new_password):
                errors.append('Password must contain at least 1 number')
            if not re.search(r'[!@#$%^&*]', new_password):
                errors.append('Password must contain at least 1 special character')
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

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip() 
        password = request.form.get('password')
        remember_me = request.form.get('remember_me') 
    
        if not email.endswith('@student.mmu.edu.my'):
            flash('Only @student.mmu.edu.my email addresses are allowed', 'error')
            return render_template('admin_login.html')
    
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s AND is_admin = 1', (email,))
        user = cur.fetchone()
        cur.close()
        db.close()

        if user and check_password_hash(user['password'], password):
            session['admin_logged_in'] = True
            session['admin_email'] = user['email']
            session['admin_username'] = user['username']
            
            if remember_me:
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
    
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT id, email, username, is_admin FROM users WHERE remember_token = %s AND is_admin = 1', (token,))
        user = cur.fetchone()
        cur.close()
        db.close()
        
        if user:
            session['admin_logged_in'] = True
            session['admin_email'] = user['email']
            session['admin_username'] = user['username']
            print(f"Auto-logged in admin: {user['username']}")
    except Exception as e:
        print(f"Error in check_admin_remember_me: {e}")
        response = make_response()
        response.set_cookie('admin_remember_token', '', expires=0)
        return response

@app.route('/logout')
def logout():
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
# Admin Routes
# ============================================================
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        flash('Please login as admin first', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT COUNT(*) AS count FROM products")
    total_products = cur.fetchone()['count']
    cur.execute("SELECT COUNT(*) AS count FROM users")
    total_users = cur.fetchone()['count']
    cur.execute("SELECT COUNT(*) AS count FROM products WHERE status = 'approved'")
    approved_count = cur.fetchone()['count']
    cur.execute("SELECT COUNT(*) AS count FROM products WHERE status = 'pending'")
    pending_count = cur.fetchone()['count']
    cur.execute("SELECT COUNT(DISTINCT seller_id) AS count FROM products")
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
    
    pending = [dict(row) for row in pending]
    approved = [dict(row) for row in approved]
    rejected = [dict(row) for row in rejected]

    cur.close()
    db.close()

    return render_template("admin_product.html",
                           pending_list=pending,
                           approved_list=approved,
                           rejected_list=rejected)

@app.route('/admin/product/approve/<int:pid>')
def approve_product(pid):
    if not session.get('admin_logged_in'):
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    cur = db.cursor()
    
    cur.execute('SELECT seller_id, name FROM products WHERE id = %s', (pid,))
    product = cur.fetchone()
    
    cur.execute('''
        UPDATE products
        SET status = 'approved', reject_reason = ''
        WHERE id = %s
    ''', (pid,))

    db.commit()
    
    if product:
        create_notification(
            user_id=product['seller_id'],
            message=f'🎉 Product "{product["name"]}" has been APPROVED and is now live!',
            notif_type='product_approved',
            related_id=pid,
            product_id=pid
        )
    
    cur.close()
    db.close()

    flash("Product approved successfully, now visible on homepage", "success")
    return redirect(url_for('admin_products'))

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
    
    cur.execute('SELECT seller_id, name FROM products WHERE id = %s', (pid,))
    product = cur.fetchone()
    
    cur.execute('''
        UPDATE products
        SET status = 'rejected', reject_reason = %s
        WHERE id = %s
    ''', (reject_reason, pid))

    db.commit()
    
    if product:
        create_notification(
            user_id=product['seller_id'],
            message=f'❌ Product "{product["name"]}" was REJECTED. Reason: {reject_reason}. You can edit and resubmit.',
            notif_type='product_rejected',
            related_id=pid,
            product_id=pid
        )
    
    cur.close()
    db.close()

    flash("Product rejected successfully", "success")
    return redirect(url_for('admin_products'))

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

    images_list = []
    if product_dict.get('images_blob'):
        try:
            images_list = json.loads(product_dict['images_blob'])
        except Exception:
            images_list = [product_dict['images_blob']]

    if not images_list and product_dict.get('images'):
        for fname in product_dict['images'].split(','):
            fname = fname.strip()
            if fname:
                images_list.append(f"/static/uploads/{fname}")

    product_dict['images_list'] = images_list
    return product_dict

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
          f" Your account has been UNBLOCKED by admin.\n"
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
        
        create_notification(
            user_id=report['reporter_id'],
            message=f'📋 Your report has been reviewed and DISMISSED by admin. No action was taken.',
            notif_type='report_dismissed',
            related_id=report_id
        )
              
    elif action == 'block':
        cur.execute("UPDATE users SET is_blocked = 1 WHERE id = %s", (report['reported_user_id'],))
        cur.execute("UPDATE reports SET status = 'resolved' WHERE id = %s", (report_id,))
        
        create_notification(
            user_id=report['reported_user_id'],
            message=f'🚫 Your account has been BLOCKED due to user reports. Please contact admin if you believe this is a mistake.',
            notif_type='block',
            related_id=report_id
        )
        
        create_notification(
            user_id=report['reporter_id'],
            message=f'✅ Your report has been verified. The reported user has been BLOCKED. Thank you for helping keep our community safe!',
            notif_type='report_resolved',
            related_id=report_id
        )

    db.commit()
    cur.close()
    db.close()
    return jsonify({'success': True})

# ============================================================
# Chat Routes
# ============================================================
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
        VALUES (%s, %s, %s, %s, NOW() AT TIME ZONE 'Asia/Kuala_Lumpur')
    ''', (session['user_id'], int(receiver_id), int(product_id) if product_id else None, content))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

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
        VALUES (%s, %s, %s, %s, NOW() AT TIME ZONE 'Asia/Kuala_Lumpur')
    ''', (session['user_id'], int(receiver_id), content, ','.join(filenames)))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

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
        VALUES (%s, %s, %s, %s, %s, NOW() AT TIME ZONE 'Asia/Kuala_Lumpur')
    ''', (session['user_id'], int(receiver_id), int(product_id) if product_id else None, '', filename))
    db.commit()
    cur.close()
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
    
    cur.execute('SELECT * FROM users WHERE id = %s', (other_user_id,))
    other_user = cur.fetchone()
    if not other_user:
        cur.close()
        db.close()
        flash("User not found", "error")
        return redirect(url_for('home'))

    product_info = None
    if product_id:
        cur.execute('''
            SELECT p.*, u.username as seller_name
            FROM products p JOIN users u ON p.seller_id = u.id
            WHERE p.id = %s
        ''', (product_id,))
        product_info = cur.fetchone()

    cur.execute('''
        SELECT * FROM messages
        WHERE (sender_id = %s AND receiver_id = %s)
           OR (sender_id = %s AND receiver_id = %s)
        ORDER BY created_at ASC
    ''', (session['user_id'], other_user_id, other_user_id, session['user_id']))
    messages = cur.fetchall()
    
    for msg in messages:
        if msg['created_at']:
            from datetime import timezone, timedelta
            malaysia_tz = timezone(timedelta(hours=8))
            ca = msg['created_at']
            if isinstance(ca, str):
                ca = datetime.strptime(ca[:19], '%Y-%m-%d %H:%M:%S')
            msg['created_at'] = ca.replace(tzinfo=timezone.utc).astimezone(malaysia_tz).strftime('%Y-%m-%d %H:%M:%S')

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

    from datetime import timezone, timedelta
    malaysia_tz = timezone(timedelta(hours=8))
    
    result = []
    for msg in messages:
        msg = dict(msg)
        if msg['created_at']:
            ca = msg['created_at']
            if isinstance(ca, str):
                ca = datetime.strptime(ca[:19], '%Y-%m-%d %H:%M:%S')
            msg['created_at'] = ca.replace(tzinfo=timezone.utc).astimezone(malaysia_tz).strftime('%Y-%m-%d %H:%M:%S')
        result.append(msg)

    return jsonify(result)

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
    
    cur.execute('SELECT username FROM users WHERE id = %s', (user_id,))
    reported_user = cur.fetchone()
    
    cur.execute('''
        INSERT INTO reports (reporter_id, reported_user_id, reason, details)
        VALUES (%s, %s, %s, %s)
    ''', (session['user_id'], user_id, reason, details))
    db.commit()
    
    create_notification(
        user_id=session['user_id'],
        message=f'📋 You reported user @{reported_user["username"]} for: {reason}. Admin will review within 1-3 business days.',
        notif_type='report_submitted'
    )
    
    create_notification(
        user_id=user_id,
        message=f'⚠️ You received a report: {reason}. Please follow community guidelines. Repeated violations will result in account restrictions.',
        notif_type='report_warning'
    )
    
    cur.close()
    db.close()
    
    return jsonify({'success': True})

@app.route('/chatlist')
def chat_list():
    if 'user_id' not in session:
        flash("Please login first", "error")
        return redirect(url_for('login'))

    from datetime import timezone, timedelta
    malaysia_tz = timezone(timedelta(hours=8))

    db = get_db()
    user_id = session['user_id']
    cur = db.cursor()

    cur.execute('''
        SELECT u.id, u.username, u.full_name, u.avatar_blob,
               m.content as last_message, m.image as last_image,
               m.created_at as last_time,
               m.is_read, m.sender_id,
               (SELECT COUNT(*) AS count FROM messages
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
        if chat.get('last_time'):
            lt = chat['last_time']
            if isinstance(lt, str):
                lt = datetime.strptime(lt[:19], '%Y-%m-%d %H:%M:%S')
            chat['last_time'] = lt.replace(tzinfo=timezone.utc).astimezone(malaysia_tz).strftime('%Y-%m-%d %H:%M:%S')
        chat_list_data.append(chat)

    cur.execute("SELECT COUNT(*) AS count FROM notifications WHERE user_id = %s AND is_read = 0", (user_id,))
    unread_notifications = cur.fetchone()['count']
    unread_reviews = 0
    
    cur.execute("SELECT COUNT(*) AS count FROM announcements")
    unread_announcements = cur.fetchone()['count']
    
    cur.close()
    db.close()

    return render_template('user_chatlist.html', 
                           chats=chat_list_data,
                           unread_notifications=unread_notifications,
                           unread_reviews=unread_reviews,
                           unread_announcements=unread_announcements)

@app.route('/api/order/<int:order_id>/update-meeting', methods=['POST'])
def update_order_meeting(order_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json()
    meeting_point = data.get('meeting_point')
    meeting_time = data.get('meeting_time')

    if not meeting_point or not meeting_time:
        return jsonify({'success': False, 'error': 'Meeting point and time required'}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute('SELECT seller_id, buyer_id, order_number FROM orders WHERE id = %s', (order_id,))
    order = cur.fetchone()
    if not order or order['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    cur.execute('''
        UPDATE orders SET meeting_point = %s, meeting_time = %s, updated_at = NOW()
        WHERE id = %s
    ''', (meeting_point, meeting_time, order_id))

    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'order', %s, 0)
    ''', (order['buyer_id'],
          f" The seller has updated the meetup info for Order #{order['order_number']}. New meeting: {meeting_point} at {meeting_time}",
          order_id))

    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

@app.route('/api/order/<int:order_id>/ship', methods=['POST'])
def ship_order(order_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT seller_id, buyer_id, order_number FROM orders WHERE id = %s', (order_id,))
    order = cur.fetchone()
    if not order or order['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    cur.execute('UPDATE orders SET status = %s, updated_at = NOW() WHERE id = %s', ('delivered', order_id))

    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'order', %s, 0)
    ''', (order['buyer_id'],
          f"✅ Order #{order['order_number']} has been marked as DELIVERED. Please confirm receipt to complete the order.",
          order_id))

    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

@app.route('/api/mark-ann-read', methods=['POST'])
def mark_ann_read():
    if 'user_id' not in session:
        return jsonify({'success': False}), 401
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE users SET last_read_ann = NOW() WHERE id = %s", (session['user_id'],))
    db.commit()
    cur.close()
    db.close()
    return jsonify({'success': True})

@app.route('/api/search-users')
def search_users():
    if 'user_id' not in session:
        return jsonify([])
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    db = get_db()
    cur = db.cursor()
    # make search term space‑flexible and case‑insensitive
    search_term = f"%{q.replace(' ', '%')}%"
    cur.execute(
        "SELECT id, username, student_id FROM users WHERE username ILIKE %s OR student_id ILIKE %s LIMIT 10",
        (search_term, search_term)
    )
    users = cur.fetchall()
    cur.close()
    db.close()
    return jsonify([dict(u) for u in users])

@app.route('/api/announcements')
def api_announcements():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT title, content, created_at FROM announcements ORDER BY created_at DESC")
    anns = cur.fetchall()
    cur.close()
    db.close()
    return jsonify([dict(a) for a in anns])

@app.route('/admin/announcement/add', methods=['POST'])
def add_announcement():
    if not session.get('admin_logged_in'):
        return jsonify({'success': False}), 403
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    if title and content:
        db = get_db()
        cur = db.cursor()
        cur.execute("INSERT INTO announcements (title, content) VALUES (%s, %s) RETURNING id", (title, content))
        ann_id = cur.fetchone()['id']
        cur.execute("INSERT INTO notifications (user_id, message, created_at) SELECT id, %s, NOW() FROM users", 
                    (f"📢 New announcement: {title}",))
        db.commit()
        cur.close()
        db.close()
        return jsonify({'success': True, 'id': ann_id})
    return jsonify({'success': False})

@app.route('/admin/announcement/delete/<int:ann_id>', methods=['POST'])
def delete_announcement(ann_id):
    if not session.get('admin_logged_in'):
        return jsonify({'success': False}), 403
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM announcements WHERE id = %s", (ann_id,))
    db.commit()
    cur.close()
    db.close()
    return jsonify({'success': True})

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

@app.route('/upload', methods=['GET', 'POST'])
def upload_product():
    if 'user_id' not in session:
        flash("You must be logged in to post an item.", "error")
        return redirect(url_for('login'))

    # Check if user has selected a campus
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT campus FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()

    if not user or not user['campus']:
        flash('📍 Please select your campus in Edit Profile before listing items.', 'error')
        return redirect(url_for('edit_profile'))

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

        # 支持的文件类型
        MIME_MAP = {
            # 图片格式
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
            'gif': 'image/gif', 'webp': 'image/webp', 'bmp': 'image/bmp',
            'jfif': 'image/jpeg',
            # 视频格式
            'mp4': 'video/mp4',
            'webm': 'video/webm',
            'mov': 'video/quicktime',
            'avi': 'video/x-msvideo',
            'mkv': 'video/x-matroska',
            'm4v': 'video/x-m4v',
        }

        files = request.files.getlist('product_images')
        
        # 过滤掉空文件
        files = [f for f in files if f and f.filename]
        
        if not files:
            errors.append("Please upload at least one photo or video.")
        
        # 检查文件数量（最多 12 个）
        if len(files) > 12:
            errors.append("Maximum 12 images/videos allowed.")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template('upload.html')

        images_base64 = []
        image_filenames = []

        for file in files:
            if not file or not file.filename:
                continue

            # 获取文件扩展名
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
            
            # 检查文件类型是否支持
            if ext not in MIME_MAP:
                flash(f"Unsupported file type: .{ext}. Supported: jpg, jpeg, png, gif, webp, mp4, webm, mov", "error")
                return render_template('upload.html')
            
            # 读取文件数据
            file_data = file.read()
            
            # 检查文件大小
            is_video = ext in ['mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v']
            max_size = 200 * 1024 * 1024 if is_video else 50 * 1024 * 1024  # 视频200MB，图片50MB
            
            if not file_data or len(file_data) > max_size:
                max_mb = max_size // (1024 * 1024)
                flash(f"{file.filename} is too large (max {max_mb}MB)", "error")
                return render_template('upload.html')
            
            # 获取 MIME 类型
            mime_type = MIME_MAP.get(ext, 'application/octet-stream')
            
            # 特殊处理 MOV 文件
            if ext == 'mov':
                mime_type = 'video/quicktime'

            # 构建 base64 数据 URI
            base64_str = base64.b64encode(file_data).decode('utf-8')
            images_base64.append(f"data:{mime_type};base64,{base64_str}")

            # 保存到磁盘（备份）
            filename = secure_filename(file.filename)
            if not filename or filename.strip() == '':
                filename = f"media_{uuid.uuid4().hex}.{ext}"
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            with open(save_path, 'wb') as f:
                f.write(file_data)
            image_filenames.append(unique_filename)
            
            print(f" Uploaded: {filename} ({len(file_data)} bytes, type: {mime_type})")

        if not images_base64:
            errors.append("Failed to process files. Please try again.")
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
        
        # 获取新商品 ID
        cur.execute("SELECT LASTVAL() as id")
        new_product_id = cur.fetchone()['id']
        
        db.commit()
        cur.close()
        db.close()

        # 发送通知
        create_notification(
            user_id=seller_id,
            message=f' Product "{name}" submitted. Awaiting admin approval.',
            notif_type='product_uploaded',
            related_id=new_product_id,
            product_id=new_product_id
        )

        flash("Your item has been submitted for admin approval.", "success")
        return redirect(url_for('home'))

    return render_template('upload.html')

@app.route('/clear-products')
def clear_products():
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM products")
    db.commit()
    cur.close()
    db.close()
    return "All products deleted."

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    if 'user_id' not in session:
        flash('Please login to view product details.', 'error')
        return redirect(url_for('login'))

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT p.*, u.username as seller_name, u.full_name as seller_full_name,
            u.avatar_blob as seller_avatar, u.id as seller_id, u.created_at as user_joined,
            u.is_blocked as seller_blocked, u.campus as seller_campus
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.id = %s AND p.status IN ('approved', 'sold', 'reserved')
    ''', (product_id,))
    product = cur.fetchone()
    cur.close()
    db.close()

    if not product:
        flash('Product not found or not yet approved.', 'error')
        return redirect(url_for('home'))
    
    if product['seller_blocked'] == 1:
        flash('This product is no longer available (seller has been blocked).', 'error')
        return redirect(url_for('home'))

    images_blob_str = product.get('images_blob', '[]')
    images = []
    if images_blob_str and images_blob_str != '[]':
        try:
            images = json.loads(images_blob_str)
            images = [img for img in images if img.startswith('data:')]
        except:
            pass
    if not images and product.get('images'):
        images = product['images'].split(',') if product['images'] else []

    return render_template('product.html', product=product, images=images)

@app.route('/api/report-product/<int:product_id>', methods=['POST'])
def api_report_product(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    reason = data.get('reason', '').strip()
    details = data.get('details', '').strip()
    
    if not reason:
        return jsonify({'success': False, 'error': 'Reason required'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('SELECT name, seller_id FROM products WHERE id = %s', (product_id,))
    product = cur.fetchone()
    
    cur.execute('''
        INSERT INTO reports (reporter_id, product_id, reason, details)
        VALUES (%s, %s, %s, %s)
    ''', (session['user_id'], product_id, reason, details))
    db.commit()
    
    if product:
        create_notification(
            user_id=session['user_id'],
            message=f'📋 You reported product "{product["name"]}" for: {reason}. Admin will review within 1-3 business days.',
            notif_type='report_submitted',
            product_id=product_id
        )
        
        create_notification(
            user_id=product['seller_id'],
            message=f'⚠️ Your product "{product["name"]}" received a report: {reason}. Please ensure your listing follows guidelines.',
            notif_type='report_warning',
            product_id=product_id
        )
    
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'message': 'Report submitted'})

@app.route('/api/orders/my', methods=['GET'])
def api_get_my_orders():
    if 'user_id' not in session:
        return jsonify({'as_buyer': [], 'as_seller': []}), 401
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT o.*, p.name as product_name, p.images, p.images_blob,
               u.username as seller_name, u.full_name as seller_full_name, u.id as seller_id
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON o.seller_id = u.id
        WHERE o.buyer_id = %s
        ORDER BY o.created_at DESC
    ''', (session['user_id'],))
    buyer_orders = cur.fetchall()
    
    cur.execute('''
        SELECT o.*, p.name as product_name, p.images, p.images_blob,
               u.username as buyer_name, u.full_name as buyer_full_name, u.id as buyer_id
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON o.buyer_id = u.id
        WHERE o.seller_id = %s
        ORDER BY o.created_at DESC
    ''', (session['user_id'],))
    seller_orders = cur.fetchall()
    
    cur.close()
    db.close()
    
    result_buyer = []
    for o in buyer_orders:
        o_dict = dict(o)
        # 获取产品图片
        if o_dict.get('images_blob'):
            try:
                imgs = json.loads(o_dict['images_blob'])
                o_dict['product_image'] = imgs[0] if imgs else None
            except:
                o_dict['product_image'] = None
        elif o_dict.get('images'):
            img_list = o_dict['images'].split(',')
            if img_list:
                o_dict['product_image'] = '/static/uploads/' + img_list[0]
        else:
            o_dict['product_image'] = None
        result_buyer.append(o_dict)
    
    result_seller = []
    for o in seller_orders:
        o_dict = dict(o)
        if o_dict.get('images_blob'):
            try:
                imgs = json.loads(o_dict['images_blob'])
                o_dict['product_image'] = imgs[0] if imgs else None
            except:
                o_dict['product_image'] = None
        elif o_dict.get('images'):
            img_list = o_dict['images'].split(',')
            if img_list:
                o_dict['product_image'] = '/static/uploads/' + img_list[0]
        else:
            o_dict['product_image'] = None
        result_seller.append(o_dict)
    
    return jsonify({'as_buyer': result_buyer, 'as_seller': result_seller})

@app.route('/api/order/<int:order_id>/status', methods=['PUT'])
def api_update_order_status(order_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    new_status = data.get('status')
    
    valid_statuses = ['pending', 'confirmed', 'delivered', 'completed', 'cancelled']
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id
        FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (order_id,))
    order = cur.fetchone()
    
    if not order:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Order not found'}), 404
    
    is_seller = (order['seller_id'] == session['user_id'])
    is_buyer = (order['buyer_id'] == session['user_id'])
    
    if not (is_seller or is_buyer):
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # 允许的状态转换
    allowed = {
        'pending': {'confirmed': 'seller', 'cancelled': 'both'},
        'confirmed': {'delivered': 'seller', 'cancelled': 'both'},
        'delivered': {'completed': 'buyer'},
        'completed': {},
        'cancelled': {}
    }
    
    if new_status not in allowed.get(order['status'], {}):
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Invalid status transition'}), 400
    
    allowed_by = allowed[order['status']][new_status]
    if allowed_by == 'seller' and not is_seller:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Only seller can do this'}), 403
    if allowed_by == 'buyer' and not is_buyer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Only buyer can do this'}), 403
    
    cur.execute('UPDATE orders SET status = %s, updated_at = NOW() WHERE id = %s', (new_status, order_id))
    
    notify_user_id = order['buyer_id'] if is_seller else order['seller_id']
    
    messages = {
        'confirmed': f"✅ Order #{order['order_number']} has been CONFIRMED by seller!",
        'delivered': f"🚚 Order #{order['order_number']} has been MARKED AS DELIVERED! Please confirm receipt to complete the order.",
        'completed': f"🎉 Order #{order['order_number']} is COMPLETED! Please leave a review.",
        'cancelled': f"❌ Order #{order['order_number']} has been CANCELLED."
    }
    
    if new_status in messages:
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
            VALUES (%s, %s, NOW(), 'order', %s, 0)
        ''', (notify_user_id, messages[new_status], order_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

@app.route('/api/order/<int:order_id>/review', methods=['POST'])
def api_submit_order_review(order_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json()
    rating_service = data.get('rating_service', 0)
    rating_shipping = data.get('rating_shipping', 0)
    rating_quality = data.get('rating_quality', 0)
    comment = data.get('comment', '').strip()

    for r, name in [(rating_service, 'service'), (rating_shipping, 'shipping'), (rating_quality, 'quality')]:
        if r < 1 or r > 5:
            return jsonify({'success': False, 'error': f'{name} rating must be 1-5'}), 400
    
    rating_overall = round((rating_service + rating_shipping + rating_quality) / 3, 1)
    
    db = get_db()
    cur = db.cursor()

    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id, p.id as product_id
        FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.buyer_id = %s AND o.status = 'completed'
    ''', (order_id, session['user_id']))

    order = cur.fetchone()

    if not order:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Order not found'}), 404

    cur.execute('SELECT id FROM reviews WHERE order_id = %s', (order_id,))
    if cur.fetchone():
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Already reviewed'}), 400
    
    cur.execute('''
        INSERT INTO reviews (product_id, reviewer_id, reviewee_id, order_id,
                           rating_service, rating_shipping, rating_quality, rating_overall, comment, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) RETURNING id
    ''', (order['product_id'], session['user_id'], order['seller_id'], order_id,
          rating_service, rating_shipping, rating_quality, rating_overall, comment))
    
    review_id = cur.fetchone()['id']

    cur.execute('''
        SELECT AVG(rating_service) as avg_service, AVG(rating_shipping) as avg_shipping,
               AVG(rating_quality) as avg_quality, AVG(rating_overall) as avg_overall, COUNT(*) as total
        FROM reviews WHERE reviewee_id = %s
    ''', (order['seller_id'],))
    stats = cur.fetchone()
    
    cur.execute('''
        UPDATE users SET avg_service_rating = %s, avg_shipping_rating = %s,
               avg_quality_rating = %s, avg_overall_rating = %s, total_reviews = %s,
               rating = %s
        WHERE id = %s
    ''', (stats['avg_service'] or 0, stats['avg_shipping'] or 0,
          stats['avg_quality'] or 0, stats['avg_overall'] or 0,
          stats['total'] or 0,
          str(round(float(stats['avg_overall'] or 0), 1)),
          order['seller_id']))
    
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (order['seller_id'], 
          f"⭐ You received a {rating_overall}-star review for {order['product_name']}: \"{comment[:50]}{'...' if len(comment) > 50 else ''}\"",
          'review', review_id))

    db.commit()
    cur.close()
    db.close()   

    return jsonify({'success': True, 'overall_rating': rating_overall})

@app.route('/api/user/<int:user_id>/reviews', methods=['GET'])
def api_get_user_reviews(user_id):
    db = get_db()
    cur = db.cursor()

    cur.execute('''
        SELECT r.*, r.reviewer_id, u.username as reviewer_name, u.full_name as reviewer_full_name,
               u.avatar_blob, p.name as product_name
        FROM reviews r
        JOIN users u ON r.reviewer_id = u.id
        JOIN products p ON r.product_id = p.id
        WHERE r.reviewee_id = %s
        ORDER BY r.created_at DESC
    ''', (user_id,))
    reviews = cur.fetchall()

    cur.execute('''
        SELECT AVG(rating_service) as avg_service, AVG(rating_shipping) as avg_shipping,
               AVG(rating_quality) as avg_quality, AVG(rating_overall) as avg_overall, COUNT(*) as total
        FROM reviews WHERE reviewee_id = %s
    ''', (user_id,))
    stats = cur.fetchone()

    cur.close()
    db.close()

    result = []   
    for r in reviews:
        r_dict = dict(r)
        if r_dict.get('avatar_blob'):
            avatar_data = bytes(r_dict['avatar_blob']) if hasattr(r_dict['avatar_blob'], 'tobytes') else r_dict['avatar_blob']
            r_dict['reviewer_avatar_base64'] = f"data:image/jpeg;base64,{base64.b64encode(avatar_data).decode('utf-8')}"
        else:
            r_dict['reviewer_avatar_base64'] = None
        r_dict.pop('avatar_blob', None)
        r_dict['reviewer_id'] = r['reviewer_id'] if 'reviewer_id' in r else r.get('id')
        result.append(r_dict)  
    
    return jsonify({
        'reviews': result,
        'avg_service': round(stats['avg_service'], 1) if stats['avg_service'] else 0,
        'avg_shipping': round(stats['avg_shipping'], 1) if stats['avg_shipping'] else 0,
        'avg_quality': round(stats['avg_quality'], 1) if stats['avg_quality'] else 0,
        'avg_overall': round(stats['avg_overall'], 1) if stats['avg_overall'] else 0,
        'total_reviews': stats['total'] or 0
    })

@app.route('/api/user/<int:user_id>/can-review', methods=['GET'])
def api_can_review_user(user_id):
    """Check whether user can comment and review seller or not(check either have completed order but not review order or not)"""
    if 'user_id' not in session:
        return jsonify({'can_review': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()

    # check either have completed order but no review order
    cur.execute('''
        SELECT o.id, o.order_number, p.name as product_name
        FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE o.buyer_id = %s 
          AND o.seller_id = %s 
          AND o.status = 'completed'
          AND NOT EXISTS (
              SELECT 1 FROM reviews r 
              WHERE r.order_id = o.id AND r.reviewer_id = %s
          )
        LIMIT 1
    ''', (session['user_id'], user_id, session['user_id']))

    order = cur.fetchone()
    cur.close()
    db.close()

    if order:
        return jsonify({
            'can_review': True,
            'order_id': order['id'],
            'product_name': order['product_name']
        })
    else:
        return jsonify({'can_review': False})
    
@app.route('/meetup-locations')
def meetup_locations():
    return render_template('meetup.html')

# ============================================================
# Other User Profile - Xingru
# ============================================================

@app.route('/user/<int:user_id>')
def other_profile(user_id):
    if 'user_id' not in session:
        flash('Please login to view profiles.', 'error')
        return redirect(url_for('login'))

    # If viewing own profile, redirect to my_profile
    if user_id == session['user_id']:
        return redirect(url_for('my_profile'))

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    user = cur.fetchone()
    if not user:
        cur.close()
        db.close()
        flash('User not found.', 'error')
        return redirect(url_for('home'))

    # Get listing count (approved products only)
    cur.execute("SELECT COUNT(*) AS count FROM products WHERE seller_id = %s AND status = 'approved'", (user_id,))
    listing_count = cur.fetchone()['count']

    # Get sold count (completed orders as seller)
    cur.execute("SELECT COUNT(*) AS count FROM orders WHERE seller_id = %s AND status = 'completed'", (user_id,))
    sold_count = cur.fetchone()['count']

    # Calculate trust score and response rate (same as my_profile)
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

    return render_template('other_profile.html',
                           user=user,
                           listing_count=listing_count,
                           sold_count=sold_count,
                           trust_score=trust_score,
                           response_rate=response_rate)

@app.route('/api/user/<int:user_id>/background')
def api_other_user_background(user_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT background_type, background_value FROM users WHERE id = %s', (user_id,))
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

@app.route('/api/user/<int:user_id>/cover')
def api_other_user_cover(user_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT cover_blob FROM users WHERE id = %s', (user_id,))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    if user and user['cover_blob']:
        cover_data = bytes(user['cover_blob']) if hasattr(user['cover_blob'], 'tobytes') else user['cover_blob']
        response = make_response(cover_data)
        response.headers.set('Content-Type', 'image/jpeg')
        response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
        return response
    return jsonify({'success': False, 'error': 'User not found'}), 404

@app.route('/api/user/<int:user_id>/listings')
def api_user_other_listings(user_id):
    if 'user_id' not in session:
        return jsonify([])

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT p.id, p.name, p.price, p.status, p.created_at,
               p.images, p.images_blob, p.condition, u.campus as seller_campus
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.seller_id = %s AND p.status = 'approved'
        ORDER BY p.created_at DESC
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    db.close()

    listings = []
    for row in rows:
        item = dict(row)
        first_image = None
        is_video = False

        # 1. Try to get first image from images_blob (base64)
        images_blob = item.get('images_blob')
        if images_blob:
            try:
                blob_list = json.loads(images_blob) if isinstance(images_blob, str) else images_blob
                if isinstance(blob_list, list) and len(blob_list) > 0:
                    first_blob = blob_list[0]
                    if isinstance(first_blob, str) and first_blob.startswith('data:'):
                        first_image = first_blob
                        is_video = first_blob.startswith('data:video/')
            except Exception as e:
                print(f"Error parsing images_blob for other user: {e}")

        # 2. Fallback to static file paths (images column)
        if not first_image and item.get('images'):
            img_str = item['images']
            if img_str:
                img_list = [x.strip() for x in img_str.split(',') if x.strip()]
                if img_list:
                    first_image = '/static/uploads/' + img_list[0]
                    ext = img_list[0].split('.')[-1].lower()
                    is_video = ext in ['mp4', 'webm', 'mov', 'avi', 'mkv']

        # Remove raw blob to avoid sending huge JSON
        item.pop('images_blob', None)
        item.pop('images', None)
        item['first_image'] = first_image
        item['first_image_is_video'] = is_video
        listings.append(item)

    return jsonify(listings)

if __name__ == '__main__':
    app.run(debug=False)