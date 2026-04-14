import re
from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import init_db, get_db
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'e-bye-secret-key-2025'

# initialize the database
init_db()

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
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('home.html', username=session.get('username'))

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
        
        # here do simple validation, afterthat will be changed to database validation
        # temporary admin account
        if email == 'admin@student.mmu.edu.my' and password == 'Admin@2025':
            session['admin_logged_in'] = True
            flash('Welcome, Administrator!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials', 'error')
    
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        flash('Please login as admin first', 'error')
        return redirect(url_for('admin_login'))
    return render_template('admin_dashboard.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')  # 修正: get 不是 grt
        
        # validate email
        if not email:
            flash('Email is required', 'error')
            return render_template('forgot_password.html')
        
        if not email.endswith('@student.mmu.edu.my'):
            flash('Only @student.mmu.edu.my emails are allowed', 'error')
            return render_template('forgot_password.html')
        
        # validate password
        if not password:
            flash('Password is required', 'error')
            return render_template('forgot_password.html')
        
        if len(password) < 8:
            flash('Password must be at least 8 characters', 'error')
            return render_template('forgot_password.html')
        
        if not re.search(r'[A-Z]', password):
            flash('Password must contain at least 1 uppercase letter', 'error')
            return render_template('forgot_password.html')
        
        if not re.search(r'[a-z]', password):
            flash('Password must contain at least 1 lowercase letter', 'error')
            return render_template('forgot_password.html')
        
        if not re.search(r'[0-9]', password):
            flash('Password must contain at least 1 number', 'error')
            return render_template('forgot_password.html')
        
        if not re.search(r'[!@#$%^&*]', password):
            flash('Password must contain at least 1 special character', 'error')
            return render_template('forgot_password.html')
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('forgot_password.html')
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        
        if not user:
            flash('No account found with this email address', 'error')
            return render_template('forgot_password.html')
        
        # update password
        hashed_password = generate_password_hash(password)
        db.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_password, user['id']))
        db.commit()
        
        flash('Password reset successfully! Please login with your new password.', 'success')
        return redirect(url_for('login'))
    
    return render_template('forgot_password.html')

if __name__ == '__main__':
    app.run(debug=True)