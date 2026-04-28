import re

import subprocess

import os

import sqlite3

from datetime import datetime, timedelta

import uuid

import base64

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, make_response
)
from database import init_db, get_db, init_products


from werkzeug.security import generate_password_hash, check_password_hash


from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'e-bye-secret-key-2026-new'

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


@app.route('/')


def index():
    return redirect(url_for('login'))


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
        user = db.execute(
            'SELECT * FROM users WHERE LOWER(email) = LOWER(?)',
            (email,)
        ).fetchone()
        db.close()

        # Account+password check validation if correct then will pass to verify
        if user and check_password_hash(user['password'], password):
            # Permanently blocked check
            if user['is_blocked'] == 1:
                flash('❌ This account is permanently blocked.', 'danger')
                return redirect(url_for('login'))

            # Time-limited freeze check
            is_user_frozen = user['is_frozen']
            frozen_end_time = user['frozen_until']

            if is_user_frozen == 1 and frozen_end_time:
                now = datetime.now()
                expire_time = None
                try:
                    expire_time = datetime.strptime(
                        frozen_end_time, "%Y-%m-%d %H:%M:%S"
                    )
                except Exception:
                    pass

                if expire_time and now < expire_time:
                    time_diff = expire_time - now
                    remain_days = time_diff.days
                    remain_hours = time_diff.seconds // 3600

                    freeze_reason_text = (
                        user['freeze_reason']
                        if user['freeze_reason']
                        else 'No specific reason provided'
                    )
                    alert_msg = (
                        f'⚠️ ACCOUNT FROZEN\n'
                        f'Reason: {freeze_reason_text}\n'
                        f'Will unlock in: {remain_days} Day(s) '
                        f'{remain_hours} Hour(s)'
                    )
                    flash(alert_msg, 'warning')
                    return redirect(url_for('login'))
                else:
                    # Auto unfreeze expired account
                    db_auto = get_db()
                    db_auto.execute("""
                        UPDATE users
                        SET is_frozen = 0, frozen_until = NULL,
                            freeze_reason = NULL
                        WHERE id = ?
                    """, (user["id"],))
                    db_auto.commit()
                    db_auto.close()

            # Login successful
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['student_id'] = user['student_id']

            if remember_me:
                session.permanent = True
            else:
                session.permanent = False

            flash('Login successful!', 'success')
            return redirect(url_for('home'))

        # Account/password error fallback
        else:
            flash('Invalid email or password', 'error')

    return render_template('login.html')


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

        # Check existing student_id or email
        existing = db.execute(
            'SELECT * FROM users WHERE student_id = ? OR LOWER(email) = LOWER(?)',
            (student_id, email)
        ).fetchone()
        if existing:
            db.close()
            flash('Student ID or Email already registered', 'error')
            return render_template('register.html')

        # Check existing username
        username_exists = db.execute(
            'SELECT * FROM users WHERE LOWER(username) = LOWER(?)',
            (username,)
        ).fetchone()
        if username_exists:
            db.close()
            flash('Username already taken. Please choose another one.', 'error')
            return render_template('register.html')

        # Create user
        hashed_password = generate_password_hash(password)
        db.execute('''
            INSERT INTO users (
                student_id, email, username, password, gender,
                security_q1, security_a1, security_q2, security_a2
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (student_id, email, username, hashed_password, gender,
              q1, a1, q2, a2))
        db.commit()
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
    products_data = db.execute('''
        SELECT p.*, u.username as seller_name, u.full_name as seller_full_name, u.id as seller_id
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'approved'
        ORDER BY p.created_at DESC
    ''').fetchall()
    db.close()

    products = []
    for row in products_data:
        product = dict(row)
        images_str = product.get('images', '')
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
        products.append(product)

    return render_template('home.html',
                           username=session.get('username'), latest_products=products)

@app.route('/logout')

def logout():
    session.clear()
    flash('Logged out', 'info')
    return redirect(url_for('login'))

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
    user = db.execute('SELECT avatar_blob FROM users WHERE id = ?',
                      (session['user_id'],)).fetchone()
    db.close()

    if user and user['avatar_blob']:
        response = make_response(user['avatar_blob'])
        response.headers.set('Content-Type', 'image/jpeg')
        response.headers.set('Cache-Control', 'no-cache, no-store, must-revalidate')
        return response
    return '', 404


# Eileen's Route - Update avatar image
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
    db.execute('UPDATE users SET avatar_blob = ? WHERE id = ?',
               (image_data, session['user_id']))
    db.commit()
    db.close()

    return jsonify({'success': True})


# Added by Xingru - public route to serve avatar by user_id (for displaying other users' avatars)
@app.route('/user-avatar/<int:user_id>')

def user_avatar(user_id):
    db = get_db()
    user = db.execute('SELECT avatar_blob FROM users WHERE id = ?', (user_id,)).fetchone()
    db.close()
    if user and user['avatar_blob']:
        response = make_response(user['avatar_blob'])
        response.headers.set('Content-Type', 'image/jpeg')
        return response
    return '', 404


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
    user = db.execute('SELECT cover_blob FROM users WHERE id = ?',
                      (session['user_id'],)).fetchone()
    db.close()

    if user and user['cover_blob']:
        response = make_response(user['cover_blob'])
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
    db.execute('UPDATE users SET cover_blob = ? WHERE id = ?',
               (image_data, session['user_id']))
    db.commit()
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
    db.execute('''
        UPDATE users SET background_type = ?, background_value = ? WHERE id = ?
    ''', (bg_type, bg_value, session['user_id']))
    db.commit()
    db.close()

    return jsonify({'success': True})


# Eileen's Route - Upload custom background image
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
    db.execute('''
        UPDATE users SET background_type = ?, background_value = ? WHERE id = ?
    ''', ('image', bg_value, session['user_id']))
    db.commit()
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
    user = db.execute('''
        SELECT background_type, background_value
        FROM users WHERE id = ?
    ''', (session['user_id'],)).fetchone()
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
    return jsonify([])


# Eileen's Route - Api for listing
@app.route('/api/user/listings')

def api_user_listings():
    if 'user_id' not in session:
        return jsonify([])

    db = get_db()
    rows = db.execute("""
        SELECT id, name, price, status, created_at,
               CASE category
                   WHEN 'books' THEN '📚'
                   WHEN 'gadgets' THEN '💻'
                   WHEN 'dorm' THEN '🛏'
                   WHEN 'fashion' THEN '👕'
                   WHEN 'stationery' THEN '✏️'
                   WHEN 'sports' THEN '⚽'
                   ELSE '📦'
               END as emoji
        FROM products
        WHERE seller_id = ?
        ORDER BY created_at DESC
    """, (session['user_id'],)).fetchall()
    db.close()

    return jsonify([dict(row) for row in rows])


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
    product = db.execute('''
        SELECT id, name, price, description, condition, category, images, status
        FROM products
        WHERE id = ? AND seller_id = ?
    ''', (product_id, session['user_id'])).fetchone()
    db.close()

    if not product:
        return jsonify({'error': 'Product not found'}), 404

    return jsonify(dict(product))


# Eileen's Route - Update product
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

    # Verify product belongs to user
    product = db.execute('SELECT id FROM products WHERE id = ? AND seller_id = ?',
                         (product_id, session['user_id'])).fetchone()
    if not product:
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404

    # Update product (status becomes pending again for admin review)
    db.execute('''
        UPDATE products
        SET name = ?, price = ?, description = ?, condition = ?, category = ?, status = 'pending'
        WHERE id = ?
    ''', (name, price, description, condition, category, product_id))
    db.commit()
    db.close()

    return jsonify({'success': True})


# Eileen's Route - Delete product
@app.route('/api/product/<int:product_id>/delete', methods=['DELETE'])

def api_delete_product(product_id):
    """Delete a product listing"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = get_db()

    # Verify product belongs to user
    product = db.execute('SELECT id, name, images FROM products WHERE id = ? AND seller_id = ?',
                         (product_id, session['user_id'])).fetchone()
    if not product:
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404

    # Delete associated images from filesystem
    if product['images']:
        for img in product['images'].split(','):
            img_path = os.path.join('static/uploads', img)
            if os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except:
                    pass

    # Delete product from database
    db.execute('DELETE FROM products WHERE id = ?', (product_id,))
    db.commit()
    db.close()

    return jsonify({'success': True})


# ============================================================
# Eileen's Route - User own profile
# ============================================================
@app.route('/my-profile')

def my_profile():
    """Display user's own profile page with listings and purchases"""
    if 'user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    if not user:
        session.clear()
        flash('User not found', 'error')
        return redirect(url_for('login'))

    # Get listing count
    listing_count = db.execute('SELECT COUNT(*) FROM products WHERE seller_id = ?',
                               (session['user_id'],)).fetchone()[0]

    # Get sold count (from orders table if exists)
    sold_count = 0
    try:
        sold_count = db.execute('SELECT COUNT(*) FROM orders WHERE seller_id = ? AND status = "completed"',
                               (session['user_id'],)).fetchone()[0]
    except:
        pass

    # Calculate trust score
    trust_score = 60
    if user['avatar_blob']:
        trust_score += 8
    if user['bio']:
        trust_score += 8
    if user['contact']:
        trust_score += 7
    if user['full_name']:
        trust_score += 7
    trust_score += min(25, (listing_count // 2) * 2)
    trust_score = min(100, max(30, trust_score))

    db.close()

    return render_template('my_profile.html',
                           user=user,
                           listing_count=listing_count,
                           sold_count=sold_count,
                           trust_score=trust_score)


# ============================================================
# Eileen's route - update product full
# ============================================================
@app.route('/api/product/<int:product_id>/update-full', methods=['POST'])

def api_update_product_full(product_id):
    """Update product with images"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = get_db()

    # Verify product belongs to user
    product = db.execute('SELECT id, images FROM products WHERE id = ? AND seller_id = ?',
                         (product_id, session['user_id'])).fetchone()
    if not product:
        db.close()
        return jsonify({'success': False, 'error': 'Product not found'}), 404

    # Get form data
    name = request.form.get('name', '').strip()
    price = request.form.get('price', 0)
    description = request.form.get('description', '').strip()
    condition = request.form.get('condition', '')
    category = request.form.get('category', '')

    # Validation
    if not name or not price or not description:
        return jsonify({'success': False, 'error': 'Name, price and description required'}), 400

    try:
        price = float(price)
    except:
        return jsonify({'success': False, 'error': 'Invalid price'}), 400

    # Handle image deletions
    current_images = product['images'].split(',') if product['images'] else []
    delete_images = request.form.get('delete_images', '[]')
    import json
    images_to_delete = json.loads(delete_images) if delete_images else []

    # Remove deleted images from filesystem
    for img_name in images_to_delete:
        if img_name in current_images:
            current_images.remove(img_name)
            img_path = os.path.join('static/uploads', img_name)
            if os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except:
                    pass

    # Handle new image uploads
    new_images = request.files.getlist('new_images')
    for img in new_images:
        if img and img.filename:
            ext = img.filename.rsplit('.', 1)[-1].lower() if '.' in img.filename else 'jpg'
            filename = f"product_{product_id}_{uuid.uuid4().hex}.{ext}"
            img.save(os.path.join('static/uploads', filename))
            current_images.append(filename)

    # Update database
    images_string = ','.join(current_images) if current_images else ''
    db.execute('''
        UPDATE products
        SET name = ?, price = ?, description = ?, condition = ?, category = ?,
            images = ?, status = 'pending'
        WHERE id = ?
    ''', (name, price, description, condition, category, images_string, product_id))
    db.commit()
    db.close()

    return jsonify({'success': True})


# ============================================================
# Eileen's Route - Edit Profile
# ============================================================
@app.route('/edit_profile', methods=['GET'])

def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    user = db.execute(
        'SELECT * FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()

    listing_count = db.execute(
        'SELECT COUNT(*) FROM products WHERE seller_id = ?',
        (session['user_id'],)
    ).fetchone()[0]

    # Calculate trust score
    trust_score = 60
    if user['avatar_blob']:
        trust_score += 8
    if user['bio']:
        trust_score += 8
    if user['contact']:
        trust_score += 7
    if user['full_name']:
        trust_score += 7

    if user['created_at']:
        try:
            created_date = datetime.strptime(
                user['created_at'], '%Y-%m-%d %H:%M:%S'
            )
            days_since_join = (datetime.now() - created_date).days
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

    trust_score += min(25, (listing_count // 2) * 2)

    if user['active_hours'] and user['active_hours'] != 'Not set':
        trust_score += 10
    if user['gender']:
        trust_score += 5

    trust_score = min(trust_score, 100)
    trust_score = max(trust_score, 30)

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

    # Check if username already taken
    existing = db.execute(
        'SELECT id FROM users WHERE username = ? AND id != ?',
        (username, session['user_id'])
    ).fetchone()
    if existing:
        db.close()
        flash('Username already taken', 'error')
        return redirect(url_for('edit_profile'))

    # Update all fields
    db.execute("""
        UPDATE users
        SET username = ?, full_name = ?, bio = ?,
            contact = ?, gender = ?, active_hours = ?
        WHERE id = ?
    """, (username, full_name, bio, contact, gender,
          active_hours, session['user_id']))

    db.commit()
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
    user = db.execute(
        'SELECT * FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()

    if not user:
        db.close()
        flash('User not found', 'error')
        return redirect(url_for('edit_profile'))

    if not check_password_hash(user['password'], current_password):
        db.close()
        flash('Current password is incorrect', 'error')
        return redirect(url_for('edit_profile'))

    if new_password != confirm_password:
        db.close()
        flash('New passwords do not match', 'error')
        return redirect(url_for('edit_profile'))

    hashed = generate_password_hash(new_password)
    db.execute(
        'UPDATE users SET password = ? WHERE id = ?',
        (hashed, session['user_id'])
    )
    db.commit()
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
    user = db.execute(
        'SELECT * FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()

    if not check_password_hash(user['password'], password):
        flash('Password is incorrect', 'error')
        return redirect(url_for('edit_profile'))

    db.execute('DELETE FROM products WHERE seller_id = ?', (session['user_id'],))
    db.execute("""
        DELETE FROM orders WHERE buyer_id = ? OR seller_id = ?
    """, (session['user_id'], session['user_id']))
    db.execute('DELETE FROM notifications WHERE user_id = ?', (session['user_id'],))
    db.execute('DELETE FROM users WHERE id = ?', (session['user_id'],))
    db.commit()
    db.close()

    session.clear()
    flash('Your account has been permanently deleted', 'info')
    return redirect(url_for('login'))


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
    user = db.execute(
        'SELECT password FROM users WHERE id = ?',
        (session['user_id'],)
    ).fetchone()
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
            user = db.execute(
                'SELECT id, security_q1, security_q2 FROM users WHERE email = ?',
                (email,)
            ).fetchone()
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
            user = db.execute(
                'SELECT id, security_a1, security_a2 FROM users WHERE email = ?',
                (email,)
            ).fetchone()
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
            db.execute(
                'UPDATE users SET password = ? WHERE email = ?',
                (hashed, email)
            )
            db.commit()
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

        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE email = ? AND is_admin = 1',
            (email,)
        ).fetchone()
        db.close()

        if user and check_password_hash(user['password'], password):
            session['admin_logged_in'] = True
            session['admin_email'] = user['email']
            session['admin_username'] = user['username']
            flash('Admin login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials', 'error')

    return render_template('admin_login.html')


# ============================================================
# Keting's Route - Admin Dashboard
# ============================================================
@app.route('/admin/dashboard')

def admin_dashboard():
    if not session.get('admin_logged_in'):
        flash('Please login as admin first', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()

    total_products = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    # Total registered users
    total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # Approved products count
    approved_count = db.execute(
        "SELECT COUNT(*) FROM products WHERE status = 'approved'"
    ).fetchone()[0]

    # Pending products count
    pending_count = db.execute(
        "SELECT COUNT(*) FROM products WHERE status = 'pending'"
    ).fetchone()[0]

    # Active sellers count (users with at least one product)
    seller_count = db.execute(
        "SELECT COUNT(DISTINCT seller_id) FROM products"
    ).fetchone()[0]

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
    users = db.execute("SELECT * FROM users").fetchall()
    db.close()
    return render_template("admin_users.html", users=users)


@app.route('/admin/products')

def admin_products():
    if not session.get('admin_logged_in'):
        flash('Please login as admin first', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    pending = db.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'pending' ORDER BY p.created_at DESC
    ''').fetchall()

    approved = db.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'approved' ORDER BY p.created_at DESC
    ''').fetchall()

    rejected = db.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p JOIN users u ON p.seller_id = u.id
        WHERE p.status = 'rejected' ORDER BY p.created_at DESC
    ''').fetchall()
    
    # Convert database rows to Python dictionaries
    pending = [dict(row) for row in pending]
    approved = [dict(row) for row in approved]
    rejected = [dict(row) for row in rejected]

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
    db.execute('''
        UPDATE products
        SET status = 'approved', reject_reason = ''
        WHERE id = ?
    ''', (pid,))

    db.commit()
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
    db.execute('''
        UPDATE products
        SET status = 'rejected', reject_reason = ?
        WHERE id = ?
    ''', (reject_reason, pid))

    db.commit()
    db.close()

    flash("Product rejected successfully", "success")
    return redirect(url_for('admin_products'))


# Admin API - Get product info for modal
@app.route('/admin/api/product/<int:pid>')

def admin_get_product_info(pid):
    if not session.get('admin_logged_in'):
        return {"error": "no permission"}, 403

    db = get_db()
    product = db.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.id = ?
    ''', (pid,)).fetchone()
    db.close()

    if not product:
        return {"error": "not found"}, 404

    return dict(product)


# Freeze user for 7 days
@app.route("/admin/user/<int:user_id>/freeze", methods=["POST"])

def freeze_7day(user_id):
    if not session.get("admin_logged_in"):
        flash("Unauthorized", "error")
        return redirect(url_for("admin_login"))

    reason = request.form.get('reason', 'No reason provided').strip()
    now = datetime.now()
    frozen_end_time = now + timedelta(days=7)
    time_str = frozen_end_time.strftime("%Y-%m-%d %H:%M:%S")

    db = get_db()
    db.execute("""
        UPDATE users
        SET is_frozen = 1,
            frozen_until = ?,
            freeze_reason = ?
        WHERE id = ?
    """, (time_str, reason, user_id))

    db.execute("""
        INSERT INTO notifications (user_id, message, created_at)
        VALUES (?, ?, ?)
    """, (
        user_id,
        f"Your account has been frozen for 7 days.\nReason: {reason}\nAuto unfreeze: {time_str}",
        now.strftime("%Y-%m-%d %H:%M:%S")
    ))

    db.commit()
    db.close()
    flash("User successfully frozen for 7 days.", "success")
    return redirect(url_for("admin_users"))


# Block user permanently
@app.route('/admin/user/<int:user_id>/block', methods=['POST'])

def block_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    reason = request.form.get('reason', 'No reason provided')
    db = get_db()

    db.execute("UPDATE users SET is_blocked = 1 WHERE id = ?", (user_id,))
    db.execute("""
        INSERT INTO notifications (user_id, message, is_read)
        VALUES (?, ?, 0)
    """, (user_id, f"Your account has been PERMANENTLY blocked. "
                   f"Reason: {reason}"))

    db.commit()
    db.close()
    flash(f"User {user_id} has been permanently blocked, notification sent.", "success")

    return redirect(url_for('admin_users'))


@app.route("/admin/unfreeze/<int:user_id>", methods=["POST"])

def unfreeze_user(user_id):
    if not session.get("admin_logged_in"):
        flash("Unauthorized", "error")
        return redirect(url_for("admin_login"))

    db = get_db()
    db.execute("""
        UPDATE users
        SET is_frozen = 0, frozen_until = NULL, freeze_reason = NULL
        WHERE id = ?
    """, (user_id,))
    db.commit()
    db.close()

    flash("User has been unfrozen successfully.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/unblock/<int:user_id>", methods=["POST"])

def unblock_user(user_id):
    if not session.get("admin_logged_in"):
        flash("Unauthorized", "error")
        return redirect(url_for("admin_login"))

    db = get_db()
    db.execute("""
        UPDATE users
        SET is_blocked = 0
        WHERE id = ?
    """, (user_id,))
    db.commit()
    db.close()

    flash("User ban has been lifted successfully.", "success")
    return redirect(url_for("admin_users"))


# ============================================================
# Chat List Route
# ============================================================
@app.route('/chatlist')

def user_chatlist():
    if 'user_id' not in session:
        flash("Please login first", "error")
        return redirect(url_for('login'))
    return render_template('user_chatlist.html')


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

        # Validate images
        files = request.files.getlist('product_images')
        ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov'}
        invalid_files = []
        valid_files = []

        for file in files:
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
                if ext not in ALLOWED_EXTENSIONS:
                    invalid_files.append(file.filename)
                else:
                    valid_files.append(file)

        # If any invalid file is found, abort the whole upload
        if invalid_files:
            flash(f"Unsupported file type(s): {', '.join(invalid_files)}. Only images and MP4/WebM/MOV videos are allowed.", "error")
            return render_template('upload.html')

        # Now save only valid files (all are valid)
        saved_image_names = []
        for file in valid_files:
            original_filename = file.filename
            ext = original_filename.rsplit('.', 1)[-1].lower()
            filename = secure_filename(original_filename)
            if not filename:
                filename = f"media_{uuid.uuid4().hex}.{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            saved_image_names.append(filename)

            if ext in ['mp4', 'webm', 'mov']:
                thumb_filename = f"{os.path.splitext(filename)[0]}_thumb.jpg"
                thumb_path = os.path.join(app.config['UPLOAD_FOLDER'], thumb_filename)
                generate_video_thumbnail(filepath, thumb_path)

        if not saved_image_names:
            errors.append("Please upload at least one photo.")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template('upload.html')

        images_string = ",".join(saved_image_names)
        db = get_db()
        db.execute('''
            INSERT INTO products (seller_id, name, price,
                    description, condition, category, images, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ''', (seller_id, name,
              price_val, description,
              condition, category, images_string, 'pending'))
        db.commit()
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
    db.execute("DELETE FROM products")
    db.execute("DELETE FROM sqlite_sequence WHERE name='products'")
    db.commit()
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
    product = db.execute('''
        SELECT p.*, u.username as seller_name, u.full_name as seller_full_name,
            u.avatar_blob as seller_avatar, u.id as seller_id, u.created_at as user_joined
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.id = ? AND p.status = 'approved'
    ''', (product_id,)).fetchone()
    db.close()

    if not product:
        flash('Product not found or not yet approved.', 'error')
        return redirect(url_for('home'))

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
