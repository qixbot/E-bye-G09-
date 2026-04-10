from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import init_db, get_db
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'e-bye-secret-key-2025'

# 初始化数据库
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
        
        # 验证
        errors = []
        if not student_id or len(student_id) < 8:
            errors.append('Valid Student ID is required')
        if not email.endswith('@mmu.edu.my') and not email.endswith('@student.mmu.edu.my'):
            errors.append('Only MMU email addresses are allowed')
        if password != confirm_password:
            errors.append('Passwords do not match')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html')
        
        db = get_db()
        
        # 检查唯一性
        existing = db.execute('SELECT * FROM users WHERE student_id = ? OR email = ?', 
                              (student_id, email)).fetchone()
        if existing:
            flash('Student ID or Email already registered', 'error')
            return render_template('register.html')
        
        # 创建用户
        hashed_password = generate_password_hash(password)
        db.execute('''
            INSERT INTO users (student_id, email, username, password)
            VALUES (?, ?, ?, ?)
        ''', (student_id, email, username, hashed_password))
        db.commit()
        
        flash('Account created! Please login.', 'success')
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

if __name__ == '__main__':
    app.run(debug=True)