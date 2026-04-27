import re

import os

import uuid

import sqlite3

from datetime import datetime, timedelta

from flask import (
    Flask,
    render_template,
    request, redirect,
    url_for, session, flash, jsonify
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

# --- Setup folder for uploaded product images ---
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# initialize the database
init_db()
init_products()

@app.route('/')

def index():
    return redirect(url_for('login'))

# Eileen and Keting
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

        # Account+password check vakidation if correct then will pass to verify
        if user and check_password_hash(user['password'], password):

            # Block the user permanenetly
            if user['is_blocked'] == 1:
                flash('❌ This account is permanently blocked.', 'danger')
                return redirect(url_for('login'))

            # time-limited freezing and precise interception
            is_user_frozen = user['is_frozen']
            frozen_end_time = user['frozen_until']

            if is_user_frozen == 1 and frozen_end_time:
                now = datetime.now()
                expire_time = None

                # Security analysis time
                try:
                    expire_time = datetime.strptime(frozen_end_time, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

                # The account is still frozen and will be forcibly blocked.
                if expire_time and now < expire_time:
                    # Calculate the remaining thawing time
                    time_diff = expire_time - now
                    remain_days = time_diff.days
                    remain_hours = time_diff.seconds // 3600

                    # Reasons for compatibility with empty freeze
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

                # The freeze period has expired; it will automatically unfreeze.
                else:
                    db_auto_unfreeze = get_db()
                    db_auto_unfreeze.execute("""
                        UPDATE users
                        SET is_frozen = 0, frozen_until = NULL, freeze_reason = NULL
                        WHERE id = ?
                    """, (user["id"],))
                    db_auto_unfreeze.commit()
                    db_auto_unfreeze.close()

            # All verifications passed, now officially logged in.
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['student_id'] = user['student_id']

            if remember_me:
                session.permanent = True
            else:
                session.permanent = False

            flash('✅ Login successful!', 'success')
            return redirect(url_for('home'))

        # Account/password error fallback
        else:
            flash('Invalid email or password', 'error')

    return render_template('login.html')

# Eileen's Route
@app.route('/register', methods=['GET', 'POST'])

def register():
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        gender = request.form.get('gender')

        # Verification and validation
        q1 = request.form.get('q1', '').strip()
        a1 = request.form.get('a1', '').strip().lower()
        q2 = request.form.get('q2', '').strip()
        a2 = request.form.get('a2', '').strip().lower()

        errors = []

        # Student ID
        if not student_id or len(student_id) != 10:
            errors.append('Please enter a valid Student ID (10 characters)')
        elif not student_id.replace(' ', '').isalnum():
            errors.append('Student ID must contain only letters and numbers')

        # Email
        if not email:
            errors.append('Email is required')
        elif not (email.endswith('@student.mmu.edu.my')):
            errors.append(
                'Only MMU email addresses are allowed '
                '(@student.mmu.edu.my)')

        # Username
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters')

        # Password - increase complexity requirements
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
                errors.append(
                    'Password must contain at least 1 special character '
                    '(! @ # $ % ^ & *)')

        # Confirm password
        if password != confirm_password:
            errors.append('Passwords do not match')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html')

        db = get_db()

        # Check if student_id or email already exists
        existing = db.execute(
            'SELECT * FROM users WHERE student_id = ? OR LOWER(email) = LOWER(?)',
            (student_id, email)
        ).fetchone()
        if existing:
            db.close()
            flash('Student ID or Email already registered', 'error')
            return render_template('register.html')

        username_exists = db.execute(
            'SELECT * FROM users WHERE LOWER(username) = LOWER(?)',
            (username,)
        ).fetchone()
        if username_exists:
            db.close()
            flash('Username already taken. Please choose another one.', 'error')
            return render_template('register.html')

        # Create user with gender field
        hashed_password = generate_password_hash(password)
        db.execute('''
            INSERT INTO users (student_id, email, username, password, gender,
                    security_q1, security_a1, security_q2, security_a2)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (student_id, email, username, hashed_password, gender, q1, a1, q2, a2))
        db.commit()
        db.close()

        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# Xingru's Route ------Homepage
@app.route('/home')

def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    products_data = db.execute('''
        SELECT p.*, u.username as seller_name 
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
            image_extensions = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
            image_only = [f for f in img_list if f.split('.')[-1].lower() in image_extensions]
            product['images_list'] = image_only[:3]      # for carousel (only images)
            product['actual_total'] = len(img_list)      # total media (including videos)
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

# Eileen's Route-Forgot Password
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

            # Store in session so step 2 knows which user
            session['fp_email'] = email
            session['fp_q1'] = user['security_q1']
            session['fp_q2'] = user['security_q2']
            return render_template('forgot_password.html',
                                   step=2,
                                   q1=user['security_q1'],
                                   q2=user['security_q2'])

        # Step 2: verify security question answers
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

            if a1_input != user['security_a1'] or a2_input != user['security_a2']:
                flash(
                    'One or both answers are incorrect. Please try again.', 'error')
                return render_template('forgot_password.html',
                                       step=2,
                                       q1=session.get('fp_q1'),
                                       q2=session.get('fp_q2'))

            # Answers correct — allow password reset
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

            # Update password in database
            hashed = generate_password_hash(new_password)
            db = get_db()
            db.execute(
                'UPDATE users SET password = ? WHERE email = ?',
                (hashed, email)
            )
            db.commit()
            db.close()

            # Clear forgot-password session keys
            session.pop('fp_email', None)
            session.pop('fp_q1', None)
            session.pop('fp_q2', None)
            session.pop('fp_verified', None)

            flash(
                'Password reset successfully! '
                'Please login with your new password.', 'success'
            )
            return redirect(url_for('login'))

    return render_template('forgot_password.html')

# Eileen's Route
@app.route('/admin/login', methods=['GET', 'POST'])

def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE email = ? AND is_admin = 1', (email,)
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

# Eileen's Route ------EDIT profile
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

    # Gain trust score and response rate
    # Basic mark=60. the below is 5 mark
    # 10 listing can go up to 20 marks
    trust_score = 60
    if user['avatar']:        trust_score += 8
    if user['bio']:           trust_score += 8
    if user['contact']:       trust_score += 7
    if user['full_name']:     trust_score += 7

    if user['created_at']:
        try:
            created_date = datetime.strptime(user['created_at'], '%Y-%m-%d %H:%M:%S')
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

    # 商品数量加分（最多25分）
    trust_score += min(25, (listing_count // 2) * 2)  # 每2个商品加2分，最高25分

    # 活跃度加分（最多15分）
    if user['active_hours'] and user['active_hours'] != 'Not set':
        trust_score += 10
    if user['gender']:
        trust_score += 5

    trust_score = min(trust_score, 100)
    trust_score = max(trust_score, 30)

    # 修复 Response Rate（如果没有聊天功能，暂时用商品活跃度代替）==========
    # 真正的响应率需要聊天数据，这里先用商品和活跃度估算
    response_rate = 50  # 基础分

    # 有商品在售加10分
    if listing_count > 0:
        response_rate += 15

    # 有完善资料加10分
    if user['bio'] and user['contact']:
        response_rate += 10

    # 有活跃时间加10分
    if user['active_hours'] and user['active_hours'] != 'Not set':
        response_rate += 10

    # 有头像加5分
    if user['avatar']:
        response_rate += 5

    response_rate = min(response_rate, 98)
    response_rate = max(response_rate, 40)


    if user:
            user_dict = dict(user)
            bg_image_value = user_dict.get('bg_image')
    else:
            bg_image_value = None

    db.close()
    return render_template(
        'edit_profile.html',
        user=user,
        listing_count=listing_count,
        sold_count=0,
        trust_score=trust_score,
        response_rate=response_rate,
        bg_image=bg_image_value
    )

# Eileen's Route ------UPDATE profile
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

    # Handle avatar upload
    avatar = request.files.get('avatar')
    if avatar and avatar.filename:
        filename = secure_filename(f"avatar_{session['user_id']}_{avatar.filename}")
        avatar.save(os.path.join('static/uploads', filename))
        db.execute(
            'UPDATE users SET avatar = ? WHERE id = ?',
            (filename, session['user_id'])
        )

    # Handle cover image upload
    cover = request.files.get('cover_image')
    if cover and cover.filename:
        filename = secure_filename(f"cover_{session['user_id']}_{cover.filename}")
        cover.save(os.path.join('static/uploads', filename))
        db.execute(
            'UPDATE users SET cover_image = ? WHERE id = ?',
            (filename, session['user_id'])
        )

    # Handle background image upload
    bg_image = request.files.get('bg_image')
    if bg_image and bg_image.filename:
        ext = bg_image.filename.rsplit('.', 1)[-1].lower() if '.' in bg_image.filename else 'jpg'
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            bg_filename = secure_filename(f"bg_{session['user_id']}_{uuid.uuid4().hex}.{ext}")
            bg_image.save(os.path.join('static/uploads', bg_filename))
            db.execute(
                'UPDATE users SET bg_image = ? WHERE id = ?',
                (bg_filename, session['user_id'])
            )

    # Update other fields
    db.execute('''        
        UPDATE users 
        SET username = ?, full_name = ?, bio = ?,
            contact = ?, gender = ?, active_hours = ?
        WHERE id = ?
    ''', (username, full_name, bio, contact, gender, active_hours, session['user_id']))

    db.commit()
    db.close()

    session['username'] = username
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('edit_profile'))

# Eileen's Route ------Upload Background profile
@app.route('/upload-background', methods=['POST'])

def upload_background():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if 'bg_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['bg_image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    if file:
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
        if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            return jsonify({'success': False, 'error': 'Unsupported file format'}), 400

        filename = secure_filename(f"bg_{session['user_id']}_{uuid.uuid4().hex}.{ext}")
        filepath = os.path.join('static/uploads', filename)
        file.save(filepath)

        return jsonify({
            'success': True,
            'image_url': url_for('static', filename=f'uploads/{filename}')
        })

    return jsonify({'success': False, 'error': 'Upload failed'}), 500

@app.route('/save-background', methods=['POST'])

def save_background():

    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    bg_filename = request.form.get('bg_image_filename')
    if not bg_filename:
        return jsonify({'success': False, 'error': 'No filename provided'}), 400

    db = get_db()
    db.execute(
        'UPDATE users SET bg_image = ? WHERE id = ?',
        (bg_filename, session['user_id'])
    )
    db.commit()
    db.close()

    return jsonify({'success': True})

# 保存预设背景到数据库
@app.route('/save-background-preset', methods=['POST'])

def save_background_preset():

    if 'user_id' not in session:
        return jsonify({'success': False}), 401
    data = request.get_json()
    bg_type = data.get('bg_type', 'default')

    db = get_db()
    db.execute('UPDATE users SET bg_type = ? WHERE id = ?', (bg_type, session['user_id']))
    db.commit()
    db.close()
    
    return jsonify({'success': True})


# Eileen's Route ------CHANGE password
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

# Eileen's Route ------DELETE account
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
    db.execute('DELETE FROM orders WHERE buyer_id = ? OR seller_id = ?',
               (session['user_id'], session['user_id']))
    db.execute('DELETE FROM notifications WHERE user_id = ?', (session['user_id'],))
    db.execute('DELETE FROM users WHERE id = ?', (session['user_id'],))
    db.commit()
    db.close()

    session.clear()
    flash('Your account has been permanently deleted', 'info')
    return redirect(url_for('login'))

# Eileen's Route ------VERIFY password
@app.route('/verify-password', methods=['POST'])

def verify_password():
    if 'user_id' not in session:
        return jsonify({'valid': False}), 401
    
    data = request.get_json()
    password = data.get('password', '')
    
    db = get_db()
    user = db.execute('SELECT password FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    db.close()
    
    if user and check_password_hash(user['password'], password):
        return jsonify({'valid': True})
    else:
        return jsonify({'valid': False})
    
#Eileen's Route ------ UPDATE background cover
@app.route('/update-cover', methods=['POST'])

def update_cover():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if 'cover_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['cover_image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    if file:
        original_filename = secure_filename(file.filename)
        if not original_filename:
            original_filename = f"cover_{uuid.uuid4().hex}.jpg"
        filepath = os.path.join('static/uploads', original_filename)
        file.save(filepath)

        db = get_db()
        db.execute(
            'UPDATE users SET cover_image = ? WHERE id = ?',
            (original_filename, session['user_id']))
        db.commit()
        db.close()

        return jsonify(
            {'success': True, 'image_url': url_for('static',filename=f'uploads/{original_filename}')})

    return jsonify({'success': False, 'error': 'Upload failed'}), 500

#Eileen's Route ------ UPDATE profile avatar
@app.route('/update-profile-avatar', methods=['POST'])

def update_profile_avatar():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'No file'}), 400
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
    filename = secure_filename(f"avatar_{session['user_id']}_{uuid.uuid4().hex}.{ext}")
    filepath = os.path.join('static/uploads', filename)
    file.save(filepath)
    db = get_db()
    db.execute('UPDATE users SET avatar = ? WHERE id = ?', (filename, session['user_id']))
    db.commit()
    db.close()
    return jsonify({'success': True, 'image_url': url_for('static', filename=f'uploads/{filename}')})

#Eileen's Route ------ api
@app.route('/api/user/purchases')

def api_user_purchases():
    if 'user_id' not in session:
        return jsonify([])
    # You need to implement purchases logic or return empty for now
    return jsonify([])

#Eileen's Route ------ api
@app.route('/api/user/listings')

def api_user_listings():
    if 'user_id' not in session:
        return jsonify([])
    db = get_db()
    rows = db.execute('''
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
    ''', (session['user_id'],)).fetchall()
    db.close()
    return jsonify([dict(row) for row in rows])

# keting's route
@app.route('/admin/dashboard')

def admin_dashboard():
    if not session.get('admin_logged_in'):
        flash('Please login as admin first', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()

    total_products = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    
    # 总注册用户数
    total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    
    # 已通过审核的商品数
    approved_count = db.execute(
        "SELECT COUNT(*) FROM products WHERE status = 'approved'"
    ).fetchone()[0]
    
    # 待审核商品数
    pending_count = db.execute(
        "SELECT COUNT(*) FROM products WHERE status = 'pending'"
    ).fetchone()[0]
    
    # 活跃卖家数（有至少一个商品的用户）
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
    # 把数据库原生Row，全部转成Python标准字典
    pending = [dict(row) for row in pending]
    approved = [dict(row) for row in approved]
    rejected = [dict(row) for row in rejected]

    db.close()

    # 这里三个参数一个都不能少！
    return render_template("admin_product.html",
                           pending_list=pending,
                           approved_list=approved,
                           rejected_list=rejected)
# 审核通过商品
@app.route('/admin/product/approve/<int:pid>')
def approve_product(pid):
    if not session.get('admin_logged_in'):
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    # 更新商品状态+清空驳回理由
    db.execute('''
        UPDATE products 
        SET status = 'approved', reject_reason = ''
        WHERE id = ?
    ''', (pid,))

    # 获取商品和卖家信息，用于发通知
    prod = db.execute('SELECT seller_id, name FROM products WHERE id = ?',(pid,)).fetchone()
    seller_id = prod['seller_id']
    prod_name = prod['name']

    db.commit()
    db.close()

    # 【之后对接ChatList通知在这里加】
    # 通知文案：✅ 你的商品【{prod_name}】审核已通过，现已上架展示！

    flash("Product approved successfully, now visible on homepage", "success")
    return redirect(url_for('admin_products'))


# 驳回商品 + 填写理由
@app.route('/admin/product/reject/<int:pid>', methods=['POST'])
def reject_product(pid):
    if not session.get('admin_logged_in'):
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_login'))

    reject_reason = request.form.get('reject_reason','').strip()
    if not reject_reason:
        flash("Please provide a reason for rejection", "error")
        return redirect(url_for('admin_products'))

    db = get_db()
    db.execute('''
        UPDATE products 
        SET status = 'rejected', reject_reason = ?
        WHERE id = ?
    ''', (reject_reason, pid))

    prod = db.execute('SELECT seller_id, name FROM products WHERE id = ?',(pid,)).fetchone()
    seller_id = prod['seller_id']
    prod_name = prod['name']

    db.commit()
    db.close()

    # 【之后对接ChatList通知在这里加】
    # 通知文案：❌ 你的商品【{prod_name}】审核驳回，原因：{reject_reason}，修改后可重新上传

    flash("Product rejected successfully", "success")
    return redirect(url_for('admin_products'))

# Admin 弹窗专用 拿商品完整信息
@app.route('/admin/api/product/<int:pid>')
def admin_get_product_info(pid):
    if not session.get('admin_logged_in'):
        return {"error":"no permission"},403

    db = get_db()
    product = db.execute('''
        SELECT p.*, u.username as seller_name
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.id = ?
    ''', (pid,)).fetchone()
    db.close()

    if not product:
        return {"error":"not found"},404

    # 直接转字典给前端弹窗用
    return dict(product)

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

@app.route('/admin/user/<int:user_id>/block', methods=['POST'])

def block_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    reason = request.form.get('reason', 'No reason provided')
    db = get_db()

    # 1.Add a "permanent ban mark" to the user
    db.execute("UPDATE users SET is_blocked = 1 WHERE id = ?", (user_id,))

    # 2.Send a "Ban Notice" to this user
    db.execute(
        "INSERT INTO notifications (user_id, message, is_read) VALUES (?, ?, 0)",
        (user_id, f"Your account has been PERMANENTLY blocked. Reason: {reason}")
    )

    db.commit()
    db.close()
    flash(
        f"User {user_id} has been permanently blocked, notification sent.",
        "success"
    )

    return redirect(url_for('admin_users'))

@app.route("/admin/unfreeze/<int:user_id>", methods=["POST"])

def unfreeze_user(user_id):

    if not session.get("admin_logged_in"):
        flash("Unauthorized")
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
        flash("Unauthorized")
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

@app.route('/chatlist')

def user_chatlist():
    if 'user_id' not in session:
        flash("Please login first", "error")
        return redirect(url_for('login'))
    return render_template('user_chatlist.html')

# Xingru's Route ------Upload product
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

        # Price validation and rounding
        price_val = None
        try:
            price_val = float(price)
            if price_val < 0:
                errors.append("Price cannot be negative.")
            elif price_val > 9999999:
                errors.append("Price cannot exceed RM 9,999,999.")
            else:
                # Round to 2 decimal places
                price_val = round(price_val, 2)
        except ValueError:
            errors.append("Please enter a valid price.")

        # Validate images
        files = request.files.getlist('product_images')
        saved_image_names = []
        ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov'}

        for file in files:
            if file and file.filename != '':
                # Check extension
                original_filename = file.filename
                ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
                if ext not in ALLOWED_EXTENSIONS:
                    flash(f"Unsupported file type: {original_filename}. Only images and MP4/WebM/MOV videos are allowed.", "error")
                    continue   # skip this file, continue with others
                
                filename = secure_filename(original_filename)
                if not filename:
                    filename = f"media_{uuid.uuid4().hex}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                saved_image_names.append(filename)

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

        flash("Your item has been submitted for admin approval."
              " It will appear once approved.", "success")
        return redirect(url_for('home'))

    return render_template('upload.html')

#(Xingru) For testing purposes only - clear all products from database
#This route is not linked from anywhere in the UI and should be used with caution.
@app.route('/clear-products')

def clear_products():
    db = get_db()
    db.execute("DELETE FROM products")
    db.execute("DELETE FROM sqlite_sequence WHERE name='products'")
    db.commit()
    db.close()
    return "All products deleted."

#Xingru's Route ------Product details page
@app.route('/product/<int:product_id>')

def product_detail(product_id):
    if 'user_id' not in session:
        flash('Please login to view product details.', 'error')
        return redirect(url_for('login'))

    db = get_db()
    product = db.execute('''
        SELECT p.*, u.username as seller_name, 
                         u.id as seller_id, u.created_at as user_joined
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.id = ? AND p.status = 'approved'
    ''', (product_id,)).fetchone()
    db.close()

    if not product:
        flash('Product not found or not yet approved.', 'error')
        return redirect(url_for('home'))

    # Split images into list
    images = product['images'].split(',') if product['images'] else []

    return render_template('product.html', product=product, images=images)


#Xingru's Route ------Temporary route for testing product page only
@app.route('/user/<int:user_id>')
def user_profile(user_id):
    if 'user_id' not in session:
        flash('Please login to view profiles.', 'error')
        return redirect(url_for('login'))
    flash('Profile page is under construction.', 'info')
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)
