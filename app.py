import re
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import init_db, get_db, init_products
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'e-bye-secret-key-2026'

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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['student_id'] = user['student_id']
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('login.html')

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
        existing = db.execute('SELECT * FROM users WHERE student_id = ? OR email = ?', 
                              (student_id, email)).fetchone()
        if existing:
            flash('Student ID or Email already registered', 'error')
            return render_template('register.html')
        
        # create user with gender field
        hashed_password = generate_password_hash(password)
        db.execute('''
            INSERT INTO users (student_id, email, username, password, gender)
            VALUES (?, ?, ?, ?, ?)
        ''', (student_id, email, username, hashed_password, gender))
        db.commit()
        
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/home')
def home():
    #if 'user_id' not in session:
    #    return redirect(url_for('login'))
    
    db = get_db()
    # Fetch all products and the seller's username
    products_data = db.execute('''
        SELECT p.*, u.username as seller_name 
        FROM products p
        JOIN users u ON p.seller_id = u.id
        ORDER BY p.created_at DESC
    ''').fetchall()
    db.close()
    return render_template('home.html', username=session.get('username'), latest_products=products_data)

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out', 'info')
    return redirect(url_for('login'))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        # Add your admin authentication logic here
        flash('Admin login demo - implement your logic', 'info')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')

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


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    return render_template('forgot_password.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_product():
    #if 'user_id' not in session:
        flash("You must be logged in to post an item.", "error")
    #    return redirect(url_for('login'))

    if request.method == 'POST':
        # 1. Get the text data from the form
        name = request.form.get('item_name')
        price = request.form.get('item_price') 
        description = request.form.get('item_desc')
        condition = request.form.get('item_condition') 
        category = request.form.get('item_category') 
        seller_id = session['user_id']

        # 2. Get the images (up to 12)
        files = request.files.getlist('product_images')
        saved_image_names = []
        
        for file in files:
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                saved_image_names.append(filename)

        # Join the image names with commas
        images_string = ",".join(saved_image_names)

        # 3. Save everything to the database
        db = get_db()
        db.execute('''
            INSERT INTO products (seller_id, name, price, description, condition, category, images)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (seller_id, name, price, description, condition, category, images_string))
        db.commit()
        db.close()

        flash("Your item has been successfully listed!", "success")
        return redirect(url_for('home'))

    return render_template('upload.html')

if __name__ == '__main__':
    app.run(debug=True)