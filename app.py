import os
import uuid
import sqlite3
from datetime import datetime
from flask import Flask, request, render_template, send_from_directory, redirect, abort, url_for
from werkzeug.utils import secure_filename
import qrcode
import cv2

# ---------- Configuration ----------
UPLOAD_FOLDER = "uploads"
GENERATED_FOLDER = "static/generated"
DB_PATH = "db.sqlite3"
ALLOWED_EXT = {"png", "jpg", "jpeg"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GENERATED_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me-in-prod")

# ---------- Database helpers ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE,
            original TEXT,
            used INTEGER DEFAULT 0,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_token(token, original):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO tokens (token, original, created_at) VALUES (?, ?, ?)', (token, original, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def mark_used(token):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE tokens SET used = 1 WHERE token = ?', (token,))
    conn.commit()
    conn.close()

def get_record(token):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT token, original, used FROM tokens WHERE token = ?', (token,))
    row = c.fetchone()
    conn.close()
    return row  # None or (token, original, used)

# ---------- Utilities ----------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def decode_qr_from_image(path):
    # משתמש ב-OpenCV כדי לפענח QR - מתאים לפריסה בענן (לא זקוק ל-zbar)
    img = cv2.imread(path)
    detector = cv2.QRCodeDetector()
    data, bbox, _ = detector.detectAndDecode(img)
    return data if data else None

def generate_one_time_qr(url, output_filename):
    img = qrcode.make(url)
    out_path = os.path.join(GENERATED_FOLDER, output_filename)
    img.save(out_path)
    return out_path

# ---------- Flask routes ----------
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'qrfile' not in request.files:
            return render_template('index.html', error='לא נבחר קובץ')
        file = request.files['qrfile']
        if file.filename == '':
            return render_template('index.html', error='לא נבחר קובץ')
        if not allowed_file(file.filename):
            return render_template('index.html', error='סוג קובץ לא נתמך (רק PNG/JPG)')

        filename = secure_filename(file.filename)
        save_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}_{filename}")
        file.save(save_path)

        original_text = decode_qr_from_image(save_path)
        if not original_text:
            return render_template('index.html', error='לא נמצא QR תקף בתמונה. ודא שהתמונה ברורה.')

        # יצירת טוקן ושמירה ב-SQLite
        token = str(uuid.uuid4())
        save_token(token, original_text)

        one_time_path = f"qr/{token}"
        one_time_full = request.host_url.rstrip('/') + '/' + one_time_path

        img_name = f"{token}.png"
        generate_one_time_qr(one_time_full, img_name)

        return render_template('result.html', one_time_full=one_time_full, img_name=img_name, original=original_text)

    return render_template('index.html')

@app.route('/static/generated/<filename>')
def serve_generated(filename):
    return send_from_directory(GENERATED_FOLDER, filename)

@app.route('/qr/<token>')
def one_time(token):
    rec = get_record(token)
    if not rec:
        return render_template('used.html', message='הקישור לא קיים.')
    _, original, used = rec
    if used:
        return render_template('used.html', message='הקוד כבר שומש ואינו תקף יותר.')

    # סמן כשומש
    mark_used(token)

    # אם ה-original הוא כתובת URL (http/https) - נעשה redirect ישיר
    if isinstance(original, str) and (original.startswith('http://') or original.startswith('https://')):
        return redirect(original)
    # אחרת - נציג את הטקסט המקורי בדף
    return render_template('result.html', one_time_full=None, img_name=None, original=original, direct_view=True)

# ---------- Init ----------
if __name__ == '__main__':
    init_db()
    # מחברות ל-host כללי עבור הפעלה בענן
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
