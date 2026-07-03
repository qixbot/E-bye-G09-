# ============================================================
# STANDARD LIBRARY IMPORTS
# ============================================================

import re              # Regular expressions - input validation, pattern matching
import subprocess      # Run external commands/processes
import os              # Operating system - file paths, environment variables
from datetime import datetime, timedelta  # Date/time manipulation
import uuid            # Generate unique identifiers
import base64          # Binary to text encoding/decoding
import json            # JSON data parsing/serialization
import secrets         # Cryptographically secure random numbers
import random          # Pseudo-random number generation
import time            # Time functions - timestamps, delays

# ============================================================
# FLASK FRAMEWORK IMPORTS
# ============================================================

from flask import (
    Flask,           # Main application class
    render_template, # Render HTML templates
    request,         # Access HTTP request data
    redirect,        # Redirect to URLs
    url_for,         # Generate route URLs
    session,         # Store user session data
    flash,           # Display temporary messages
    jsonify,         # Convert to JSON responses
    make_response    # Customize HTTP responses
)

# ============================================================
# WERKZEUG SECURITY IMPORTS
# ============================================================

from werkzeug.security import generate_password_hash  # Hash passwords
from werkzeug.security import check_password_hash    # Verify passwords
from werkzeug.utils import secure_filename           # Sanitize filenames

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

from dotenv import load_dotenv  # Load environment variables from .env file


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

_unread_cache = {}
_unread_cache_time = {}

@app.route('/api/unread-count')
def unread_count():
    if 'user_id' not in session:
        return jsonify({'chat': 0, 'notifications': 0})
    
    user_id = session['user_id']
    now = time.time()
    
    # Cache for 5 seconds to avoid frequent database queries.
    if user_id in _unread_cache and (now - _unread_cache_time.get(user_id, 0)) < 5:
        return jsonify(_unread_cache[user_id])
    
    try:
        db = get_db()
        cur = db.cursor()
        
        cur.execute("SELECT COUNT(*) AS count FROM messages WHERE receiver_id = %s AND is_read = 0", (user_id,))
        chat_unread = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) AS count FROM notifications WHERE user_id = %s AND is_read = 0", (user_id,))
        notif_unread = cur.fetchone()['count']
        
        cur.close()
        db.close()
        
        result = {'chat': chat_unread, 'notifications': notif_unread}
        
        # Update cache
        _unread_cache[user_id] = result
        _unread_cache_time[user_id] = now
        
        return jsonify(result)
    except Exception as e:
        print(f"Unread count error: {e}")
        return jsonify({'chat': 0, 'notifications': 0})

# ============================================================
# Helper functions
# ============================================================

# Xingru'part
# Emoji mapping based on product name
def get_emoji_by_category(name):
    """Return an emoji based on product name (fallback for purchases)"""
    name_lower = str(name).lower()          #convert to string and lowercase for safety
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

# ============================================================
# Eileen's Routes
# ============================================================
# Calculate user trust score (30-100, starts at 60)
def calculate_trust_score(user, listing_count):
    trust_score = 60
    
    # Profile completeness bonuses
    if user['avatar_blob']:
        trust_score += 8
    if user['bio']:
        trust_score += 8
    if user['contact']:
        trust_score += 7
    if user['full_name']:
        trust_score += 7
    if user['campus']:
        trust_score += 5

    # Account age bonus (0-20 points)
    if user['created_at']:
        try:
            ca = user['created_at']
            if isinstance(ca, str):
                created_date = datetime.strptime(ca[:19], '%Y-%m-%d %H:%M:%S')
            else:
                created_date = ca
            
            # Ensure time zone handling is correct
            if hasattr(created_date, 'tzinfo') and created_date.tzinfo is not None:
                created_date = created_date.replace(tzinfo=None)
            
            now = datetime.now()
            days_since_join = (now - created_date).days
            
            # Bonus points based on the number of days
            if days_since_join >= 365:
                trust_score += 20
            elif days_since_join >= 180:
                trust_score += 15
            elif days_since_join >= 30:
                trust_score += 10
            elif days_since_join >= 7:
                trust_score += 5
        except Exception as e:
            print(f"Error calculating days since join: {e}") # No points are awarded by default when an error occurs.

    # Listing activity bonus (up to 25 points)
    trust_score += min(25, (listing_count // 2) * 2)

    # Additional profile bonuses
    if user['active_hours'] and user['active_hours'] != 'Not set':
        trust_score += 10
    if user['gender']:
        trust_score += 5

    # Clamp score within range
    trust_score = min(trust_score, 100)
    trust_score = max(trust_score, 30)
    
    return trust_score

# ============================================================
# TEMPLATE FILTER - Format time since user joined
#                       Xingru's part
#                    Time Since Filter
# ============================================================
@app.template_filter('time_since')
def time_since(date):
    """
    Jinja2 template filter: Convert date to human-readable "time since" string
    Usage in template: {{ user.created_at|time_since }}
    
    Returns:
        str: e.g., "2 years", "3 months", "5 days", or "Just joined"
    """
    # Return default if no date provided
    if not date:
        return 'Just joined'       # If date is None or empty, return 'Just joined'
    
    now = datetime.now()
    
    # Convert string date to datetime if needed
    if isinstance(date, str):      # If date is a string, parse it
        try:
            date = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')          # converts it into a structured Python datetime object via format configurations
        except:
            return 'Just joined'                                         # If parsing fails, return 'Just joined'
    
    # Remove timezone info if present
    if hasattr(date, 'tzinfo') and date.tzinfo is not None:    # If the date has timezone info, remove it to avoid comparison issues
        date = date.replace(tzinfo=None)
    
    # Calculate the difference between now and the given date
    diff = now - date
    
    # Format based on time elapsed
    if diff.days > 365:
        return f"{diff.days//365} year{'s' if diff.days//365 > 1 else ''}"          # If the difference is more than a year, return the number of years
    elif diff.days > 30:
        return f"{diff.days//30} month{'s' if diff.days//30 > 1 else ''}"          # If the difference is more than a month, return the number of months
    elif diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''}"          # If the difference is more than a day, return the number of days
    elif diff.days == 0:
        return 'Just joined'
    else:
        return 'Just joined'

# ============================================================
#                       Xingru's part
#                 Video Thumbnail Generation
# ============================================================
def generate_video_thumbnail(video_path, thumbnail_path, time_offset=0.5):
    """Extract a frame from video at given time offset and save as JPEG."""
    cmd = [
        'ffmpeg',
        '-i', video_path,          # Input video file
        '-ss', str(time_offset),          # Seek to the specified time offset (in seconds)
        '-vframes', '1',          # Extract only one frame
        '-q:v', '2',          # Set quality for JPEG (lower is better, 2 is high quality)
        '-y',          # Overwrite output file if it exists
        thumbnail_path          # Output thumbnail file path
    ]
    # Run the command and handle errors
    try:
        # uses "subprocess" engine module to execute the ffmpeg command list in the system background environment
        # It blocks execution until it returns, ensuring code reliability by asserting validation checks (check=True) and capturing status log strings.
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"Thumbnail generated for {video_path}")
        return True
    except subprocess.CalledProcessError as e:           # If ffmpeg fails, print the error message and return False
        print(f"FFmpeg error for {video_path}: {e.stderr}")
        return False

# ============================================================
# ?'s Routes
# ============================================================
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

# ============================================================
#                       Xingru's part
#                 Campus Abbreviation Filter
# ============================================================
@app.template_filter('campus_abbr')
def campus_abbr(campus):
    if not campus:
        return ''
    if 'Cyberjaya' in campus:
        return 'CYBER'
    if 'Melaka' in campus:
        return 'MLK'
    return ''

# Product image upload folder configuration
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database tables
init_products()      # Product listings
init_messages()      # Chat messages
init_announcements() # Site announcements
init_reviews()       # Seller reviews/ratings

# ============================================================
# Eileen's Routes
# WELCOME PAGE ROUTE
# ============================================================
@app.route('/')
def index():
    return render_template('welcome.html')  

# ============================================================
# LOGIN ROUTE - Handles both GET and POST requests (EILEEN & KETING)
# ===========================================================

# Eileen's part
# ============================================================
@app.route('/login', methods=['GET', 'POST']) 
def login():
     # Handle POST request - user submitting login form
    if request.method == 'POST':
        # Get form data
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember_me = request.form.get('remember_me')
        
        # Validate email domain - only MMU student emails allowed
        if not email.endswith('@student.mmu.edu.my'):
            flash('Only @student.mmu.edu.my email addresses are allowed', 'error')
            return render_template('login.html')
        
        # Query database for user
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT * FROM users WHERE LOWER(email) = LOWER(%s)', (email,))
        user = cur.fetchone()
        cur.close()
        db.close()
        
        #Keting's part
        # ============================================================

        if user and check_password_hash(user['password'], password):
            #  BLOCKED ACCOUNT CHECK
            if user['is_blocked'] == 1:
                flash('❌ This account is permanently blocked. Contact admin for appeal.', 'danger')
                return redirect(url_for('login'))

            # 检查冻结状态
            if user['is_frozen'] == 1:
                frozen_until = user.get('frozen_until')
                
                if frozen_until:
                    now = datetime.now()
                    
                    # 统一转换为 datetime 对象
                    if isinstance(frozen_until, str):
                        try:
                            frozen_until = datetime.strptime(frozen_until, '%Y-%m-%d %H:%M:%S')
                        except:
                            frozen_until = None
                    
                    # 移除时区信息
                    if frozen_until and hasattr(frozen_until, 'tzinfo') and frozen_until.tzinfo:
                        frozen_until = frozen_until.replace(tzinfo=None)
                    
                    if frozen_until and now < frozen_until:
                        days_left = (frozen_until - now).days
                        hours_left = (frozen_until - now).seconds // 3600
                        reason = user.get('freeze_reason') or 'No reason provided'
                        flash(f'⚠️ ACCOUNT FROZEN!\nReason: {reason}\nUnlocks in: {days_left}d {hours_left}h', 'warning')
                        return redirect(url_for('login'))
                    else:
                        # 冻结已过期，自动解冻
                        db_auto = get_db()
                        cur_auto = db_auto.cursor()
                        cur_auto.execute("""
                            UPDATE users 
                            SET is_frozen = 0, frozen_until = NULL, freeze_reason = NULL 
                            WHERE id = %s
                        """, (user['id'],))
                        db_auto.commit()
                        cur_auto.close()
                        db_auto.close()
                        flash('Your account has been automatically unfrozen. Welcome back!', 'success')
                else:
                    # 数据异常，修复
                    db_fix = get_db()
                    cur_fix = db_fix.cursor()
                    cur_fix.execute("UPDATE users SET is_frozen = 0 WHERE id = %s", (user['id'],))
                    db_fix.commit()
                    cur_fix.close()
                    db_fix.close()
            
            # Eileen's part
            # ============================================================
            # NORMAL LOGIN PROCESS
            # ============================================================
            
            # Store user info in session
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['student_id'] = user['student_id']

            # Handle "Remember Me" functionality
            if remember_me:
                # Generate secure token for cookie-based authentication
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
                # Remove remember token if exists
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
            # Invalid credentials
            flash('Invalid email or password', 'error')
            return render_template('login.html')

    # GET request - display login form
    return render_template('login.html')

# ============================================================
# ?'s route
# ============================================================
@app.before_request
def auto_unfreeze_expired():
    if 'user_id' in session or 'admin_logged_in' in session:
        try:
            db = get_db()
            cur = db.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 查找过期的冻结用户
            cur.execute("""
                SELECT id, username, frozen_until FROM users
                WHERE is_frozen = 1 AND frozen_until IS NOT NULL AND frozen_until < %s
            """, (now,))
            expired = cur.fetchall()
            
            # 解冻
            cur.execute("""
                UPDATE users
                SET is_frozen = 0, frozen_until = NULL, freeze_reason = NULL
                WHERE is_frozen = 1 AND frozen_until IS NOT NULL AND frozen_until < %s
            """, (now,))
            
            # 发送通知
            for user in expired:
                cur.execute("""
                    INSERT INTO notifications (user_id, message, created_at, type, is_read)
                    VALUES (%s, %s, NOW(), 'system', 0)
                """, (user['id'],
                      f"✅ Your 7-day freeze has ENDED. Your account is now ACTIVE.\n"
                      f"Your freeze count remains. Please follow community guidelines.\n"
                      f"After 3 freezes, your account will be permanently blocked."))
            
            db.commit()
            cur.close()
            db.close()
            
            if len(expired) > 0:
                print(f"Auto-unfrozen {len(expired)} accounts")
        except Exception as e:
            print(f"auto_unfreeze_expired error: {e}")

# ============================================================
# ?'s route
# ============================================================
@app.before_request
def check_upcoming_meetings():
    if 'user_id' not in session:
        return
    user_id = session['user_id']
    db = get_db()
    cur = db.cursor()
    
    # 获取需要提醒的订单（在 Python 中处理时间比较）
    cur.execute('''
        SELECT id, order_number, meeting_point, meeting_time, last_reminder_sent
        FROM orders
        WHERE (buyer_id = %s OR seller_id = %s)
          AND status IN ('confirmed', 'delivered')
          AND meeting_time IS NOT NULL
          AND meeting_time != ''
          AND (last_reminder_sent IS NULL OR last_reminder_sent < CURRENT_DATE)
        LIMIT 20
    ''', (user_id, user_id))
    
    orders = cur.fetchall()
    now = datetime.now()
    reminded_orders = []
    
    for order in orders:
        meeting_time_str = order['meeting_time']
        if not meeting_time_str:
            continue
        
        try:
            if isinstance(meeting_time_str, str):
                if 'T' in meeting_time_str:
                    meeting_time = datetime.fromisoformat(meeting_time_str.replace('Z', '+00:00'))
                else:
                    meeting_time = datetime.strptime(meeting_time_str, '%Y-%m-%d %H:%M:%S')
            else:
                meeting_time = meeting_time_str
            
            if hasattr(meeting_time, 'tzinfo') and meeting_time.tzinfo:
                meeting_time = meeting_time.replace(tzinfo=None)
            
            time_diff = (meeting_time - now).total_seconds()
            if 0 < time_diff <= 3600:
                reminded_orders.append(order)
        except Exception as e:
            print(f"Error parsing meeting_time: {e}")
            continue
    
    for order in reminded_orders:
        meeting_time = order['meeting_time']
        if isinstance(meeting_time, str):
            meeting_time = meeting_time[:16]
        else:
            meeting_time = meeting_time.strftime('%Y-%m-%d %H:%M')
        
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
            VALUES (%s, %s, NOW(), 'order', %s, 0)
        ''', (user_id,
              f"⏰ Reminder: Order #{order['order_number']} meetup at {meeting_time} at {order['meeting_point']}. Please be on time!",
              order['id']))
        
        cur.execute("UPDATE orders SET last_reminder_sent = NOW() WHERE id = %s", (order['id'],))
    
    db.commit()
    cur.close()
    db.close()

# ============================================================
# ?'s Routes
# ============================================================
# 在 check_upcoming_meetings 之后添加 update_last_seen
@app.before_request
def update_last_seen():
    if 'user_id' in session:
        try:
            db = get_db()
            cur = db.cursor()
            cur.execute("UPDATE users SET last_seen = NOW() WHERE id = %s", (session['user_id'],))
            db.commit()
            cur.close()
            db.close()
        except Exception as e:
            print(f"Update last_seen error: {e}")

# ============================================================
# Eileen's Routes
# ============================================================
# BEFORE REQUEST HOOK - Auto-login via Remember Me cookie
# ============================================================
@app.before_request
def check_remember_me():
    # If already in admin mode, skip automatic login for regular users.
    # Skip if already in admin mode
    if session.get('admin_logged_in'):
        return
    
    # Skip if user already logged in
    if 'user_id' in session:
        return
    
    # Skip public routes that don't require authentication
    public_routes = ['login', 'register', 'forgot_password', 'static', 'welcome', 'admin_login']
    if request.endpoint in public_routes:
        return
    
    # Get remember token from cookie
    token = request.cookies.get('remember_token')
    if not token:
        return
    
    try:
        # Find user with matching token
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT id, username, student_id FROM users WHERE remember_token = %s', (token,))
        user = cur.fetchone()
        cur.close()
        db.close()
        
        # Auto-login the user
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['student_id'] = user['student_id']
            print(f"Auto-logged in user: {user['username']}")
    except Exception as e:
        print(f"Error in check_remember_me: {e}")

# ============================================================
# REGISTER ROUTE - New user registration
# ============================================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':

    # STEP 1: Get form data
        student_id = request.form.get('student_id')
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        gender = request.form.get('gender')

        # Security questions and answers (for password recovery)
        q1 = request.form.get('q1', '').strip()
        a1 = request.form.get('a1', '').strip().lower()
        q2 = request.form.get('q2', '').strip()
        a2 = request.form.get('a2', '').strip().lower()

    # STEP 2: Validation - collect all errors
        errors = []

        # Student ID validation (must be exactly 10 characters, alphanumeric)
        if not student_id or len(student_id) != 10:
            errors.append('Please enter a valid Student ID (10 characters)')
        elif not student_id.replace(' ', '').isalnum():
            errors.append('Student ID must contain only letters and numbers')

        # Email validation (must be MMU student email)
        if not email:
            errors.append('Email is required')
        elif not (email.endswith('@student.mmu.edu.my')):
            err = 'Only MMU email addresses are allowed (@student.mmu.edu.my)'
            errors.append(err)
        
        # Username validation (minimum 3 characters)
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters')
        
        # Password validation - strong password requirements
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
        
        # Confirm password match
        if password != confirm_password:
            errors.append('Passwords do not match')

        # If any validation errors, flash them and return to form
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html')

    # STEP 3: Check for existing user (duplicate registration)
        db = get_db()
        cur = db.cursor()

        # Check if student ID or email already registered
        cur.execute('SELECT * FROM users WHERE student_id = %s OR LOWER(email) = LOWER(%s)', (student_id, email))
        existing = cur.fetchone()
        if existing:
            cur.close()
            db.close()
            flash('Student ID or Email already registered', 'error')
            return render_template('register.html')

        # Check if username already taken
        cur.execute('SELECT * FROM users WHERE LOWER(username) = LOWER(%s)', (username,))
        username_exists = cur.fetchone()
        if username_exists:
            cur.close()
            db.close()
            flash('Username already taken. Please choose another one.', 'error')
            return render_template('register.html')

    # STEP 4: Create new user account
        # Hash password for secure storage
        hashed_password = generate_password_hash(password)

        # Insert new user into database
        cur.execute('''
            INSERT INTO users (
                student_id, email, username, password, gender,
                security_q1, security_a1, security_q2, security_a2
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (student_id, email, username, hashed_password, gender,
              q1, a1, q2, a2))
        
        db.commit()
        
    # STEP 5: Get new user ID and send welcome notification

        # Retrieve the newly created user's ID
        cur.execute('SELECT id FROM users WHERE email = %s', (email,))
        new_user = cur.fetchone()
        
        # Send welcome notification to new user
        if new_user:
            create_notification(
                user_id=new_user['id'],
                message='🎉 Welcome to E-bye! Please complete your profile — especially your campus (Cyberjaya/Melaka) to help buyers find you.',
                notif_type='welcome'
                )
        
        cur.close()
        db.close()

    # STEP 6: Redirect to login page
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))

    # GET request - display registration form
    return render_template('register.html')

# ============================================================
#                       Xingru's route
#                        Home Page
# ============================================================
@app.route('/home')
def home():
    if 'user_id' not in session:          # If the user is not logged in, redirect to login page
        return redirect(url_for('login'))

    db = get_db()          # Get a database connection
    cur = db.cursor()          # Create a cursor to execute SQL queries
    cur.execute('''
        SELECT p.*, u.username as seller_name, u.full_name as seller_full_name, u.id as seller_id, u.campus as seller_campus
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.status IN ('approved') AND u.is_blocked = 0
        ORDER BY p.created_at DESC
    ''')          # Select the latest approved products and their sellers, ordered by creation date
    products_data = cur.fetchall()          # Fetch all the results from the executed query
    cur.close()
    db.close()

    products = []
    for row in products_data:          # Iterate through each product row and process its images
        product = dict(row)          # Convert the row to a dictionary for easier access to its fields

        # retrieves disk image location strings (images) and base64 string storage arrays (images_blob)
        images_str = product.get('images', '')
        images_blob_str = product.get('images_blob', '[]')
        
        # Process base64 images
        base64_list = []
        if images_blob_str and images_blob_str != '[]':          # checks whether the inline image field contains data beyond empty JSON array brackets
            try:
                base64_list = json.loads(images_blob_str)          # Attempts to parse the JSON array string into a live list object
                base64_list = [img for img in base64_list if img.startswith('data:')]          # Filter out any non-base64 strings (e.g., empty strings or invalid data)
            except:
                base64_list = []          # If parsing fails, default to an empty list
        
        if images_str:
            img_list = images_str.split(',')
            image_extensions = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'jfif', 'bmp'}          # Define a set of valid image file extensions for filtering
            image_only = []
            for f in img_list:
                f = f.strip()        # Remove any leading/trailing whitespace from the filename
                ext = f.split('.')[-1].lower()           # extracts the file extension after the dot and convert it to lowercase for case-insensitive comparison
                if ext in image_extensions:          # Check if the file extension is in the set of valid image extensions
                    image_only.append(f)
            product['images_list'] = image_only[:3]          # Restricts the inline image preview container array to the first 3 items
            product['actual_total'] = len(img_list)          # Store the total number of images (including non-image files) for display purposes
            product['image_1'] = image_only[0] if len(image_only) > 0 else None          # Store the first valid image for display; if none, set to None
            product['image_2'] = image_only[1] if len(image_only) > 1 else None
        else:
            # Clean fallback fields for items with no uploaded images, preventing frontend rendering errors
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

# ============================================================
#                       Xingru's route
#                        Search Page
# ============================================================
@app.route('/search')
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    keyword = request.args.get('q', '').strip()          # Retrieve the search keyword from the query parameters and remove leading/trailing whitespace
    
    campus_raw = request.args.get('campus', '')          # Retrieve the raw campus filter string from the query parameters
    if campus_raw:
        campuses = [c.strip() for c in campus_raw.split(',') if c.strip() and c != 'all']          # Split the raw string by commas, remove whitespace, and filter out empty strings and 'all'
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
    """.format(','.join(['%s']*len(statuses)))          # Prepare the SQL query with placeholders for the statuses
    
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


# ============================================================
# Eileen's Routes
# ============================================================
# AVATAR IMAGE ROUTES - Serve and update user avatar
# Serve current user's avatar image
# ============================================================
@app.route('/avatar-image')
def avatar_image():
    """Return the current user's avatar image as JPEG"""
    if 'user_id' not in session:
        return '', 404

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT avatar_blob FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()

    if user and user['avatar_blob']:
        # Convert blob to bytes (handle different blob types)
        avatar_data = bytes(user['avatar_blob']) if hasattr(user['avatar_blob'], 'tobytes') else user['avatar_blob']
        response = make_response(avatar_data)
        response.headers.set('Content-Type', 'image/jpeg')
        response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
        return response
    return '', 404

# ============================================================
# Update user's avatar image
# ============================================================
@app.route('/update-profile-avatar', methods=['POST'])
def update_profile_avatar():
    """Upload and update user's avatar image (max 2MB)"""

    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # Check if file was included in request
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    
    # Get the uploaded file
    file = request.files['avatar']
    # Check if file has a valid name
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400
    
    # Read the image data into memory
    image_data = file.read()

    # Validate file size (max 2MB = 2 * 1024 * 1024 bytes)
    if len(image_data) > 2 * 1024 * 1024: 
        return jsonify({'success': False, 'error': 'Image too large (max 2MB)'}), 400
    
    # Save avatar to database as BLOB
    db = get_db()
    cur = db.cursor()
    cur.execute('UPDATE users SET avatar_blob = %s WHERE id = %s', (image_data, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

# ============================================================
# Serve any user's avatar by user ID (for displaying avatars on other pages)
# ============================================================
# Update user avatar - max 2MB
@app.route('/user-avatar/<int:user_id>')
def user_avatar(user_id):
    """Return a specific user's avatar image by user ID"""

    # Query database for user's avatar blob
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT avatar_blob FROM users WHERE id = %s', (user_id,))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    # If avatar exists, return as image response
    if user and user['avatar_blob']:
        # Convert blob to bytes (handles different blob data types)
        avatar_data = bytes(user['avatar_blob']) if hasattr(user['avatar_blob'], 'tobytes') else user['avatar_blob']
        
        # Build HTTP response with image data
        response = make_response(avatar_data)
        response.headers.set('Content-Type', 'image/jpeg')
        response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate') # Prevent caching
        return response
    return '', 404  # Return 404 if no avatar found

# ============================================================
# Helper function to create image responses from blob data
# ============================================================
def make_blob_response(blob_data, content_type='image/jpeg'):
    """Convert blob data to HTTP response with proper headers"""
    if blob_data is None:
        return None
    
    # Convert various blob formats to bytes
    if hasattr(blob_data, 'tobytes'):
        blob_data = blob_data.tobytes()
    elif isinstance(blob_data, memoryview):
        blob_data = bytes(blob_data)
    response = make_response(blob_data)
    response.headers.set('Content-Type', content_type)
    response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
    return response

# ============================================================
# COVER IMAGE ROUTES - Serve and update user cover image
# ============================================================
# Serve current user's cover image
@app.route('/cover-image')
def cover_image():
    """Return the current user's cover image as JPEG"""
    # User must be logged in
    if 'user_id' not in session:
        return '', 404
    
    # Query database for cover image blob
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT cover_blob FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()

    # If cover exists, return as image response
    if user and user['cover_blob']:
        # Convert blob to bytes
        cover_data = bytes(user['cover_blob']) if hasattr(user['cover_blob'], 'tobytes') else user['cover_blob']
        response = make_response(cover_data)
        response.headers.set('Content-Type', 'image/jpeg')
        response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
        return response
    return '', 404

# ============================================================
# Update user's cover image
# ============================================================
@app.route('/update-cover', methods=['POST'])
def update_cover():
    """Upload and update user's cover image (max 5MB)"""

    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # Check if file was included in request
    if 'cover_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    # Get the uploaded file
    file = request.files['cover_image']
    # Check if file has a valid name
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    #Read the image data into memory
    image_data = file.read()

    if len(image_data) > 5 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Image too large (max 5MB)'}), 400
 
    # Save cover to database as BLOB
    db = get_db()
    cur = db.cursor()
    cur.execute('UPDATE users SET cover_blob = %s WHERE id = %s', 
                (image_data, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

# ============================================================
# BACKGROUND ROUTES - Save, upload, and retrieve user background
# ============================================================
# Save background preset (color or gradient) to user profile
# ============================================================
@app.route('/save-background-preset', methods=['POST'])
def save_background_preset():
    """Save user's selected background color/gradient preset"""
    if 'user_id' not in session:
        return jsonify({'success': False}), 401
    
    # Get background data from request body
    data = request.get_json()
    bg_type = data.get('bg_type', 'default') # 'gradient', 'color', or 'default'
    bg_value = data.get('bg_value') # CSS value (e.g., '#ff0000' or 'linear-gradient(...)')

    # Save to database
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
# Upload custom background image
# ============================================================
@app.route('/upload-background', methods=['POST'])
def upload_background():
    """Upload custom background image (converted to base64)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # Check if file was included in request
    if 'bg_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    
    # Get the uploaded file
    file = request.files['bg_image']
    # Check if file has a valid name
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    # Read the image data into memory
    image_data = file.read()

    if len(image_data) > 5 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'Image too large (max 5MB)'}), 400

    # Convert image to base64 data URL for storage in database
    # Format: data:image/jpeg;base64,/9j/4AAQSkZJRg...
    mime_type = file.content_type or 'image/jpeg'
    bg_value = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('utf-8')}"

    # Save to database with type 'image'
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        UPDATE users SET background_type = %s, background_value = %s WHERE id = %s
    ''', ('image', bg_value, session['user_id']))
    db.commit()
    cur.close()
    db.close()
    
    # Return the base64 value so client can preview immediately
    return jsonify({
        'success': True,
        'bg_value': bg_value
    })

# ============================================================
# API endpoint to get user's background
# ============================================================
@app.route('/api/user/background')
def api_user_background():
    """Return user's background type and value"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # Query database for background settings
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT background_type, background_value
        FROM users WHERE id = %s
    ''', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()

    # Return background data if user exists
    if user:
        return jsonify({
            'success': True,
            'background_type': user['background_type'],
            'background_value': user['background_value']
        })
    return jsonify({'success': False, 'error': 'User not found'}), 404


# ============================================================
# API ENDPOINTS - User Data Retrieval
# ============================================================
# Get user's purchase history
# ============================================================

@app.route('/api/user/purchases')
def api_user_purchases():
    """Return user's purchase orders with product details"""
    if 'user_id' not in session:
        return jsonify([])
    
    # Query database for user's orders as buyer
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
        # Add category emoji for visual display
        item['emoji'] = get_emoji_by_category(item['name'])
        
        # Extract product image from blob or image path
        # Try to extract product image from images_blob (base64 data)
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
        
         # Fallback: use images field (file path)
        if not product_image and item.get('images'):
            img_str = item['images']
            if img_str:
                img_list = [x.strip() for x in img_str.split(',') if x.strip()]
                if img_list:
                    product_image = '/static/uploads/' + img_list[0]
        
        # Store image URL and remove large blob fields from response
        item['product_image'] = product_image
        # Remove large fields
        item.pop('images_blob', None)
        item.pop('images', None)
        purchases.append(item)
    
    return jsonify(purchases)

# ============================================================
# Get user's product listings
# ============================================================
@app.route('/api/user/listings')
def api_user_listings():
    """Return all products listed by the current user"""
    if 'user_id' not in session:
        return jsonify([])
    
    # Query database for user's products
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

        # Try to extract first image from images_blob (base64 data)
        images_blob = item.get('images_blob')
        if images_blob:
            try:
                blob_list = json.loads(images_blob) if isinstance(images_blob, str) else images_blob
                if isinstance(blob_list, list) and len(blob_list) > 0:
                    first_blob = blob_list[0]
                    if isinstance(first_blob, str) and first_blob.startswith('data:'):
                        first_image = first_blob
                        # Detect if it's a video (starts with data:video/)
                        is_video = first_blob.startswith('data:video/')
            except Exception as e:
                print(f"Error parsing images_blob for listing: {e}")

        # Fallback: use images field (file path)
        if not first_image and item.get('images'):
            img_str = item['images']
            if img_str:
                img_list = [x.strip() for x in img_str.split(',') if x.strip()]
                if img_list:
                    first_image = '/static/uploads/' + img_list[0]
                    # Detect video by file extension
                    ext = img_list[0].split('.')[-1].lower()
                    is_video = ext in ['mp4', 'webm', 'mov', 'avi', 'mkv']
        
        # Remove blob field, add image info
        item.pop('images_blob', None)
        item['first_image'] = first_image
        item['first_image_is_video'] = is_video
        listings.append(item)
    
    return jsonify(listings)

# ============================================================
# ORDER CONFIRMATION - Seller confirms order
# ============================================================
@app.route('/api/order/<int:order_id>/confirm', methods=['POST'])
def api_confirm_order(order_id):
    """Seller confirms order with selected meetup location and time"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Get meetup details from request body
    data = request.get_json()
    meeting_point = data.get('meeting_point')
    meeting_time = data.get('meeting_time')
    
    # Validate required fields
    if not meeting_point or not meeting_time:
        return jsonify({'success': False, 'error': 'Meeting point and time are required'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    # Verify the order exists, belongs to current user as seller and is pending
    cur.execute('SELECT * FROM orders WHERE id = %s AND seller_id = %s AND status = %s', 
                (order_id, session['user_id'], 'pending'))
    order = cur.fetchone()
    
    if not order:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Order not found or already confirmed'}), 404
    
    # Get product name for notifications
    cur.execute('SELECT name FROM products WHERE id = %s', (order['product_id'],))
    product = cur.fetchone()
    product_name = product['name'] if product else 'Product'
    
    # Update order: set meeting details and change status to 'confirmed'
    cur.execute('''
        UPDATE orders 
        SET meeting_point = %s, meeting_time = %s, status = 'confirmed', updated_at = NOW()
        WHERE id = %s
    ''', (meeting_point, meeting_time, order_id))
    
    # Mark the product as reserved (no longer available for others)
    cur.execute('UPDATE products SET status = %s WHERE id = %s', ('reserved', order['product_id']))
    
    # Notify buyer that seller confirmed the order
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'order', %s, 0)
    ''', (order['buyer_id'], 
          f"✅ Order #{order['order_number']} has been CONFIRMED by seller! Meeting at: {meeting_point} on {meeting_time}. Product: {product_name}",
          order_id))
    
    # Notify seller that product is now reserved
    create_notification(
        user_id=session['user_id'],
        message=f'🟡 Your product "{product_name}" has been RESERVED for Order #{order["order_number"]}.',
        notif_type='product_reserved',
        related_id=order_id,
        product_id=order['product_id']
    )
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'message': 'Order confirmed successfully'})

# ============================================================
# OFFER MANAGEMENT API ENDPOINTS
# ============================================================
# Get all offers for a specific product (seller only)
# ============================================================
@app.route('/api/product/<int:product_id>/offers')
def get_product_offers(product_id):
    """Return all offers for a product (seller only)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    # Verify current user is the seller of this product
    cur.execute('SELECT seller_id FROM products WHERE id = %s', (product_id,))
    product = cur.fetchone()
    # Return 403 if user is not the seller
    if not product or product['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'error': 'Unauthorized'}), 403
        
    # Query all offers for this product with buyer names
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
    
    # Convert rows to dictionaries
    result = []
    for offer in offers:
        offer_dict = dict(offer)
        result.append(offer_dict)
    
    return jsonify(result)

# ============================================================
# Get count of offers for a product
# ============================================================
@app.route('/api/product/<int:product_id>/offer-count')
def get_product_offer_count(product_id):
    """Return the count of offers for a product"""

    # Return 0 if user is not logged in
    if 'user_id' not in session:
        return jsonify({'count': 0})
    
    # Count total offers for this product
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT COUNT(*) AS count FROM offers WHERE product_id = %s', (product_id,))
    row = cur.fetchone()
    count = row['count'] if row else 0
    cur.close()
    db.close()
    
    return jsonify({'count': count})

# ============================================================
# Send an offer on a product (buyer)
# ============================================================
@app.route('/api/product/<int:product_id>/offers/send', methods=['POST'])
def send_offer(product_id):
    """Buyer sends an offer on a product"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json()
    offer_price = data.get('offer_price')
    message = data.get('message', '')
    
    if not offer_price or float(offer_price) <= 0:
        return jsonify({'success': False, 'error': 'Invalid offer price'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    # Check product exists and is approved
    cur.execute("SELECT id, name, price, seller_id FROM products WHERE id = %s AND status = 'approved'", (product_id,))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    # Cannot offer on own product
    if product['seller_id'] == session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'You cannot make an offer on your own product'}), 400
    
    # Check for existing pending offer
    cur.execute("SELECT id FROM offers WHERE product_id = %s AND buyer_id = %s AND status = 'pending'", 
                (product_id, session['user_id']))
    existing = cur.fetchone()
    
    if existing:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'You already have a pending offer for this product'}), 400
    
    # Create offer
    cur.execute('''
        INSERT INTO offers (product_id, buyer_id, offer_price, original_price, message, status)
        VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING id
    ''', (product_id, session['user_id'], float(offer_price), product['price'], message))
    new_offer_id = cur.fetchone()['id']
    
    # Notify seller
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, product_id, is_read)
        VALUES (%s, %s, NOW(), 'new_offer', %s, %s, 0)
    ''', (product['seller_id'], 
          f"💰 New offer of RM {float(offer_price):.2f} on your listing \"{product['name']}\". Go to My Listings → Offers to accept or decline.",
          new_offer_id, product_id))
    
    # Notify buyer
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'offer_sent', %s, 0)
    ''', (session['user_id'],
          f"Your offer of RM {float(offer_price):.2f} for \"{product['name']}\" has been sent to the seller. You'll be notified when they respond.",
          new_offer_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'message': 'Offer sent successfully', 'offer_id': new_offer_id})

# ============================================================
# Get all offers received by seller
# ============================================================
@app.route('/api/seller/offers')
def api_seller_offers():
    """Return all offers received by the seller"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify([]), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Query all offers for products owned by the seller
    # Includes product details and buyer information
    cur.execute('''
        SELECT o.*, 
               p.name as product_name, 
               p.status as product_status,
               u.username as buyer_name,
               u.full_name as buyer_full_name
        FROM offers o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON o.buyer_id = u.id
        WHERE p.seller_id = %s
        ORDER BY 
            -- Custom order: pending first, then countered, then accepted, then others
            CASE o.status 
                WHEN 'pending' THEN 1 
                WHEN 'countered' THEN 2 
                WHEN 'accepted' THEN 3 
                ELSE 4 
            END,
            o.created_at DESC
    ''', (session['user_id'],))
    
    offers = cur.fetchall()
    cur.close()
    db.close()
    
    # Convert rows to dictionaries
    result = []
    for offer in offers:
        offer_dict = dict(offer)
        result.append(offer_dict)
    
    return jsonify(result)

# ============================================================
# Get count of pending offers for seller
# ============================================================
@app.route('/api/seller/offers/count')
def api_seller_offers_count():
    """Return count of pending offers for the seller"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'count': 0}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Count only pending offers for products owned by the seller
    cur.execute('''
        SELECT COUNT(*) as count
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE p.seller_id = %s AND o.status = 'pending'
    ''', (session['user_id'],))
    
    result = cur.fetchone()
    cur.close()
    db.close()
    
    return jsonify({'count': result['count'] if result else 0})
    
# ============================================================
# OFFER RESPONSE ENDPOINTS - Accept, Reject, Counter
# ============================================================
# Accept an offer (seller)
# ============================================================
@app.route('/api/offer/<int:offer_id>/accept', methods=['POST'])
def api_accept_offer(offer_id):
    """Seller accepts a buyer's offer"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = get_db()
    cur = db.cursor()

    # Get offer details with product info
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id, p.id as product_id, p.price as original_price
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()

    # Check if offer exists
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found'}), 404

    # Check if current user is the seller
    if offer['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    # Update offer status to accepted
    cur.execute("UPDATE offers SET status = 'accepted' WHERE id = %s", (offer_id,))

    accept_price = float(offer['offer_price'])
    product_price = float(offer['original_price'])

    # Build notification message for buyer
    message = f"🎉 Offer ACCEPTED! Your offer of RM {accept_price:.2f} for \"{offer['product_name']}\" has been accepted by the seller. "
    if accept_price < product_price:
        message += f"Click 'Proceed to Checkout' to purchase at the agreed price (RM {accept_price:.2f})"
    else:
        message += f"Click 'Proceed to Checkout' to purchase at the original price (RM {product_price:.2f})"

    # Notify buyer that offer was accepted
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['buyer_id'], message, 'offer_accepted', offer_id))

    # Notify seller that they accepted the offer
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['seller_id'],
          f"You accepted the offer of RM {accept_price:.2f} for \"{offer['product_name']}\". Waiting for buyer to confirm checkout.",
          'offer_accept_confirm', offer_id))

    db.commit()
    cur.close()
    db.close()

    # Return offer details for UI update
    return jsonify({'success': True, 'offer_id': offer['id'], 'offer_price': offer['offer_price'],
                    'product_price': product_price, 'product_name': offer['product_name']})

# ============================================================
# Reject an offer (seller)  Seller rejects a buyer's offer
# ============================================================
@app.route('/api/offer/<int:offer_id>/reject', methods=['POST'])
def api_reject_offer(offer_id):
    """Seller rejects a buyer's offer"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Get offer details with product name
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()
    
    # Check if offer exists
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found'}), 404
    
    # Check if current user is the seller
    if offer['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Update offer status to rejected
    cur.execute("UPDATE offers SET status = 'rejected' WHERE id = %s", (offer_id,))
    
    # Notify buyer that offer was declined
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['buyer_id'],
          f"❌ Offer DECLINED. Your offer of RM {offer['offer_price']:.2f} for \"{offer['product_name']}\" was not accepted by the seller.",
          'offer_rejected', offer_id))
    
    # Notify seller of their action
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

# ============================================================
# Make a counter offer (seller) Seller makes a counter offer to buyer
# ============================================================
@app.route('/api/offer/<int:offer_id>/counter', methods=['POST'])
def counter_offer(offer_id):
    """Seller makes a counter offer to the buyer"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Get counter price from request body
    data = request.get_json()
    counter_price = data.get('counter_price')
    
    # Validate counter price
    if not counter_price or float(counter_price) <= 0:
        return jsonify({'success': False, 'error': 'Invalid counter price'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    # Get offer details with product name
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()
    
    # Check if offer exists
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found'}), 404
    
    # Check if current user is the seller
    if offer['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Update offer with counter price and change status to 'countered'
    cur.execute('''
        UPDATE offers 
        SET counter_price = %s, status = 'countered'
        WHERE id = %s
    ''', (float(counter_price), offer_id))
    
    # Notify buyer that seller sent a counter offer
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, product_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, %s, 0)
    ''', (offer['buyer_id'],
          f"Counter offer received! Seller countered...",
          'offer_countered', offer_id, offer['product_id']))
    
    # Notify seller of their action
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

# ============================================================
# Accept counter offer (buyer)
# ============================================================
@app.route('/api/offer/<int:offer_id>/accept-counter', methods=['POST'])
def accept_counter_offer(offer_id):
    """Buyer accepts seller's counter offer"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    try:
        db = get_db()
        cur = db.cursor()
        
        # Get offer details with product and seller info
        # Must be the buyer and offer must be in 'countered' status
        cur.execute('''
            SELECT o.*, p.name as product_name, p.seller_id, p.price as product_price,
                   u.username as seller_name
            FROM offers o
            JOIN products p ON o.product_id = p.id
            JOIN users u ON p.seller_id = u.id
            WHERE o.id = %s AND o.buyer_id = %s AND o.status = %s
        ''', (offer_id, session['user_id'], 'countered'))
        
        offer = cur.fetchone()
        
        # Check if offer exists and is in countered status
        if not offer:
            cur.close()
            db.close()
            return jsonify({'success': False, 'error': 'Offer not found or not countered'}), 404
        
        # Get the counter price as the agreed price
        agreed_price = float(offer['counter_price'])
        
        # Update offer: set offer_price to counter price, status to 'accepted', clear counter_price
        cur.execute('''
            UPDATE offers 
            SET offer_price = %s, status = %s, counter_price = NULL
            WHERE id = %s
        ''', (agreed_price, 'accepted', offer_id))
        
        # Notify seller that buyer accepted their counter offer
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
            VALUES (%s, %s, NOW(), %s, %s, 0)
        ''', (offer['seller_id'],
              f"🎉 Buyer accepted your counter offer of RM {agreed_price:.2f} for \"{offer['product_name']}\". Waiting for checkout.",
              'offer_accepted', offer_id))
        
        # Notify buyer that they accepted the counter offer
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
            VALUES (%s, %s, NOW(), %s, %s, 0)
        ''', (session['user_id'],
              f"✅ Counter offer accepted! RM {agreed_price:.2f} for \"{offer['product_name']}\". Click 'Proceed to Checkout' to confirm your order.",
              'offer_accepted', offer_id))
        
        db.commit()
        cur.close()
        db.close()
        
        return jsonify({'success': True, 'offer_id': offer_id, 'accepted_price': agreed_price})
        
    except Exception as e:
        # Log error and return 500
        print(f"Error in accept_counter_offer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# Reject counter offer (buyer) Buyer rejects seller's counter offer
# ============================================================
@app.route('/api/offer/<int:offer_id>/reject-counter', methods=['POST'])
def reject_counter_offer(offer_id):
    """Buyer rejects seller's counter offer, reverts to pending"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    try:
        db = get_db()
        cur = db.cursor()
        
        # Get offer - must be buyer and status = 'countered'
        cur.execute('''
            SELECT o.*, p.name as product_name, p.seller_id
            FROM offers o
            JOIN products p ON o.product_id = p.id
            WHERE o.id = %s AND o.buyer_id = %s AND o.status = %s
        ''', (offer_id, session['user_id'], 'countered'))
        
        offer = cur.fetchone()
        
        # Check if offer exists and is in countered status
        if not offer:
            cur.close()
            db.close()
            return jsonify({'success': False, 'error': 'Offer not found or not countered'}), 404
        
        # Revert to pending status and clear counter price
        cur.execute("UPDATE offers SET status = %s, counter_price = NULL WHERE id = %s", ('pending', offer_id))
        
        # Notify seller that buyer rejected their counter offer
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
            VALUES (%s, %s, NOW(), %s, %s, 0)
        ''', (offer['seller_id'],
              f"❌ Buyer rejected your counter offer for \"{offer['product_name']}\". The original offer is still pending.",
              'offer_rejected', offer_id))
        
        db.commit()
        cur.close()
        db.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        # Log error and return 500
        print(f"Error in reject_counter_offer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# USER OFFERS - Get all offers made by user (buyer view)
# ============================================================
@app.route('/api/user/offers')
def api_user_offers():
    """Return all offers made by the current user"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify([])
    
    db = get_db()
    cur = db.cursor()
    
    # Get all offers made by the user with product and seller details
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
        
        # Extract product image from blob (first image only)
        product_image = None
        if item.get('images_blob'):
            try:
                blob_list = json.loads(item['images_blob']) if isinstance(item['images_blob'], str) else item['images_blob']
                if blob_list and len(blob_list) > 0:
                    product_image = blob_list[0]
            except:
                pass
        
        item['product_image'] = product_image
        item.pop('images_blob', None)  # Remove blob to reduce response size
        result.append(item)
    
    return jsonify(result)

# ============================================================
# UTILITY API ENDPOINTS
# ============================================================
# Get current user ID
@app.route('/api/current-user-id')
def api_current_user_id():
    """Return the current user's ID or None if not logged in"""
    if 'user_id' not in session:
        return jsonify({'user_id': None})
    return jsonify({'user_id': session['user_id']})

# Cancel offer (buyer cancels pending offer)
@app.route('/api/offer/<int:offer_id>/cancel', methods=['POST'])
def cancel_offer(offer_id):
    """Buyer cancels their own pending offer"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Verify offer belongs to buyer and is pending
    cur.execute('''
        SELECT o.*, p.seller_id, p.name as product_name, p.id as product_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.buyer_id = %s AND o.status = %s
    ''', (offer_id, session['user_id'], 'pending'))
    
    offer = cur.fetchone()
    
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found or cannot be cancelled'}), 404
    
    # Get offer details
    seller_id = offer['seller_id']
    buyer_id = session['user_id']
    product_name = offer['product_name']
    product_id = offer['product_id']
    offer_price = float(offer['offer_price'])
    
    # Update status to cancelled
    cur.execute('UPDATE offers SET status = %s WHERE id = %s', ('cancelled', offer_id))
    
    # Notify seller
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, product_id, is_read)
        VALUES (%s, %s, NOW(), 'offer_cancelled', %s, %s, 0)
    ''', (seller_id, 
          f'🗑️ Buyer cancelled their offer of RM {offer_price:.2f} for "{product_name}".',
          offer_id, product_id))
    
    # Notify buyer
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, product_id, is_read)
        VALUES (%s, %s, NOW(), 'offer_cancelled', %s, %s, 0)
    ''', (buyer_id,
          f'✅ You have cancelled your offer of RM {offer_price:.2f} for "{product_name}".',
          offer_id, product_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

# ============================================================
# Cancel counter offer (buyer cancels their counter offer)
# ============================================================
@app.route('/api/offer/<int:offer_id>/cancel-counter', methods=['POST'])
def cancel_counter_offer(offer_id):
    """Buyer cancels their counter offer, reverts to pending"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
     # Verify offer belongs to buyer and is in 'countered' status
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.buyer_id = %s AND o.status = %s
    ''', (offer_id, session['user_id'], 'countered'))
    
    offer = cur.fetchone()
    # Check if offer exists and can be cancelled
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Counter offer not found or cannot be cancelled'}), 404
    
    # Revert to pending status and clear counter price
    cur.execute("UPDATE offers SET status = 'pending', counter_price = NULL WHERE id = %s", (offer_id,))
    
    # Notify seller that buyer cancelled their counter offer
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'offer_cancelled', %s, 0)
    ''', (offer['seller_id'],
          f"❌ Buyer cancelled their counter offer for \"{offer['product_name']}\". The original offer of RM {offer['offer_price']:.2f} is still pending.",
          offer_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

# ============================================================
# CREATE ORDER FROM OFFER = Buyer creates order from accepted offer
# ============================================================
@app.route('/api/offer/<int:offer_id>/create-order', methods=['POST'])
def api_create_order_from_offer(offer_id):
    """Create an order from an accepted offer (buyer side)"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Get meetup details from request
    data = request.get_json()
    meetup_locations = data.get('meetup_locations', [])
    meeting_dates = data.get('meeting_dates', [])
    
    # Validate meetup locations
    if not meetup_locations:
        return jsonify({'success': False, 'error': 'Please select meetup locations'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    # Get offer details - must be buyer
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id, p.price as product_price
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.buyer_id = %s
    ''', (offer_id, session['user_id']))
    
    offer = cur.fetchone()
    
    # Check if offer exists
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found or you are not the buyer'}), 404
    
    # Check if order already placed
    if offer['status'] == 'ordered':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Order has already been placed for this offer'}), 400
    
    # Check if offer is accepted
    if offer['status'] != 'accepted':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': f'Offer is not ready for checkout (status: {offer["status"]})'}), 400
    
    # Generate unique order number
    order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    
    # Convert dates list to comma-separated string
    meeting_dates_str = ','.join(meeting_dates) if meeting_dates else ''
    
    # Insert new order into database
    cur.execute('''
        INSERT INTO orders (order_number, product_id, buyer_id, seller_id, offer_price,
                           meeting_point, meeting_time, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW()) RETURNING id
    ''', (order_number, offer['product_id'], offer['buyer_id'], offer['seller_id'],
          offer['offer_price'], ','.join(meetup_locations), meeting_dates_str))
    
    order_id = cur.fetchone()['id']

    # Mark product as reserved (no longer available for others)
    cur.execute("UPDATE products SET status = 'reserved' WHERE id = %s", (offer['product_id'],))

    # Remove product from buyer's cart if exists
    cur.execute('DELETE FROM cart_items WHERE user_id = %s AND product_id = %s', 
                (session['user_id'], offer['product_id']))
    
    # Update offer status to 'ordered'
    cur.execute("UPDATE offers SET status = 'ordered' WHERE id = %s", (offer_id,))
    
    # Mark product as sold
    cur.execute("UPDATE products SET status = 'sold' WHERE id = %s", (offer['product_id'],))
    
    # Notify seller about new order
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (offer['seller_id'],
          f"🛒 NEW ORDER #{order_number}! {session['username']} has placed an order for \"{offer['product_name']}\" at RM {offer['offer_price']:.2f}. " +
          f"Preferred locations: {', '.join(meetup_locations)}. " +
          (f"Preferred times: {meeting_dates_str}" if meeting_dates else ""),
          'order_created', order_id))
    
    # Notify buyer that order was created
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (session['user_id'],
          f"📋 Order #{order_number} created successfully for \"{offer['product_name']}\" at RM {offer['offer_price']:.2f}. " +
          f"Meetup locations: {', '.join(meetup_locations)}. " +
          (f"Preferred times: {meeting_dates_str}" if meeting_dates else "") +
          " Waiting for seller to confirm.",
          'order_created', order_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'order_id': order_id, 'order_number': order_number})

# ============================================================
# Create order from accepted offer (seller side)
# ============================================================
@app.route('/api/offer/<int:offer_id>/create-order-from-accept', methods=['POST'])
def api_create_order_from_accept(offer_id):
    """Create an order from an accepted offer (seller side)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Get meetup details from request
    data = request.get_json()
    meetup_locations = data.get('meetup_locations', [])
    meeting_dates = data.get('meeting_dates', [])
    
    # Validate meetup locations
    if not meetup_locations:
        return jsonify({'success': False, 'error': 'Please select meetup locations'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    # Get offer details - must be seller and status must be 'accepted'
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id, p.price as product_price
        FROM offers o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.seller_id = %s AND o.status = 'accepted'
    ''', (offer_id, session['user_id']))
    
    offer = cur.fetchone()
    
    # Check if offer exists and is accepted
    if not offer:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Offer not found or not accepted'}), 404
    
    # Generate order number
    order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    
    # Convert dates list to comma-separated string
    meeting_dates_str = ','.join(meeting_dates) if meeting_dates else ''
    
    # Insert new order into database
    cur.execute('''
        INSERT INTO orders (order_number, product_id, buyer_id, seller_id, offer_price,
                           meeting_point, meeting_time, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW()) RETURNING id
    ''', (order_number, offer['product_id'], offer['buyer_id'], offer['seller_id'],
          offer['offer_price'], ','.join(meetup_locations), meeting_dates_str))
    
    order_id = cur.fetchone()['id']
    
    # Mark product as reserved
    cur.execute("UPDATE products SET status = 'reserved' WHERE id = %s", (offer['product_id'],))

     # Remove product from buyer's cart
    cur.execute('DELETE FROM cart_items WHERE user_id = %s AND product_id = %s', 
                (offer['buyer_id'], offer['product_id']))
    
    # Update offer status to 'ordered'
    cur.execute("UPDATE offers SET status = 'ordered' WHERE id = %s", (offer_id,))
    cur.execute("UPDATE products SET status = 'sold' WHERE id = %s", (offer['product_id'],))
    
    # Notify buyer that order was created
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'order_created', %s, 0)
    ''', (offer['buyer_id'],
          f"🛒 Order #{order_number} created! Seller has confirmed meetup: {', '.join(meetup_locations)}. Preferred times: {meeting_dates_str}",
          order_id))
    
    # Notify seller that order was created
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'order_created', %s, 0)
    ''', (session['user_id'],
          f"📋 Order #{order_number} created for \"{offer['product_name']}\" at RM {offer['offer_price']:.2f}",
          order_id))
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'order_id': order_id, 'order_number': order_number})

# ============================================================
# Get offer details for checkout
# ============================================================
@app.route('/api/offer/<int:offer_id>/details', methods=['GET'])
def api_offer_details(offer_id):
    """Return detailed offer information for checkout"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Get offer details with product and seller information
    cur.execute('''
        SELECT o.id, o.offer_price, o.status, o.counter_price,
               p.id as product_id, p.name as product_name, p.price as product_price,
               p.condition as product_condition, p.status as product_status,
               p.images_blob, p.images, p.seller_id, o.buyer_id,
               u.campus as seller_campus
        FROM offers o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON p.seller_id = u.id
        WHERE o.id = %s
    ''', (offer_id,))
    offer = cur.fetchone()
    cur.close()
    db.close()
    
    # Check if offer exists
    if not offer:
        return jsonify({'success': False, 'error': 'Offer not found'}), 404
    
    # Extract product image from blob (prefer base64 data)
    product_image = None
    if offer.get('images_blob'):
        try:
            blob_list = json.loads(offer['images_blob']) if isinstance(offer['images_blob'], str) else offer['images_blob']
            if blob_list and len(blob_list) > 0:
                product_image = blob_list[0]
        except:
            pass
    
    # Fallback: use images field (file path)
    if not product_image and offer.get('images'):
        img_str = offer['images']
        if img_str:
            img_list = [x.strip() for x in img_str.split(',') if x.strip()]
            if img_list:
                product_image = '/static/uploads/' + img_list[0]
    
    # Return all offer details for checkout
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
        'buyer_id': offer['buyer_id'],
        'seller_campus': offer['seller_campus']  # Used to suggest meetup locations
    })

# ============================================================
# API - BUY NOW - Instant purchase without making an offer
# ============================================================
# Eileen & Xingru work together

#Eileen's part
# ============================================================
@app.route('/api/buy-now', methods=['POST'])
def api_buy_now():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Get request data
    data = request.get_json()
    product_id = data.get('product_id')
    meetup_locations = data.get('meetup_locations', [])
    meeting_dates = data.get('meeting_dates', [])  # Array of preferred dates/times
    meeting_dates_str = ','.join(meeting_dates) if meeting_dates else ''

    # Validate required data
    if not product_id or not meetup_locations:
        return jsonify({'success': False, 'error': 'Missing required data'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    # Get product details - must be 'approved' status
    cur.execute("SELECT id, name, price, seller_id FROM products WHERE id = %s AND status = 'approved'", (product_id,))
    product = cur.fetchone()
    
    # Check if product exists and is available
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found or already sold/reserved'}), 404
    
    # Cannot buy your own product
    if product['seller_id'] == session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'You cannot buy your own product'}), 400
    
    # Generate unique order number
    order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    
    # Create order with 'pending' status - waiting for seller confirmation
    cur.execute('''
        INSERT INTO orders (order_number, product_id, buyer_id, seller_id, offer_price,
                            meeting_point, meeting_time, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW())
        RETURNING id
    ''', (order_number, product_id, session['user_id'], product['seller_id'],
          product['price'], ','.join(meetup_locations), meeting_dates_str))
    
    order_id = cur.fetchone()['id']

    #Xingru's part
    # ============================================================
    # Mark product as reserved immediately (added by Xingru)
    cur.execute("UPDATE products SET status = 'reserved' WHERE id = %s", (product_id,))

    # Delete from cart if it was there (added by Xingru)
    cur.execute('DELETE FROM cart_items WHERE user_id = %s AND product_id = %s', 
            (session['user_id'], product_id))
    
    # Note: Product status remains 'reserved' until seller confirms
    # After confirmation, it becomes 'sold'
    # Notify seller about the new order
    # cur.execute("UPDATE products SET status = 'reserved' WHERE id = %s", (product_id,))  # ← 删除这行！
    
    # Notify seller about the new order
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (product['seller_id'],
        f"🛒 BUY NOW — Order #{order_number}! {session['username']} purchased \"{product['name']}\" for RM {product['price']:.2f}. Preferred meetup: {', '.join(meetup_locations)}. Preferred times: {meeting_dates_str}. Go to My Orders to confirm.",
        'order_created', order_id))
    
    # Notify buyer that order was placed
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), %s, %s, 0)
    ''', (session['user_id'],
          f"✅ Order #{order_number} placed for \"{product['name']}\" at RM {product['price']:.2f}. Meetup: {', '.join(meetup_locations)}. Preferred times: {meeting_dates_str}. Waiting for seller to confirm.",
          'order_created', order_id))

    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'order_id': order_id, 'order_number': order_number})

# ============================================================
#                       Xingru's route
#                       Add to Cart
# ============================================================
@app.route('/add-to-cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    db = get_db()
    cur = db.cursor()

    # Check product exists and is approved
    cur.execute('SELECT id, status FROM products WHERE id = %s', (product_id,))
    product = cur.fetchone()
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    if product['status'] != 'approved':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product is not available'}), 400

    # Insert into cart (ignore duplicate)
    try:
        cur.execute('''
            INSERT INTO cart_items (user_id, product_id) VALUES (%s, %s)
        ''', (session['user_id'], product_id))
        db.commit()
        cur.close()
        db.close()
        return jsonify({'success': True, 'message': 'Added to cart'})
    except Exception as e:
        db.rollback()
        cur.close()
        db.close()
        # Unique violation = already in cart
        return jsonify({'success': False, 'error': 'Item already in cart'}), 400

# ============================================================
#                       Xingru's route
#                       Shopping Cart
# ============================================================
@app.route('/cart')
def shopping_cart():
    if 'user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))
    return render_template('shopping_cart.html')

# ============================================================
# ?'s Routes
# ============================================================
@app.route('/api/cart')
def api_get_cart():
    if 'user_id' not in session:
        return jsonify({'available': [], 'unavailable': []})

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT ci.product_id, ci.added_at, p.name as product_name, p.price, p.status, p.category,
               u.id as seller_id, u.username as seller_name, u.full_name as seller_full_name,
               u.avatar_blob as seller_avatar,
               p.images_blob, p.images
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.id
        JOIN users u ON p.seller_id = u.id
        WHERE ci.user_id = %s
        ORDER BY ci.added_at DESC
    ''', (session['user_id'],))
    items = cur.fetchall()
    
    available = []
    unavailable = []
    for item in items:
        item_dict = dict(item)
        
        # Convert datetime to string
        if item_dict.get('added_at'):
            item_dict['added_at'] = item_dict['added_at'].isoformat()
        else:
            item_dict['added_at'] = None
        
        # Convert avatar blob to base64 if exists
        if item_dict.get('seller_avatar'):
            import base64
            try:
                avatar_b64 = base64.b64encode(bytes(item_dict['seller_avatar'])).decode('utf-8')
                item_dict['seller_avatar'] = f"data:image/jpeg;base64,{avatar_b64}"
            except:
                item_dict['seller_avatar'] = None
        else:
            item_dict['seller_avatar'] = None
        
        # Get product image safely
        product_image = '/static/uploads/placeholder.jpg'
        try:
            blob = item_dict.get('images_blob')
            if blob and blob != '[]':
                import json
                blob_list = json.loads(blob)
                if isinstance(blob_list, list) and len(blob_list) > 0:
                    first = blob_list[0]
                    if isinstance(first, str):
                        if first.startswith('data:'):
                            product_image = first
                        else:
                            product_image = '/static/uploads/' + first
        except Exception as e:
            print(f"Error parsing images_blob: {e}")
        
        if product_image == '/static/uploads/placeholder.jpg' and item_dict.get('images'):
            img_list = item_dict['images'].split(',')
            if img_list and img_list[0].strip():
                product_image = '/static/uploads/' + img_list[0].strip()
        
        item_dict['product_image'] = product_image
        item_dict.pop('images_blob', None)
        item_dict.pop('images', None)
        
        # Query offer status for this product (cursor is still open)
        cur.execute('''
            SELECT status FROM offers
            WHERE product_id = %s AND buyer_id = %s
            AND status IN ('pending', 'accepted')
            ORDER BY created_at DESC LIMIT 1
        ''', (item_dict['product_id'], session['user_id']))
        offer_row = cur.fetchone()
        item_dict['user_offer_status'] = offer_row['status'] if offer_row else None

        if item_dict['status'] == 'approved':
            available.append(item_dict)
        else:
            unavailable.append(item_dict)
    
    cur.close()
    db.close()

    return jsonify({'available': available, 'unavailable': unavailable})

@app.route('/api/cart/check/<int:product_id>')
def cart_check(product_id):
    if 'user_id' not in session:
        return jsonify({'in_cart': False})
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT 1 FROM cart_items WHERE user_id = %s AND product_id = %s', 
                (session['user_id'], product_id))
    exists = cur.fetchone() is not None
    cur.close()
    db.close()
    return jsonify({'in_cart': exists})

@app.route('/cart/remove', methods=['POST'])
def cart_remove():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json()
    product_ids = data.get('product_ids', [])
    if not product_ids:
        return jsonify({'success': False, 'error': 'No items specified'}), 400

    db = get_db()
    cur = db.cursor()
    placeholders = ','.join(['%s'] * len(product_ids))
    cur.execute(f'''
        DELETE FROM cart_items 
        WHERE user_id = %s AND product_id IN ({placeholders})
    ''', [session['user_id']] + product_ids)
    db.commit()
    cur.close()
    db.close()
    return jsonify({'success': True})

@app.route('/cart/remove-unavailable', methods=['POST'])
def cart_remove_unavailable():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute('''
        DELETE FROM cart_items 
        WHERE user_id = %s 
        AND product_id IN (
            SELECT id FROM products WHERE status != 'approved'
        )
    ''', (session['user_id'],))
    db.commit()
    cur.close()
    db.close()
    return jsonify({'success': True})

@app.route('/cart/clear', methods=['POST'])
def cart_clear():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    db = get_db()
    cur = db.cursor()
    cur.execute('DELETE FROM cart_items WHERE user_id = %s', (session['user_id'],))
    db.commit()
    cur.close()
    db.close()
    return jsonify({'success': True})

# ============================================================
# Eileen's Routes - SELECT CAMNPUS API
# ============================================================
@app.route('/api/product/<int:product_id>/seller-campus')
def api_product_seller_campus(product_id):
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT u.campus FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.id = %s
    ''', (product_id,))
    row = cur.fetchone()
    cur.close()
    db.close()
    return jsonify({'campus': row['campus'] if row else 'Cyberjaya'})

# ============================================================
# ?'s Routes
# ============================================================
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

# ============================================================
# ?'s Routes
# ============================================================
@app.route('/api/notifications/all')
def get_all_notifications():
    if 'user_id' not in session:
        return jsonify([]), 401
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT n.*, 
               p.name as product_name, 
               p.images_blob as product_images
        FROM notifications n
        LEFT JOIN products p ON n.product_id = p.id
        WHERE n.user_id = %s
          AND n.created_at >= NOW() - INTERVAL '30 days'
        ORDER BY n.created_at DESC
        LIMIT 200
    ''', (session['user_id'],))
    
    notifications = cur.fetchall()
    cur.close()
    db.close()
    
    result = []
    for n in notifications:
        n_dict = dict(n)
        # 提取产品图片（第一张）
        product_image = None
        if n_dict.get('product_images'):
            try:
                import json
                images = json.loads(n_dict['product_images']) if isinstance(n_dict['product_images'], str) else n_dict['product_images']
                if images and len(images) > 0:
                    product_image = images[0]
            except:
                pass
        n_dict['product_image'] = product_image
        n_dict.pop('product_images', None)
        result.append(n_dict)
    
    return jsonify(result)

# ============================================================
# ?'s Routes
# ============================================================
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

@app.route('/api/chat/mark-read/<int:other_user_id>', methods=['POST'])
def mark_chat_read(other_user_id):
    if 'user_id' not in session:
        return jsonify({'success': False}), 401
    
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        UPDATE messages 
        SET is_read = 1 
        WHERE sender_id = %s AND receiver_id = %s AND is_read = 0
    ''', (other_user_id, session['user_id']))
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True})

# ============================================================
# API - GET PRODUCT - Get single product by ID (for editing)
#                       Xingru's route
#                         Product API
# ============================================================
@app.route('/api/product/<int:product_id>')
def api_get_product(product_id):
    """Return product details for editing (seller only)"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    db = get_db()
    cur = db.cursor()
    
    # Get product - must belong to current user
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

    # Parse and format images_blob for JSON response
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


# ============================================================
# API - GET PRODUCT IMAGE - Serve a specific product image by index
# ============================================================
@app.route('/api/product-image/<int:product_id>/<int:index>')
def api_product_image(product_id, index):
    """Return a specific product image at the given index (0-based)"""
    import base64 as b64
    
    db = get_db()
    cur = db.cursor()

    # Get product images
    cur.execute('SELECT images_blob, images FROM products WHERE id = %s', (product_id,))
    row = cur.fetchone()
    cur.close()
    db.close()

    if not row:
        return '', 404

    # Try images_blob first (base64 data)
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

    # Fallback: use images field (file path)
    if row.get('images'):
        parts = [p.strip() for p in row['images'].split(',') if p.strip()]
        if parts and index < len(parts):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], parts[index])
            if os.path.exists(filepath):
                from flask import send_file
                return send_file(filepath)

    return '', 404

# ============================================================
# API - UPDATE PRODUCT - Update product details (without images)
# ============================================================
@app.route('/api/product/<int:product_id>/update', methods=['PUT'])
def api_update_product(product_id):
    """Update product details (text fields only)"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = get_db()
    cur = db.cursor()

    # Verify product belongs to user and is not sold
    cur.execute('SELECT id, status FROM products WHERE id = %s AND seller_id = %s', (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    # Sold products cannot be edited
    if product['status'] == 'sold':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Sold products cannot be edited'}), 400

    # Get form data
    data = request.get_json()
    name = data.get('name', '').strip()
    price = data.get('price', 0)
    description = data.get('description', '').strip()
    condition = data.get('condition', '')
    category = data.get('category', '')

    # Validate required fields
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

    # Update product (status goes back to pending for admin review)
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
# API - UPDATE PRODUCT FULL - Update product with media (images/videos)
# ============================================================
@app.route('/api/product/<int:product_id>/update-full', methods=['POST'])
def api_update_product_full(product_id):
    """
    Update product with media files (images and videos)
    This endpoint handles product updates including:
    - Text fields: name, price, description, condition, category
    - Media files: images and videos (max 12 files)
    - Converts base64 data URIs to actual files on server
    
    Returns:
        JSON: {success: True/False, error: message if failed}
    """
    
    # ============================================================
    # STEP 1: Authentication - Verify user is logged in
    # ============================================================
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Session expired. Please login again.'}), 401

    db = get_db()
    cur = db.cursor()
    
    # ============================================================
    # STEP 2: Authorization - Verify product belongs to current user and is not sold
    # ============================================================
    cur.execute('SELECT id, images, status FROM products WHERE id = %s AND seller_id = %s', 
                (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    # Sold products cannot be edited
    if product['status'] == 'sold':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Sold products cannot be edited'}), 400

    # ============================================================
    # STEP 3: Get and validate form data
    # ============================================================
    name = request.form.get('name', '').strip()
    price = request.form.get('price', 0)
    description = request.form.get('description', '').strip()
    condition = request.form.get('condition', '')
    category = request.form.get('category', '')
    images_blob_json = request.form.get('images_blob', '')

    # Validate required fields
    if not name or not price or not description:
        return jsonify({'success': False, 'error': 'Name, price and description required'}), 400

    # Validate price is a valid number
    try:
        price = float(price)
    except:
        return jsonify({'success': False, 'error': 'Invalid price'}), 400

    # ============================================================
    # STEP 4: Validate media count (maximum 12 files)
    # ============================================================
    MAX_MEDIA = 12
    if images_blob_json:
        try:
            blob_check = json.loads(images_blob_json)
            if isinstance(blob_check, list) and len(blob_check) > MAX_MEDIA:
                return jsonify({'success': False,
                                'error': f'Maximum {MAX_MEDIA} media files allowed.'}), 400
        except Exception:
            pass

    # ============================================================
    # STEP 5: Process and save media files from base64 data URIs
    # ============================================================
    saved_filenames = []

    if images_blob_json:
        try:
            # Parse the JSON array of base64 data URIs
            blob_list = json.loads(images_blob_json)
            
            for idx, blob in enumerate(blob_list):
                # Skip if not a valid data URI
                if not isinstance(blob, str) or not blob.startswith('data:'):
                    continue
                
                # Parse data URI format: data:image/jpeg;base64,xxxxx
                header, b64data = blob.split(',', 1)
                mime_type = header.split(';')[0].split(':')[1]
                
                # Map MIME type to file extension
                ext_map = {
                    'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif', 'image/webp': 'webp',
                    'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov'
                }
                ext = ext_map.get(mime_type, 'bin')
                if ext == 'bin':
                    continue
                
                # Decode base64 data and save to file
                file_data = base64.b64decode(b64data)
                unique_name = f"product_{product_id}_{uuid.uuid4().hex}.{ext}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
                with open(save_path, 'wb') as f:
                    f.write(file_data)
                saved_filenames.append(unique_name)
                
        except Exception as e:
            print(f"Error processing images_blob: {e}")
            saved_filenames = []

    # ============================================================
    # STEP 6: Join filenames as comma-separated string for storage
    # ============================================================
    images_str = ','.join(saved_filenames)

    # ============================================================
    # STEP 7: Update product in database
    # ============================================================
    # Status set to 'pending' to require admin re-approval after edit
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

    # ============================================================
    # STEP 8: Return success response
    # ============================================================
    return jsonify({'success': True})

# ============================================================
# API - UPLOAD PRODUCT IMAGES - Upload images for a product (deprecated)
# ============================================================
@app.route('/api/product/<int:product_id>/upload-images', methods=['POST'])
def upload_product_images(product_id):
    """Upload additional images for a product"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Verify product belongs to user
    cur.execute('SELECT id FROM products WHERE id = %s AND seller_id = %s', 
                (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    # Get existing images and add new ones
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


# ============================================================
# API - DELETE PRODUCT - Delete a product listing
# ============================================================
@app.route('/api/product/<int:product_id>/delete', methods=['DELETE'])
def api_delete_product(product_id):
    """Delete a product and all related data"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()
    
    # Get product info (including name for notification)
    cur.execute('SELECT id, name, status, seller_id FROM products WHERE id = %s AND seller_id = %s', 
                (product_id, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    # Sold products cannot be deleted
    if product['status'] == 'sold':
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Sold products cannot be deleted'}), 400
    
    product_name = product['name']
    
    # Delete related data in correct order (child tables first to avoid FK errors)
    cur.execute('DELETE FROM cart_items WHERE product_id = %s', (product_id,))
    cur.execute('DELETE FROM notifications WHERE product_id = %s', (product_id,))
    cur.execute('''
        DELETE FROM notifications WHERE related_id IN (
            SELECT id FROM offers WHERE product_id = %s
        )
    ''', (product_id,))
    cur.execute('DELETE FROM offers WHERE product_id = %s', (product_id,))
    cur.execute('DELETE FROM products WHERE id = %s', (product_id,))
    db.commit()
    cur.close()
    db.close()
    
    # Notify user of deletion
    create_notification(
        user_id=session['user_id'],
        message=f'🗑️ You have deleted your product "{product_name}".',
        notif_type='product_deleted',
        product_id=product_id
    )
    
    return jsonify({'success': True})


# ============================================================
# PROFILE PAGE - My Profile
# ============================================================
@app.route('/my-profile')
def my_profile():
    """Display user's profile page with listings, purchases, and orders"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))

    db = get_db()
    user_id = session['user_id']
    cur = db.cursor()

    # Get user information
    cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    user = cur.fetchone()

    if not user:
        session.clear()
        flash('User not found', 'error')
        return redirect(url_for('login'))

    # Count user's listings
    cur.execute('SELECT COUNT(*) AS count FROM products WHERE seller_id = %s', (user_id,))
    listing_count = cur.fetchone()['count'] 

    # Count sold items (completed orders as seller)
    sold_count = 0
    try:
        cur.execute("SELECT COUNT(*) AS count FROM orders WHERE seller_id = %s AND status = 'completed'", (user_id,))
        sold_count = cur.fetchone()['count']  
    except:
        pass

    # Calculate trust score
    trust_score = calculate_trust_score(user, listing_count)

    # Calculate response rate
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


# ============================================================
# EDIT PROFILE PAGE - Display edit profile form with user data
# ============================================================
@app.route('/edit_profile', methods=['GET'])
def edit_profile():
    """
    Display edit profile page with user data and statistics
    Shows the user's current profile information in editable form
    Also displays user statistics: listings count, sold count, trust score, response rate
    
    Returns:
        Rendered edit_profile.html template with user data
        Redirects to login if user is not authenticated
    """
    
    # ============================================================
    # STEP 1: Authentication - Check if user is logged in
    # ============================================================
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    cur = db.cursor()
    
    # ============================================================
    # STEP 2: Get user profile data
    # ============================================================
    cur.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()

    # ============================================================
    # STEP 3: Get user statistics
    # ============================================================
    
    # Count total listings
    cur.execute('SELECT COUNT(*) AS count FROM products WHERE seller_id = %s', (session['user_id'],))
    listing_count = cur.fetchone()['count']  

    # ============================================================
    # STEP 4: Calculate Trust Score
    # ============================================================
    # Trust score is calculated based on:
    # - Profile completeness (avatar, bio, contact, full name)
    # - Account age (longer = more trustworthy)
    # - Number of active listings
    # - Active hours set
    # - Gender specified
    trust_score = calculate_trust_score(user, listing_count)

    # ============================================================
    # STEP 5: Calculate Response Rate
    # ============================================================
    # Response rate is calculated based on:
    # - Base score: 50
    # - Has active listings: +15
    # - Bio and contact filled: +10
    # - Active hours set: +10
    # - Avatar uploaded: +5
    # - Capped at 98, minimum 40
    response_rate = 50
    
    if listing_count > 0:
        response_rate += 15
    
    if user['bio'] and user['contact']:
        response_rate += 10
    if user['active_hours'] and user['active_hours'] != 'Not set':
        response_rate += 10
    if user['avatar_blob']:
        response_rate += 5
    
    response_rate = min(response_rate, 98)   # Cap at 98%
    response_rate = max(response_rate, 40)   # Minimum 40%

    # ============================================================
    # STEP 6: Count sold items (completed orders as seller)
    # ============================================================
    sold_count = 0
    try:
        cur.execute("SELECT COUNT(*) AS count FROM orders WHERE seller_id = %s AND status = 'completed'", (session['user_id'],))
        sold_count = cur.fetchone()['count']
    except:
        pass

    # ============================================================
    # STEP 7: Clean up and render template
    # ============================================================
    cur.close()
    db.close()

    return render_template(
        'edit_profile.html',
        user=user,                # User object with all profile data
        listing_count=listing_count,   # Number of active listings
        sold_count=sold_count,         # Number of sold items
        trust_score=trust_score,       # Calculated trust score (0-100)
        response_rate=response_rate    # Calculated response rate (0-100)
    )

# ============================================================
# API - CHECK ADMIN STATUS - Verify if user is admin
# ============================================================
@app.route('/api/user/is-admin')
def api_user_is_admin():
    """Check if current user has admin privileges"""
    
    # Check if user is logged in
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
# SWITCH TO ADMIN MODE Button - Convert user session to admin session
# ============================================================
@app.route('/switch-to-admin')
def switch_to_admin():
    """
    Switch user session to admin mode without logging out
    This allows admin users to toggle between user and admin views
    Pre-requisite: User must be logged in and have is_admin = 1
    
    Returns:
        Redirect to admin dashboard if user is admin
        Redirect to edit profile with error message if not admin
        Redirect to login if user is not logged in
    """
    
    # ============================================================
    # STEP 1: Authentication - Check if user is logged in
    # ============================================================
    if 'user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))
    
    # ============================================================
    # STEP 2: Authorization - Check if user has admin privileges
    # ============================================================
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT is_admin, email, username FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    # ============================================================
    # STEP 3: Verify admin status and switch session
    # ============================================================
    if user and user['is_admin'] == 1:
        # User is admin - switch to admin mode
        session['admin_logged_in'] = True
        session['admin_email'] = user['email']
        session['admin_username'] = user['username']
        
        flash('Switched to Admin mode', 'success')
        return redirect(url_for('admin_dashboard'))
    else:
        # User is not admin - deny access
        flash('You do not have admin privileges', 'error')
        return redirect(url_for('edit_profile'))

# ============================================================
# UPDATE PROFILE - Save profile changes
# ============================================================
@app.route('/update-profile', methods=['POST'])
def update_profile():
    """Update user profile information"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Get form data
    username = request.form.get('username')
    full_name = request.form.get('full_name')
    bio = request.form.get('bio')
    contact = request.form.get('contact')
    gender = request.form.get('gender')
    active_hours = request.form.get('active_hours')
    campus = request.form.get('campus')
    
    # Campus is required
    if not campus:
        flash('📍 Please select your campus (Melaka or Cyberjaya)', 'error')
        return redirect(url_for('edit_profile'))

    db = get_db()
    cur = db.cursor()

    # Check if username is already taken by another user
    cur.execute('SELECT id FROM users WHERE username = %s AND id != %s', (username, session['user_id']))
    existing = cur.fetchone()
    if existing:
        cur.close()
        db.close()
        flash('Username already taken', 'error')
        return redirect(url_for('edit_profile'))

    # Update user profile
    cur.execute("""
        UPDATE users
        SET username = %s, full_name = %s, bio = %s,
            contact = %s, gender = %s, active_hours = %s, campus = %s
        WHERE id = %s
    """, (username, full_name, bio, contact, gender, active_hours, campus, session['user_id']))

    db.commit()
    cur.close()
    db.close()

    # Update session username
    session['username'] = username
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('home'))

# ============================================================
# CHANGE PASSWORD - Change user password
# ============================================================
@app.route('/change-password', methods=['POST'])
def change_password():
    """Change user password with current password verification"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Get form data
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

    # Verify current password
    if not check_password_hash(user['password'], current_password):
        cur.close()
        db.close()
        flash('Current password is incorrect', 'error')
        return redirect(url_for('edit_profile'))

    # Check if new passwords match
    if new_password != confirm_password:
        cur.close()
        db.close()
        flash('New passwords do not match', 'error')
        return redirect(url_for('edit_profile'))

    # Hash and save new password
    hashed = generate_password_hash(new_password)
    cur.execute('UPDATE users SET password = %s WHERE id = %s', (hashed, session['user_id']))
    db.commit()
    cur.close()
    db.close()

    flash('Password changed successfully!', 'success')
    return redirect(url_for('edit_profile'))

# ============================================================
# DELETE ACCOUNT - Permanently delete user account
# ============================================================
@app.route('/delete-account', methods=['POST'])
def delete_account():
    """Permanently delete user account and all related data"""
    
    # Check if user is logged in
    if 'user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))

    # Get form data
    password = request.form.get('password', '')
    confirm_text = request.form.get('confirm_text', '')
    user_id = session['user_id']

    # Validate confirmation text
    if confirm_text != 'DELETE':
        flash('Please type DELETE to confirm', 'error')
        return redirect(url_for('edit_profile'))

    # Validate password is not empty
    if not password:
        flash('Password is required', 'error')
        return redirect(url_for('edit_profile'))

    db = get_db()
    cur = db.cursor()
    
    try:
        # Get user info
        cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
        user = cur.fetchone()
        
        if not user:
            cur.close()
            db.close()
            session.clear()
            flash('User not found', 'error')
            return redirect(url_for('login'))

        # Verify password
        if not check_password_hash(user['password'], password):
            cur.close()
            db.close()
            flash('Password is incorrect', 'error')
            return redirect(url_for('edit_profile'))

        # ===== Delete related data in correct order (child to parent) =====
        
        # 1. Delete notifications
        cur.execute('DELETE FROM notifications WHERE user_id = %s', (user_id,))
        
        # 2. Delete cart items
        cur.execute('DELETE FROM cart_items WHERE user_id = %s', (user_id,))
        
        # 3. Delete messages
        cur.execute('DELETE FROM messages WHERE sender_id = %s OR receiver_id = %s', (user_id, user_id))
        
        # 4. Delete reviews
        cur.execute('DELETE FROM reviews WHERE reviewer_id = %s OR reviewee_id = %s', (user_id, user_id))
        
        # 5. Delete reports
        cur.execute('DELETE FROM reports WHERE reporter_id = %s OR reported_user_id = %s', (user_id, user_id))
        
        # 6. Get all product IDs
        cur.execute('SELECT id FROM products WHERE seller_id = %s', (user_id,))
        product_ids = [row['id'] for row in cur.fetchall()]
        
        # 7. Delete product-related notifications
        if product_ids:
            placeholders = ','.join(['%s'] * len(product_ids))
            cur.execute(f'DELETE FROM notifications WHERE product_id IN ({placeholders})', product_ids)
        
        # 8. Delete offers (using product IDs)
        if product_ids:
            cur.execute(f'DELETE FROM offers WHERE product_id IN ({placeholders})', product_ids)
        cur.execute('DELETE FROM offers WHERE buyer_id = %s', (user_id,))
        
        # 9. Delete orders
        cur.execute('DELETE FROM orders WHERE buyer_id = %s OR seller_id = %s', (user_id, user_id))
        
        # 10. Delete products
        cur.execute('DELETE FROM products WHERE seller_id = %s', (user_id,))
        
        # 11. Finally delete user
        cur.execute('DELETE FROM users WHERE id = %s', (user_id,))
        
        db.commit()
        
    except Exception as e:
        db.rollback()
        cur.close()
        db.close()
        print(f"Delete account error: {e}")
        import traceback
        traceback.print_exc()
        flash('Something went wrong while deleting your account. Please try again or contact support.', 'error')
        return redirect(url_for('edit_profile'))

    cur.close()
    db.close()

    # Clear session and cookies
    session.clear()
    response = redirect(url_for('login'))
    response.set_cookie('remember_token', '', expires=0)
    response.set_cookie('admin_remember_token', '', expires=0)
    
    flash('Your account has been permanently deleted', 'info')
    return response

# ============================================================
# API - VERIFY PASSWORD - Check if password is correct
# ============================================================
@app.route('/verify-password', methods=['POST'])
def verify_password():
    """Verify user's password for sensitive operations"""
    
    # Check if user is logged in
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
# FORGOT PASSWORD - Password recovery via security questions
# ============================================================
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Password recovery using security questions"""
    
    if request.method == 'POST':
        step = request.form.get('step')

        # Step 1: Enter email
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

            # Store email and security questions in session
            session['fp_email'] = email
            session['fp_q1'] = user['security_q1']
            session['fp_q2'] = user['security_q2']
            return render_template(
                'forgot_password.html',
                step=2,
                q1=user['security_q1'],
                q2=user['security_q2']
            )

        # Step 2: Answer security questions
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

            # Verify answers
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

        # Step 3: Reset password
        elif step == '3':
            if not session.get('fp_verified'):
                flash('Please complete identity verification first.', 'error')
                return render_template('forgot_password.html')

            email = session.get('fp_email')
            new_password = request.form.get('fp_pw', '')
            confirm_password = request.form.get('fp_cpw', '')

            # Validate new password
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

            # Update password
            hashed = generate_password_hash(new_password)
            db = get_db()
            cur = db.cursor()
            cur.execute('UPDATE users SET password = %s WHERE email = %s', (hashed, email))
            db.commit()
            cur.close()
            db.close()

            # Clear session data
            session.pop('fp_email', None)
            session.pop('fp_q1', None)
            session.pop('fp_q2', None)
            session.pop('fp_verified', None)

            flash('Password reset successfully!', 'success')
            return redirect(url_for('login'))

    return render_template('forgot_password.html')

# ============================================================
# ADMIN LOGIN - Separate login for admin users
# ============================================================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page - separate from regular user login"""
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip() 
        password = request.form.get('password')
        remember_me = request.form.get('remember_me') 
    
        # Validate email domain
        if not email.endswith('@student.mmu.edu.my'):
            flash('Only @student.mmu.edu.my email addresses are allowed', 'error')
            return render_template('admin_login.html')
    
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s AND is_admin = 1', (email,))
        user = cur.fetchone()
        cur.close()
        db.close()

        # Verify admin credentials
        if user and check_password_hash(user['password'], password):
            # Clear any regular user session data
            session.pop('user_id', None)
            session.pop('username', None)
            session.pop('student_id', None)
            
            # Set admin session
            session['admin_logged_in'] = True
            session['admin_email'] = user['email']
            session['admin_username'] = user['username']
            session['admin_user_id'] = user['id']
            
            # Handle "Remember Me" for admin
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

# ============================================================
# BEFORE REQUEST - Auto-login admin via remember token
# ============================================================
@app.before_request
def check_admin_remember_me():
    """Auto-login admin user if valid remember token exists"""
    
    # Skip if already in admin session
    if session.get('admin_logged_in'):
        return
    
    # Skip public routes
    public_routes = [
        'login', 'admin_login', 'register', 'forgot_password', 'static', 'welcome']
    if request.endpoint in public_routes:
        return
    
    # Check for admin remember token
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

# ============================================================
# LOGOUT - Clear session and cookies
# ============================================================
@app.route('/logout')
def logout():
    """Log out user and clear session data"""
    
    # Handle admin logout
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
    
    # Handle regular user logout
    if session.get('user_id'):
        db = get_db()
        cur = db.cursor()
        cur.execute('UPDATE users SET remember_token = NULL WHERE id = %s', (session['user_id'],))
        db.commit()
        cur.close()
        db.close()
        session.clear()
        flash('Logged out', 'info')
        response = redirect(url_for('login'))
        response.set_cookie('remember_token', '', expires=0)
        return response

    # Clear session if no user
    session.clear()
    return redirect(url_for('login'))

# ============================================================
# ?'s Routes
# ============================================================
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
    
    # 获取所有用户
    cur.execute("SELECT * FROM users ORDER BY id")
    users = cur.fetchall()
    
    # 获取待处理的举报（添加错误处理）
    try:
        cur.execute('''
            SELECT r.*, u.username as reported_username,
                   rp.username as reporter_username
            FROM reports r
            LEFT JOIN users u ON r.reported_user_id = u.id
            LEFT JOIN users rp ON r.reporter_id = rp.id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
        ''')
        reports = cur.fetchall()
    except Exception as e:
        print(f"Error loading reports: {e}")
        reports = []
    
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
    
    # 1. 待审核 (pending)
    cur.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p 
        JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'pending' 
        ORDER BY p.created_at DESC
    ''')
    pending = cur.fetchall()
    
    # 2. 已通过 (approved)
    cur.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p 
        JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'approved' 
        ORDER BY p.created_at DESC
    ''')
    approved = cur.fetchall()
    
    # 3. 已拒绝 (rejected)
    cur.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p 
        JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'rejected' 
        ORDER BY p.created_at DESC
    ''')
    rejected = cur.fetchall()
    
    # 4. 已售出 (sold)
    cur.execute('''
        SELECT p.*, u.username as seller_name,
               o.buyer_id, o.order_number, o.created_at as sold_at,
               buyer.username as buyer_name, buyer.full_name as buyer_full_name
        FROM products p 
        JOIN users u ON p.seller_id = u.id
        LEFT JOIN orders o ON o.product_id = p.id AND o.status = 'completed'
        LEFT JOIN users buyer ON o.buyer_id = buyer.id
        WHERE p.status = 'sold' 
        ORDER BY o.created_at DESC NULLS LAST, p.created_at DESC
    ''')
    sold = cur.fetchall()
    
    # 5. 已预留 (reserved)
    cur.execute('''
        SELECT p.*, u.username as seller_name,
               o.buyer_id, o.order_number, o.created_at as reserved_at,
               buyer.username as buyer_name, buyer.full_name as buyer_full_name
        FROM products p 
        JOIN users u ON p.seller_id = u.id
        LEFT JOIN orders o ON o.product_id = p.id AND o.status IN ('pending', 'confirmed', 'delivered')
        LEFT JOIN users buyer ON o.buyer_id = buyer.id
        WHERE p.status = 'reserved' 
        ORDER BY o.created_at DESC NULLS LAST, p.created_at DESC
    ''')
    reserved = cur.fetchall()
    
    # 被举报的产品 (reported)
    cur.execute('''
        SELECT DISTINCT p.*, u.username as seller_name,
               COUNT(r.id) as report_count,
               STRING_AGG(DISTINCT r.reason, ', ') as report_reasons,
               STRING_AGG(DISTINCT CONCAT(rp.username, ' (', r.reason, ')'), ', ') as report_details
        FROM products p
        JOIN users u ON p.seller_id = u.id
        JOIN reports r ON r.product_id = p.id
        JOIN users rp ON r.reporter_id = rp.id
        WHERE r.status = 'pending' AND p.status IN ('approved', 'reserved')
        GROUP BY p.id, u.username
        ORDER BY report_count DESC, p.created_at DESC
    ''')
    reported = cur.fetchall()
    
    pending = [dict(row) for row in pending]
    approved = [dict(row) for row in approved]
    rejected = [dict(row) for row in rejected]
    sold = [dict(row) for row in sold]
    reserved = [dict(row) for row in reserved]
    reported = [dict(row) for row in reported]

    cur.close()
    db.close()

    return render_template("admin_product.html",
                           pending_list=pending,
                           approved_list=approved,
                           rejected_list=rejected,
                           sold_list=sold,
                           reserved_list=reserved,
                           reported_list=reported)

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
        SET status = 'approved', 
            reject_reason = ''
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
    # 直接重定向到 /admin/products 页面
    return redirect('/admin/products')

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

@app.route('/api/product/<int:product_id>/reports')
def api_product_reports(product_id):
    """获取产品的所有举报"""
    if not session.get('admin_logged_in'):
        return jsonify([]), 403
    
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        SELECT r.*, u.username as reporter_name
        FROM reports r
        JOIN users u ON r.reporter_id = u.id
        WHERE r.product_id = %s
        ORDER BY r.created_at DESC
    ''', (product_id,))
    reports = cur.fetchall()
    cur.close()
    db.close()
    
    return jsonify([dict(r) for r in reports])


@app.route('/admin/product/report/<int:report_id>/<action>', methods=['POST'])
def handle_product_report(report_id, action):
    """处理产品举报：下架或驳回"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT r.*, p.id as product_id, p.name as product_name, p.seller_id,
               u.username as seller_name
        FROM reports r
        JOIN products p ON r.product_id = p.id
        JOIN users u ON p.seller_id = u.id
        WHERE r.id = %s
    ''', (report_id,))
    report = cur.fetchone()
    
    if not report:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Report not found'}), 404
    
    if action == 'reject':
        # 驳回举报
        cur.execute("UPDATE reports SET status = 'dismissed' WHERE id = %s", (report_id,))
        
        create_notification(
            user_id=report['reporter_id'],
            message=f'📋 Your report on "{report["product_name"]}" has been reviewed and DISMISSED. No action was taken.',
            notif_type='report_dismissed',
            product_id=report['product_id']
        )
        
        db.commit()
        cur.close()
        db.close()
        return jsonify({'success': True, 'message': 'Report dismissed'})
        
    elif action == 'remove':
        # 下架产品
        cur.execute("UPDATE products SET status = 'rejected', reject_reason = %s WHERE id = %s", 
                    ('Reported and removed by admin', report['product_id']))
        cur.execute("UPDATE reports SET status = 'resolved' WHERE id = %s", (report_id,))
        
        create_notification(
            user_id=report['seller_id'],
            message=f'🚫 Your product "{report["product_name"]}" has been REMOVED due to user reports. Please contact admin if you believe this is a mistake.',
            notif_type='product_rejected',
            product_id=report['product_id']
        )
        
        create_notification(
            user_id=report['reporter_id'],
            message=f'✅ Your report on "{report["product_name"]}" has been verified. The product has been REMOVED. Thank you!',
            notif_type='report_resolved',
            product_id=report['product_id']
        )
        
        db.commit()
        cur.close()
        db.close()
        return jsonify({'success': True, 'message': 'Product removed'})
    
    cur.close()
    db.close()
    return jsonify({'success': False, 'error': 'Invalid action'}), 400

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

@app.route('/api/user/<int:user_id>')
def api_get_user_info(user_id):
    """获取用户基本信息（用于显示审批人）"""
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT id, username, full_name FROM users WHERE id = %s', (user_id,))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    if user:
        return jsonify(dict(user))
    return jsonify({'error': 'User not found'}), 404

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
    # 修改：统一使用 UTC 时间存储，不要用 AT TIME ZONE
    cur.execute('''
        INSERT INTO messages (sender_id, receiver_id, product_id, content, created_at)
        VALUES (%s, %s, %s, %s, NOW() AT TIME ZONE 'UTC')
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
    # 修改：统一使用 UTC 时间
    cur.execute('''
        INSERT INTO messages (sender_id, receiver_id, content, image, created_at)
        VALUES (%s, %s, %s, %s, NOW() AT TIME ZONE 'UTC')
    ''', (session['user_id'], int(receiver_id), content, ','.join(filenames)))
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
    
    # 修改：不要在后端做时区转换，直接输出原始 ISO 格式
    for msg in messages:
        if msg['created_at']:
            # 确保输出 ISO 格式带时区信息
            if isinstance(msg['created_at'], datetime):
                msg['created_at'] = msg['created_at'].isoformat()
            elif isinstance(msg['created_at'], str):
                # 已经是字符串，保持原样但确保格式统一
                pass

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

    result = []
    for msg in messages:
        msg_dict = dict(msg)
        if msg_dict['created_at']:
            # 直接输出 ISO 格式，不做时区转换
            if isinstance(msg_dict['created_at'], datetime):
                msg_dict['created_at'] = msg_dict['created_at'].isoformat()
            elif isinstance(msg_dict['created_at'], str):
                # 如果已经是字符串，确保是标准格式
                pass
        result.append(msg_dict)

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

    # 获取聊天列表
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

    # 获取未读通知数量
    cur.execute("SELECT COUNT(*) AS count FROM notifications WHERE user_id = %s AND is_read = 0", (user_id,))
    unread_notifications = cur.fetchone()['count']
    unread_reviews = 0
    
    # ========== 修复：正确计算未读公告数量 ==========
    # 获取用户上次阅读公告的时间
    cur.execute("SELECT last_read_ann FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    last_read = user['last_read_ann'] if user and user['last_read_ann'] else None
    
    # 统计未读公告数量
    if last_read:
        cur.execute("SELECT COUNT(*) AS count FROM announcements WHERE created_at > %s", (last_read,))
    else:
        cur.execute("SELECT COUNT(*) AS count FROM announcements")
    unread_announcements = cur.fetchone()['count']
    
    cur.close()
    db.close()

    return render_template('user_chatlist.html', 
                           chats=chat_list_data,
                           unread_notifications=unread_notifications,
                           unread_reviews=unread_reviews,
                           unread_announcements=unread_announcements)

@app.route('/api/user/<int:user_id>/status')
def get_user_status(user_id):
    db = get_db()
    cur = db.cursor()
    
    cur.execute('''
        SELECT last_seen, 
               CASE WHEN last_seen > NOW() - INTERVAL '5 minutes' THEN true ELSE false END as is_online
        FROM users WHERE id = %s
    ''', (user_id,))
    user = cur.fetchone()
    cur.close()
    db.close()
    
    if user:
        # 确保输出 ISO 格式
        last_seen_str = user['last_seen'].isoformat() if user['last_seen'] else None
        return jsonify({
            'online': user['is_online'] if user['is_online'] else False,
            'last_seen': last_seen_str
        })
    return jsonify({'online': False, 'last_seen': None})

# ============================================================
# EILEEN'S ROUTES - Order Management (Meeting Updates & Shipping)
# ============================================================

# ============================================================
# API - UPDATE ORDER MEETING - Seller updates meetup location/time
# ============================================================
@app.route('/api/order/<int:order_id>/update-meeting', methods=['POST'])
def update_order_meeting(order_id): 

    # STEP 1: Authentication - Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # STEP 2: Get and validate request data
    data = request.get_json()
    meeting_point = data.get('meeting_point')
    meeting_time = data.get('meeting_time')

    if not meeting_point or not meeting_time:
        return jsonify({'success': False, 'error': 'Meeting point and time required'}), 400

    # STEP 3: Authorization - Verify user is the seller
    db = get_db()
    cur = db.cursor()

    cur.execute('SELECT seller_id, buyer_id, order_number FROM orders WHERE id = %s', (order_id,))
    order = cur.fetchone()
    
    if not order or order['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    # STEP 4: Update meeting details in database
    cur.execute('''
        UPDATE orders SET meeting_point = %s, meeting_time = %s, updated_at = NOW()
        WHERE id = %s
    ''', (meeting_point, meeting_time, order_id))

    # STEP 5: Notify buyer about the meeting update
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'order', %s, 0)
    ''', (order['buyer_id'],
          f" The seller has updated the meetup info for Order #{order['order_number']}. New meeting: {meeting_point} at {meeting_time}",
          order_id))

    # STEP 6: Commit changes and return success
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})


# ============================================================
# API - SHIP ORDER - Seller marks order as shipped/delivered
# ============================================================
@app.route('/api/order/<int:order_id>/ship', methods=['POST'])
def ship_order(order_id):

    
    # STEP 1: Authentication - Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # STEP 2: Authorization - Verify user is the seller
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT seller_id, buyer_id, order_number FROM orders WHERE id = %s', (order_id,))
    order = cur.fetchone()
    
    if not order or order['seller_id'] != session['user_id']:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    # STEP 3: Update order status to 'delivered'
    cur.execute('UPDATE orders SET status = %s, updated_at = NOW() WHERE id = %s', ('delivered', order_id))

    # STEP 4: Notify buyer that the order has been delivered
    cur.execute('''
        INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
        VALUES (%s, %s, NOW(), 'order', %s, 0)
    ''', (order['buyer_id'],
          f"✅ Order #{order['order_number']} has been marked as DELIVERED. Please confirm receipt to complete the order.",
          order_id))

    # STEP 5: Commit changes and return success
    db.commit()
    cur.close()
    db.close()

    return jsonify({'success': True})

# ============================================================
#                       Xingru's route
#                        Search Users
# ============================================================
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

# ============================================================
# ?'s Routes
# ============================================================
@app.route('/api/announcements')
def api_announcements():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, title, content, created_at FROM announcements ORDER BY created_at DESC")
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

@app.route('/api/unread-announcements')
def unread_announcements():
    if 'user_id' not in session:
        return jsonify({'count': 0})
    
    db = get_db()
    cur = db.cursor()
    
    # 获取用户上次阅读公告的时间
    cur.execute("SELECT last_read_ann FROM users WHERE id = %s", (session['user_id'],))
    user = cur.fetchone()
    last_read = user['last_read_ann'] if user and user['last_read_ann'] else None
    
    # 统计未读公告数量
    if last_read:
        cur.execute("SELECT COUNT(*) as count FROM announcements WHERE created_at > %s", (last_read,))
    else:
        cur.execute("SELECT COUNT(*) as count FROM announcements")
    
    count = cur.fetchone()['count']
    cur.close()
    db.close()
    
    return jsonify({'count': count})

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

# ========== 添加这个删除公告的路由 ==========
@app.route('/admin/announcement/delete/<int:ann_id>', methods=['POST'])
def delete_announcement(ann_id):
    """删除公告"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        db = get_db()
        cur = db.cursor()
        
        # 删除公告
        cur.execute("DELETE FROM announcements WHERE id = %s", (ann_id,))
        db.commit()
        
        cur.close()
        db.close()
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"Delete announcement error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
#                       Xingru's route
#                       Upload Product
# ============================================================
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
    
    # 获取产品信息（包括卖家ID）
    cur.execute('SELECT id, name, seller_id FROM products WHERE id = %s', (product_id,))
    product = cur.fetchone()
    
    if not product:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    
    # 检查是否已经举报过
    cur.execute('''
        SELECT id FROM reports 
        WHERE reporter_id = %s AND product_id = %s AND status = 'pending'
    ''', (session['user_id'], product_id))
    existing = cur.fetchone()
    
    if existing:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'You have already reported this product'}), 400
    
    # ✅ 插入举报记录，reported_user_id 使用卖家的 ID
    cur.execute('''
        INSERT INTO reports (reporter_id, reported_user_id, product_id, reason, details)
        VALUES (%s, %s, %s, %s, %s)
    ''', (session['user_id'], product['seller_id'], product_id, reason, details))
    db.commit()
    
    # 通知举报者
    create_notification(
        user_id=session['user_id'],
        message=f'📋 You reported product "{product["name"]}" for: {reason}. Admin will review within 1-3 business days.',
        notif_type='report_submitted',
        product_id=product_id
    )
    
    # 通知卖家
    create_notification(
        user_id=product['seller_id'],
        message=f'⚠️ Your product "{product["name"]}" received a report: {reason}. Please ensure your listing follows guidelines.',
        notif_type='report_warning',
        product_id=product_id
    )
    
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'message': 'Report submitted'})

# ============================================================
# EILEEN'S ROUTES - Orders & Reviews Management
# ============================================================

# ============================================================
# API - GET MY ORDERS - Get all orders as buyer and seller
# ============================================================
@app.route('/api/orders/my', methods=['GET'])
def api_get_my_orders():
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'as_buyer': [], 'as_seller': []}), 401

    db = get_db()
    cur = db.cursor()
    
    # Get orders where user is the buyer
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
    
    # Get orders where user is the seller
    # Includes: product name, buyer info, product images
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
    
    # Process buyer orders - extract first image from blob
    result_buyer = []
    for o in buyer_orders:
        o_dict = dict(o)
        # Extract the first image from images_blob array
        if o_dict.get('images_blob'):
            try:
                imgs = json.loads(o_dict['images_blob'])
                o_dict['product_image'] = imgs[0] if imgs else None
            except:
                o_dict['product_image'] = None
        result_buyer.append(o_dict)
    
    # Process seller orders - extract first image from blob
    result_seller = []
    for o in seller_orders:
        o_dict = dict(o)
        # Extract the first image from images_blob array
        if o_dict.get('images_blob'):
            try:
                imgs = json.loads(o_dict['images_blob'])
                o_dict['product_image'] = imgs[0] if imgs else None
            except:
                o_dict['product_image'] = None
        result_seller.append(o_dict)
    
    #Return both order lists
    return jsonify({'as_buyer': result_buyer, 'as_seller': result_seller})

# ============================================================
# API - UPDATE ORDER STATUS - Change order status with validation
# ============================================================
@app.route('/api/order/<int:order_id>/status', methods=['PUT'])
def api_update_order_status(order_id):
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    # Get and validate new status
    data = request.get_json()
    new_status = data.get('status')
    
    valid_statuses = ['pending', 'confirmed', 'delivered', 'completed', 'cancelled']
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400
    
    db = get_db()
    cur = db.cursor()
    
    # Get order details with product info
    cur.execute('''
        SELECT o.*, p.name as product_name, p.seller_id, p.id as product_id
        FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s
    ''', (order_id,))
    order = cur.fetchone()
    
    if not order:
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Order not found'}), 404
    
    # Check if user is seller or buyer
    is_seller = (order['seller_id'] == session['user_id'])
    is_buyer = (order['buyer_id'] == session['user_id'])
    
    if not (is_seller or is_buyer):
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    # STEP 1: Validate status transitions and permissions
    # Confirm: only seller can confirm pending orders
    if new_status == 'confirmed':
        if order['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Can only confirm pending orders'}), 400
        if not is_seller:
            return jsonify({'success': False, 'error': 'Only seller can confirm order'}), 403
            
    # Deliver: only seller can mark as delivered after confirmed
    elif new_status == 'delivered':
        if order['status'] != 'confirmed':
            return jsonify({'success': False, 'error': 'Can only mark as delivered after confirmed'}), 400
        if not is_seller:
            return jsonify({'success': False, 'error': 'Only seller can mark as delivered'}), 403
            
    # Complete: only buyer can complete after delivered
    elif new_status == 'completed':
        if order['status'] != 'delivered':
            return jsonify({'success': False, 'error': 'Can only complete after delivered'}), 400
        if not is_buyer:
            return jsonify({'success': False, 'error': 'Only buyer can confirm receipt'}), 403
            
    # Cancel: only pending or confirmed orders can be cancelled
    elif new_status == 'cancelled':
        if order['status'] not in ['pending', 'confirmed']:
            return jsonify({'success': False, 'error': 'Cannot cancel order at this stage'}), 400
        
        # Restore product to approved status
        cur.execute("UPDATE products SET status = 'approved' WHERE id = %s", (order['product_id'],))
        
        # Remove from cart
        cur.execute("DELETE FROM cart_items WHERE product_id = %s", (order['product_id'],))
        
        # Notify seller product is available again
        create_notification(
            user_id=order['seller_id'],
            message=f'🔄 Order #{order["order_number"]} was cancelled. Your product "{order["product_name"]}" is now available again.',
            notif_type='order_cancelled',
            related_id=order_id,
            product_id=order['product_id']
        )
    else:
        return jsonify({'success': False, 'error': 'Invalid status transition'}), 400
    
    # STEP 2: Execute the status update
    cur.execute('UPDATE orders SET status = %s, updated_at = NOW() WHERE id = %s', (new_status, order_id))
    
    # STEP 3: Send notification to the other party
    notify_user_id = order['buyer_id'] if is_seller else order['seller_id']
    
    messages = {
        'confirmed': f"✅ Order #{order['order_number']} has been CONFIRMED by seller!",
        'delivered': f"🚚 Order #{order['order_number']} has been MARKED AS DELIVERED! Please confirm receipt.",
        'completed': f"🎉 Order #{order['order_number']} is COMPLETED! Thank you!",
        'cancelled': f"❌ Order #{order['order_number']} has been CANCELLED."
    }
    
    if new_status in messages:
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, is_read)
            VALUES (%s, %s, NOW(), 'order', %s, 0)
        ''', (notify_user_id, messages[new_status], order_id))
    
    # STEP 4: Special handling for completed orders
    if new_status == 'completed':
        # Mark product as sold
        cur.execute('UPDATE products SET status = %s WHERE id = %s', ('sold', order['product_id']))
        
        # Notify seller product is sold
        create_notification(
            user_id=order['seller_id'],
            message=f'💰 Your product "{order["product_name"]}" has been SOLD! Order #{order["order_number"]} is completed.',
            notif_type='product_sold',
            related_id=order_id,
            product_id=order['product_id']
        )
        
        # Remind buyer to leave a review
        create_notification(
            user_id=order['buyer_id'],
            message=f'⭐ Order #{order["order_number"]} is completed! Please leave a review for the seller.',
            notif_type='review_reminder',
            related_id=order_id,
            product_id=order['product_id']
        )
    
    db.commit()
    cur.close()
    db.close()
    
    return jsonify({'success': True, 'message': f'Order status updated to {new_status}'})

# ============================================================
# API - SUBMIT ORDER REVIEW - Buyer reviews seller after completed order
# ============================================================
@app.route('/api/order/<int:order_id>/review', methods=['POST'])
def api_submit_order_review(order_id):
    """
    Submit a review for an order after it's completed
    Only the buyer can review, only once per order
    Ratings: service, shipping, quality (1-5 stars)
    Overall rating is automatically calculated as average of three
    
    Args:
        order_id: The completed order ID to review
    
    Request Body:
        rating_service (int): 1-5
        rating_shipping (int): 1-5
        rating_quality (int): 1-5
        comment (str): Optional comment
    
    Returns:
        JSON: {success: True/False, overall_rating: float, error: if failed}
    """
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # Get and validate review data
    data = request.get_json()
    rating_service = data.get('rating_service', 0)
    rating_shipping = data.get('rating_shipping', 0)
    rating_quality = data.get('rating_quality', 0)
    comment = data.get('comment', '').strip()

    # Validate each rating is between 1-5
    for r, name in [(rating_service, 'service'), (rating_shipping, 'shipping'), (rating_quality, 'quality')]:
        if r < 1 or r > 5:
            return jsonify({'success': False, 'error': f'{name} rating must be 1-5'}), 400
    
    # Calculate overall rating (average of three, rounded to 1 decimal)
    rating_overall = round((rating_service + rating_shipping + rating_quality) / 3, 1)
    
    #Verify order exists and user is the buyer
    db = get_db()
    cur = db.cursor()

    # Order must belong to user as buyer and be in 'completed' status
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

    #  Check if already reviewed (prevent duplicate reviews)
    cur.execute('SELECT id FROM reviews WHERE order_id = %s', (order_id,))
    if cur.fetchone():
        cur.close()
        db.close()
        return jsonify({'success': False, 'error': 'Already reviewed'}), 400
    
    # Insert the review into database
    cur.execute('''
        INSERT INTO reviews (product_id, reviewer_id, reviewee_id, order_id,
                           rating_service, rating_shipping, rating_quality, rating_overall, comment, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) RETURNING id
    ''', (order['product_id'], session['user_id'], order['seller_id'], order_id,
          rating_service, rating_shipping, rating_quality, rating_overall, comment))
    
    review_id = cur.fetchone()['id']

    # Update seller's average ratings
    # Calculate new averages from all reviews for this seller
    cur.execute('''
        SELECT AVG(rating_service) as avg_service, AVG(rating_shipping) as avg_shipping,
               AVG(rating_quality) as avg_quality, AVG(rating_overall) as avg_overall, COUNT(*) as total
        FROM reviews WHERE reviewee_id = %s
    ''', (order['seller_id'],))
    stats = cur.fetchone()
    
    # Update seller's user record with new rating statistics
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
    
    # Notify seller about review
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

# ============================================================
# API - GET USER REVIEWS - Get all reviews for a user
# ============================================================
@app.route('/api/user/<int:user_id>/reviews', methods=['GET'])
def api_get_user_reviews(user_id):

    db = get_db()
    cur = db.cursor()

    # Get all reviews for the user
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

    # Get average rating statistics
    cur.execute('''
        SELECT AVG(rating_service) as avg_service, AVG(rating_shipping) as avg_shipping,
               AVG(rating_quality) as avg_quality, AVG(rating_overall) as avg_overall, COUNT(*) as total
        FROM reviews WHERE reviewee_id = %s
    ''', (user_id,))
    stats = cur.fetchone()

    cur.close()
    db.close()

    # Process reviews - convert avatar blob to base64 for display
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

# ============================================================
# API - CAN REVIEW USER - Check if user can review a seller
# ============================================================
@app.route('/api/user/<int:user_id>/can-review', methods=['GET'])
def api_can_review_user(user_id):

    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({'can_review': False, 'error': 'Not logged in'}), 401
    
    db = get_db()
    cur = db.cursor()

    # Check for completed order without review
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

# ============================================================
# ?'s Routes
# ============================================================
@app.route('/meetup-locations')
def meetup_locations():
    return render_template('meetup.html')

# ============================================================
#                       Xingru's route
#                     Other User Profile
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

# ============================================================
# 启动应用
# ============================================================

# 启动时检查并解冻过期账户
def check_and_unfreeze_expired():
    """启动时检查并解冻所有过期账户"""
    try:
        db = get_db()
        cur = db.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        cur.execute("""
            SELECT id FROM users
            WHERE is_frozen = 1 AND frozen_until IS NOT NULL AND frozen_until < %s
        """, (now,))
        expired = cur.fetchall()
        
        for user in expired:
            cur.execute("""
                UPDATE users 
                SET is_frozen = 0, frozen_until = NULL, freeze_reason = NULL 
                WHERE id = %s
            """, (user['id'],))
            
            create_notification(
                user_id=user['id'],
                message='✅ Your 7-day freeze has ended. Your account is now ACTIVE.',
                notif_type='system'
            )
        
        db.commit()
        cur.close()
        db.close()
        if len(expired) > 0:
            print(f"Unfrozen {len(expired)} expired accounts")
    except Exception as e:
        print(f"Unfreeze check error: {e}")

# 在后台线程中执行解冻检查，避免阻塞启动
import threading
def run_unfreeze_check():
    try:
        check_and_unfreeze_expired()
    except Exception as e:
        print(f"Unfreeze check failed: {e}")

unfreeze_thread = threading.Thread(target=run_unfreeze_check)
unfreeze_thread.daemon = True
unfreeze_thread.start()

# ============================================================
# 交易提醒功能 - 定时检查即将到来的交易
# ============================================================

import time as time_module

# 存储已发送的提醒，防止重复发送
_reminder_sent_cache = {}

def send_meeting_reminder(order_id, user_id, message, reminder_type):
    """发送交易提醒通知"""
    try:
        db = get_db()
        cur = db.cursor()
        
        # 获取订单和产品信息
        cur.execute('''
            SELECT o.*, p.name as product_name, p.images_blob, p.id as product_id
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.id = %s
        ''', (order_id,))
        order = cur.fetchone()
        
        if not order:
            cur.close()
            db.close()
            return
        
        # 获取产品图片
        product_image = None
        if order.get('images_blob'):
            try:
                images = json.loads(order['images_blob']) if isinstance(order['images_blob'], str) else order['images_blob']
                if images and len(images) > 0:
                    product_image = images[0]
            except:
                pass
        
        # 构建通知消息，包含时间、地点和产品信息
        meeting_time = order.get('meeting_time', '')
        meeting_point = order.get('meeting_point', '')
        product_name = order.get('product_name', 'Item')
        order_number = order.get('order_number', '')
        
        # 格式化时间
        try:
            if meeting_time and 'T' in meeting_time:
                dt = datetime.fromisoformat(meeting_time.replace('Z', '+00:00'))
                formatted_time = dt.strftime('%Y-%m-%d %H:%M')
            else:
                formatted_time = meeting_time
        except:
            formatted_time = meeting_time
        
        # 不同时间点的提醒消息
        reminder_messages = {
            '1hour': f"⏰ [1 HOUR REMINDER] Your meetup for Order #{order_number} is in 1 hour!\n📍 Location: {meeting_point}\n⏱️ Time: {formatted_time}\n📦 Product: {product_name}",
            '30min': f"⏰ [30 MIN REMINDER] Your meetup for Order #{order_number} is in 30 minutes!\n📍 Location: {meeting_point}\n⏱️ Time: {formatted_time}\n📦 Product: {product_name}",
            '15min': f"⏰ [15 MIN REMINDER] Your meetup for Order #{order_number} is in 15 minutes!\n📍 Location: {meeting_point}\n⏱️ Time: {formatted_time}\n📦 Product: {product_name}"
        }
        
        notif_message = reminder_messages.get(reminder_type, message)
        
        # 发送通知给用户
        cur.execute('''
            INSERT INTO notifications (user_id, message, created_at, type, related_id, product_id, is_read)
            VALUES (%s, %s, NOW(), 'meeting_reminder', %s, %s, 0)
        ''', (user_id, notif_message, order_id, order.get('product_id')))
        
        db.commit()
        cur.close()
        db.close()
        
        print(f"✅ Reminder sent to user {user_id} for order {order_id} ({reminder_type})")
    except Exception as e:
        print(f"❌ Failed to send reminder: {e}")

def check_upcoming_meetings_reminder():
    """检查即将到来的交易并发送提醒"""
    try:
        db = get_db()
        cur = db.cursor()
        
        # 获取所有已确认或已交付的订单（有 meeting_time）
        cur.execute('''
            SELECT o.id, o.order_number, o.meeting_point, o.meeting_time, 
                   o.buyer_id, o.seller_id, o.product_id,
                   p.name as product_name, p.images_blob
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.status IN ('confirmed', 'delivered')
              AND o.meeting_time IS NOT NULL
              AND o.meeting_time != ''
        ''')
        orders = cur.fetchall()
        cur.close()
        db.close()
        
        now = datetime.now()
        
        for order in orders:
            order_id = order['id']
            meeting_time_str = order['meeting_time']
            
            if not meeting_time_str:
                continue
            
            try:
                # 解析时间
                if isinstance(meeting_time_str, str):
                    if 'T' in meeting_time_str:
                        meeting_time = datetime.fromisoformat(meeting_time_str.replace('Z', '+00:00'))
                    else:
                        # 尝试多种格式
                        try:
                            meeting_time = datetime.strptime(meeting_time_str, '%Y-%m-%d %H:%M:%S')
                        except:
                            try:
                                meeting_time = datetime.strptime(meeting_time_str, '%Y-%m-%d %H:%M')
                            except:
                                meeting_time = datetime.strptime(meeting_time_str, '%Y-%m-%dT%H:%M')
                else:
                    meeting_time = meeting_time_str
                
                # 移除时区信息
                if hasattr(meeting_time, 'tzinfo') and meeting_time.tzinfo:
                    meeting_time = meeting_time.replace(tzinfo=None)
                
                # 计算时间差（秒）
                time_diff = (meeting_time - now).total_seconds()
                
                # 检查是否需要发送提醒（1小时、30分钟、15分钟）
                reminder_checks = [
                    ('1hour', 3600, 60),      # 1小时，允许60秒误差
                    ('30min', 1800, 30),       # 30分钟，允许30秒误差
                    ('15min', 900, 15)         # 15分钟，允许15秒误差
                ]
                
                for reminder_type, target_seconds, tolerance in reminder_checks:
                    if 0 <= time_diff - target_seconds <= tolerance:
                        # 检查是否已经发送过这个提醒
                        cache_key = f"{order_id}_{reminder_type}"
                        if cache_key in _reminder_sent_cache:
                            continue
                        
                        # 发送给买家
                        send_meeting_reminder(order_id, order['buyer_id'], '', reminder_type)
                        # 发送给卖家
                        send_meeting_reminder(order_id, order['seller_id'], '', reminder_type)
                        
                        # 记录已发送
                        _reminder_sent_cache[cache_key] = True
                        print(f"📨 Sent {reminder_type} reminder for order {order_id}")
                        
            except Exception as e:
                print(f"Error processing order {order_id}: {e}")
                continue
                
    except Exception as e:
        print(f"Error in check_upcoming_meetings_reminder: {e}")

def reminder_scheduler():
    """后台定时任务，每分钟执行一次"""
    while True:
        try:
            check_upcoming_meetings_reminder()
        except Exception as e:
            print(f"Reminder scheduler error: {e}")
        # 每分钟检查一次
        time_module.sleep(60)

# 启动后台提醒线程
reminder_thread = threading.Thread(target=reminder_scheduler, daemon=True)
reminder_thread.start()
print("✅ Meeting reminder scheduler started")

if __name__ == '__main__':
    app.run(debug=True)