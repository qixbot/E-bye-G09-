from flask import Flask, render_template 
import sqlite3
app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('ebye.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS USERS (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            gender TEXT DEFAULT 'Prefer not to say',
            active_status INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()
    print("Database ready!")

@app.route('/')
def home():
    return render_template('index.html')

if __name__ == '__main__':
    init_db()
    app.run(debug=True)