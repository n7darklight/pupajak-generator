import os
from flask import Flask, render_template, request, session, redirect, url_for, flash
import re
import random
import string
import smtplib
from email.message import EmailMessage
import google.generativeai as genai
# Supabase integration
from supabase import create_client, Client
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from flask import Blueprint

# --- CHANGE THIS LINE ---
# Remove the url_prefix. The middleware will handle the pathing.
app_bp = Blueprint('app_bp', __name__)

load_dotenv()

# Supabase setup
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


# This is the main app object Vercel will look for.
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'changeme')

# Register the blueprint to the main app.
# Flask's url_for will now generate relative paths like '/login' instead of '/puspajak-gen/login'
app.register_blueprint(app_bp)


# In-memory stores (replace with DB in production)
TOKENS = {}
USAGE = {}


# Disposable email domains (partial list, expand as needed)
DISPOSABLE_DOMAINS = set([
    'mailinator.com', 'tempmail.com', '10minutemail.com', 'guerrillamail.com', 'yopmail.com',
    'trashmail.com', 'fakeinbox.com', 'getnada.com', 'sharklasers.com', 'maildrop.cc',
])

CONTACT_EMAIL = os.getenv('CONTACT_EMAIL', 'your@email.com')

# --- Email validation ---
def is_valid_email(email):
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    if not re.match(pattern, email):
        return False
    domain = email.split('@')[-1].lower()
    if domain in DISPOSABLE_DOMAINS:
        return False
    return True

# --- Send token via email (configure SMTP) ---
def send_token(email, token):
    msg = EmailMessage()
    msg['Subject'] = 'Your Access Token'
    msg['From'] = CONTACT_EMAIL
    msg['To'] = email
    msg.set_content(f"Your access token: {token}")
    smtp_server = os.getenv('SMTP_SERVER')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    smtp_user = os.getenv('SMTP_USER')
    smtp_password = os.getenv('SMTP_PASSWORD')
    if not all([smtp_server, smtp_user, smtp_password]):
        raise Exception('SMTP configuration is incomplete in .env')
    with smtplib.SMTP(smtp_server, smtp_port) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)

# --- Token generation ---
def generate_token(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# --- Login required decorator ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'email' not in session or 'token' not in session:
            return redirect(url_for('app_bp.index'))
        return f(*args, **kwargs)
    return decorated

# --- Routes ---
# This is now the root of the blueprint, which will be served from /puspajak-gen/
@app_bp.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not is_valid_email(email):
            flash('Email tidak valid atau terdeteksi sebagai email sekali pakai.', 'danger')
            return render_template('index.html')
        # Check if user exists in poet_data
        user = None
        if supabase:
            res = supabase.table('poet_data').select('*').eq('email', email).execute()
            if res.data:
                user = res.data[0]
        if user:
            token = user['token']
        else:
            token = generate_token()
            # Insert new user with 10 credits
            if supabase:
                supabase.table('poet_data').insert({
                    'email': email,
                    'token': token,
                    'credit': 10,
                    'created_at': datetime.utcnow().isoformat()
                }).execute()
        try:
            send_token(email, token)
            flash('Token telah dikirim ke email Anda.', 'success')
        except Exception as e:
            flash('Gagal mengirim email. Hubungi admin.', 'danger')
        return render_template('index.html')
    return render_template('index.html')

@app_bp.route('/login', methods=['POST'])
def login():
    email = request.form.get('email', '').strip().lower()
    token = request.form.get('token', '').strip()
    # Validate token from Supabase (case-sensitive, no extra whitespace)
    user = None
    if supabase:
        # Fetch user by email only, then compare token in Python for full control
        res = supabase.table('poet_data').select('*').eq('email', email).execute()
        if res.data:
            user = res.data[0]
    if user:
        db_token = user['token'].strip()
        print(f"[DEBUG] Login: email={email}, input_token={token}, db_token={db_token}")
        if token == db_token:
            session['email'] = email
            session['token'] = db_token
            session['user_id'] = user['id']
            print(f"[DEBUG] Login success, session: {dict(session)}")
            flash(f"[DEBUG] Login success, session: {dict(session)}", 'info')
            return redirect(url_for('app_bp.generate'))
        else:
            print(f"[DEBUG] Token mismatch: input={token}, db={db_token}")
            flash(f'Token tidak cocok. (Input: "{token}", DB: "{db_token}")', 'danger')
    else:
        print(f"[DEBUG] Email not found: {email}")
        flash('Email tidak ditemukan.', 'danger')
    print(f"[DEBUG] Session after login: {dict(session)}")
    return redirect(url_for('app_bp.index'))

@app_bp.route('/generate', methods=['GET', 'POST'])
@login_required
def generate():
    print(f"[DEBUG] Session at /generate: {dict(session)}")
    email = session.get('email')
    user_id = session.get('user_id')
    if not email or not user_id:
        flash(f"[DEBUG] Session missing at /generate: {dict(session)}", 'danger')
        return redirect(url_for('app_bp.index'))
    # Get user credit from Supabase
    credit = 0
    if supabase and user_id:
        res = supabase.table('poet_data').select('credit').eq('id', user_id).execute()
        if res.data:
            credit = res.data[0]['credit']
    if credit <= 0:
        return render_template('quota.html', contact=CONTACT_EMAIL)
    result = None
    if request.method == 'POST':
        genre = request.form.get('genre', 'puisi')
        title = request.form.get('title', '').strip()
        if not title:
            flash('Masukkan judul atau tema.', 'danger')
        else:
            # --- Improved prompt for clean output ---
            prompt = (
                f"Buatkan {genre} berbahasa Indonesia dengan tema: '{title}'.\n"
                f"Tampilkan hanya isi {genre} tanpa judul, tanpa penjelasan, tanpa kata pengantar, dan tanpa format markdown.\n"
                f"Jangan ulangi judul atau tema dalam hasil.\n"
            )
            api_key = os.getenv('GOOGLE_AI_API_KEY')
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemma-3-27b-it')
                response = model.generate_content(prompt)
                raw_result = getattr(response, 'text', None) or str(response)
                # Remove only leading explanation/intro lines, but keep poem formatting and blank lines
                lines = raw_result.splitlines()
                filtered = []
                skipping = True
                for line in lines:
                    l = line.strip().lower()
                    # Skip lines that are explanation/intro, but stop skipping at first likely poem line
                    if skipping and (
                        l == '' or
                        title.lower() in l or
                        'tema' in l or
                        genre in l or
                        l.startswith('judul') or
                        l.startswith('berikut') or
                        l.startswith('tentu') or
                        l.startswith('inilah') or
                        l.startswith('ini')
                    ):
                        continue
                    skipping = False
                    filtered.append(line.rstrip())
                # Remove trailing blank lines
                while filtered and filtered[-1].strip() == '':
                    filtered.pop()
                # Compose result: title, blank line, then poem (for display)
                poem_text = '\n'.join(filtered)
                result = f"{title}\n\n{poem_text}" if poem_text else title
                # Save only the poem content (no title, no blank line) in db
                db_text = poem_text
                if supabase and user_id:
                    supabase.table('poet_creation_data').insert({
                        'poet': user_id,
                        'title': title,
                        'text': db_text,
                        'type': genre,
                        'created_at': datetime.utcnow().isoformat()
                    }).execute()
                    # Decrement credit
                    supabase.table('poet_data').update({'credit': credit-1}).eq('id', user_id).execute()
                    credit -= 1
            except Exception as e:
                result = f"Exception saat menghubungi Gemini/Gemma API: {e}"
    return render_template('generate.html', result=result, remaining=credit)
@app_bp.route('/history')
@login_required
def history():
    user_id = session.get('user_id')
    history = []
    if supabase and user_id:
        res = supabase.table('poet_creation_data').select('*').eq('poet', user_id).order('created_at', desc=True).limit(20).execute()
        if res.data:
            history = res.data
    return render_template('history.html', history=history)

@app_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('app_bp.index'))

# This block is for local development and is ignored by Vercel
if __name__ == '__main__':
    app.run(debug=True)
