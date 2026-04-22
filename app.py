from ast import For
import re
import os
import sqlite3
import datetime
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import init_db, get_db, init_products
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'e-bye-secret-key-2026-new'

# --- Setup folder for uploaded product images ---
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# initialize the database
init_db()
init_products()

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return redirect(url_for('login'))

# Eileen's Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember_me = request.form.get('remember_me') 

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE LOWER(email) = LOWER(?)",
            (email,)
        ).fetchone()
        user = db.execute(
            'SELECT * FROM users WHERE LOWER(email) = LOWER(?)', 
            (email,)).fetchone()
        db.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash("✅ Login successful!", "success")
            db.close()
            session['student_id'] = user['student_id']
            
            if remember_me:
                session.permanent = True
            else:
                session.permanent = False
            
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
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
        
        # verification and validation
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
            errors.append('Only MMU email addresses are allowed (@student.mmu.edu.my)')
        
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
                errors.append('Password must contain at least 1 special character (! @ # $ % ^ & *)')
        
        # Confirm password
        if password != confirm_password:
            errors.append('Passwords do not match')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html')
        
        db = get_db()
        
        # check if student_id or email already exists
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
        
        # create user with gender field
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
            product['images_list'] = img_list   # full list
            product['image_1'] = img_list[0] if len(img_list) > 0 else None
            product['image_2'] = img_list[1] if len(img_list) > 1 else None
        else:
            product['images_list'] = []
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

#Eileen's Route
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
 
            flash('Password reset successfully! Please login with your new password.', 'success')
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

#Eileen's Route ------EDIT profile
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

    db.close()
    return render_template(
        'edit_profile.html',
        user=user,
        listing_count=listing_count,
        sold_count=0
    )


#Eileen's Route ------UPDATE profile
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
    
    # Update other fields
    db.execute(
        'UPDATE users SET username = ?, full_name = ?, bio = ?, '
        'contact = ?, gender = ?, active_hours = ? WHERE id = ?',
    (username, full_name, bio, contact, gender, active_hours, session['user_id'])
    )
    
    db.commit()
    db.close()

    session['username'] = username
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('edit_profile'))


#Eileen's Route ------CHANGE password 
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
          

#Eileen's Route ------DELETE account
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


#keting's route
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        flash('Please login as admin first', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    db.close()
    
    return render_template("admin_dashboard.html", total_users=total_users)

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
    
    return render_template("admin_products.html")

@app.route('/admin/user/<int:user_id>/freeze', methods=['POST'])
def freeze_user(user_id):
    # Administrator Permission Verification
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    reason = request.form.get('reason', 'No reason provided')
    db = get_db()
    
    # 1.Add a "freeze tag" to the user
    db.execute("UPDATE users SET is_frozen = 1 WHERE id = ?", (user_id,))
    
   # 2.Send a "Freeze Notice" to the user
    db.execute(
        "INSERT INTO notifications (user_id, message, is_read) VALUES (?, ?, 0)",
        (user_id, f"Your account has been frozen. Reason: {reason}")
    )
    
    db.commit()
    db.close()
    flash(f"User {user_id} has been frozen, notification sent.", "success")
    return redirect(url_for('admin_users'))

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
    flash(f"User {user_id} has been permanently blocked, notification sent.", "success")
    return redirect(url_for('admin_users'))

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
        for file in files:
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                if not filename:
                    filename = f"image_{uuid.uuid4().hex}.jpg"
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
            INSERT INTO products (seller_id, name, price, description, condition, category, images, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ''', (seller_id, name, price_val, description, condition, category, images_string, 'pending'))
        db.commit()
        db.close()

        flash("Your item has been submitted for admin approval. It will appear once approved.", "success")
        return redirect(url_for('home'))

    return render_template('upload.html')


# --------(Xingru) For testing purposes only - clear all products from database -------------------------
# This route is not linked from anywhere in the UI and should be used with caution.

@app.route('/clear-products')
def clear_products():
    db = get_db()
    db.execute("DELETE FROM products")
    db.execute("DELETE FROM sqlite_sequence WHERE name='products'")
    db.commit()
    db.close()
    return "All products deleted."

# -----------------------------------------------------------------------------------------------

# Xingru's Route ------Product details page
@app.route('/product/<int:product_id>')
def product_detail(product_id):
    if 'user_id' not in session:
        flash('Please login to view product details.', 'error')
        return redirect(url_for('login'))

    db = get_db()
    product = db.execute('''
        SELECT p.*, u.username as seller_name, u.id as seller_id, u.created_at as user_joined
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

if __name__ == '__main__':
    app.run(debug=True)