from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid, hashlib, os

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ─── Models ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id          = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username    = db.Column(db.String(50), unique=True, nullable=False)
    email       = db.Column(db.String(120), unique=True, nullable=False)
    password    = db.Column(db.String(256), nullable=False)
    anonymous   = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

class Doctor(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    specialty    = db.Column(db.String(100), nullable=False)
    category     = db.Column(db.String(50), nullable=False)   # menstrual / sexual / mental / general
    experience   = db.Column(db.Integer, default=0)
    rating       = db.Column(db.Float, default=4.5)
    avatar_color = db.Column(db.String(20), default='#e8b4c8')
    available    = db.Column(db.Boolean, default=True)

class Message(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    room_id     = db.Column(db.String(100), nullable=False)
    sender      = db.Column(db.String(50), nullable=False)   # 'user' or 'doctor'
    content     = db.Column(db.Text, nullable=False)
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def seed_doctors():
    if Doctor.query.count() == 0:
        doctors = [
            Doctor(name="Dr. Priya Sharma",   specialty="Gynaecologist & Obstetrician", category="menstrual",  experience=12, rating=4.9, avatar_color="#f4a7b9"),
            Doctor(name="Dr. Ananya Rao",     specialty="Sexual Health Counsellor",     category="sexual",     experience=8,  rating=4.7, avatar_color="#b5c9a8"),
            Doctor(name="Dr. Meera Pillai",   specialty="Psychiatrist & Therapist",     category="mental",     experience=15, rating=4.8, avatar_color="#c4b5d4"),
            Doctor(name="Dr. Sunita Verma",   specialty="General Physician",            category="general",    experience=10, rating=4.6, avatar_color="#f6c89f"),
            Doctor(name="Dr. Kavita Nair",    specialty="Reproductive Endocrinologist", category="menstrual",  experience=9,  rating=4.7, avatar_color="#a8c4c4"),
            Doctor(name="Dr. Ritu Malhotra",  specialty="Clinical Psychologist",        category="mental",     experience=7,  rating=4.8, avatar_color="#d4b5b5"),
        ]
        db.session.add_all(doctors)
        db.session.commit()

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(email=email, password=hash_password(password)).first()
        if user:
            session['user_id']   = user.id
            session['username']  = user.username
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid credentials. Please try again.")
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    email     = request.form.get('email', '').strip()
    password  = request.form.get('password', '').strip()
    anonymous = request.form.get('anonymous') == 'on'
    username  = f"bloom_{uuid.uuid4().hex[:6]}" if anonymous else request.form.get('username', '').strip()

    if User.query.filter_by(email=email).first():
        return render_template('login.html', error="Email already registered.", tab='register')
    if not anonymous and User.query.filter_by(username=username).first():
        return render_template('login.html', error="Username taken.", tab='register')

    user = User(username=username, email=email, password=hash_password(password), anonymous=anonymous)
    db.session.add(user)
    db.session.commit()
    session['user_id']  = user.id
    session['username'] = user.username
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    doctors   = Doctor.query.all()
    username  = session.get('username')
    # fetch rooms user has chatted in
    rooms = db.session.query(Message.room_id).filter(
        Message.room_id.like(f"{session['user_id']}_%")
    ).distinct().all()
    history = []
    for (room_id,) in rooms:
        last_msg = Message.query.filter_by(room_id=room_id).order_by(Message.timestamp.desc()).first()
        doc_id   = int(room_id.split('_')[1])
        doc      = Doctor.query.get(doc_id)
        if doc and last_msg:
            history.append({'doctor': doc, 'last_msg': last_msg, 'room_id': room_id})
    return render_template('dashboard.html', doctors=doctors, username=username, history=history)

@app.route('/chat/<int:doctor_id>')
@login_required
def chat(doctor_id):
    doctor  = Doctor.query.get_or_404(doctor_id)
    room_id = f"{session['user_id']}_{doctor_id}"
    messages = Message.query.filter_by(room_id=room_id).order_by(Message.timestamp).all()
    return render_template('chat.html', doctor=doctor, messages=messages,
                           room_id=room_id, username=session.get('username'))

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    data    = request.get_json()
    room_id = data.get('room_id')
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'status': 'error', 'message': 'Empty message'}), 400

    msg = Message(room_id=room_id, sender='user', content=content)
    db.session.add(msg)
    db.session.commit()

    # Simple auto-reply from doctor
    auto_replies = [
        "Thank you for reaching out. I'm here to help — could you tell me more?",
        "I understand. This is a safe space. Please share as much as you're comfortable with.",
        "That's completely normal. Let's work through this together.",
        "I appreciate you trusting me with this. Can you describe how long you've been experiencing this?",
    ]
    import random
    reply = Message(room_id=room_id, sender='doctor', content=random.choice(auto_replies))
    db.session.add(reply)
    db.session.commit()

    return jsonify({
        'status': 'ok',
        'user_msg': {'content': msg.content, 'time': msg.timestamp.strftime('%I:%M %p')},
        'doctor_msg': {'content': reply.content, 'time': reply.timestamp.strftime('%I:%M %p')}
    })

@app.route('/delete_chat/<room_id>', methods=['POST'])
@login_required
def delete_chat(room_id):
    if room_id.startswith(session['user_id']):
        Message.query.filter_by(room_id=room_id).delete()
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── Init ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_doctors()
    app.run(debug=True, port=5000)
    """
***
```markdown
OTP / email verification login
- [ ] Real-time chat with WebSockets (Flask-SocketIO)
- [ ] Video consultations (WebRTC)
- [ ] Doctor verification admin panel
- [ ] Push notifications
- [ ] Migrate to PostgreSQL for production
- [ ] End-to-end encryption with proper key exchange

```###***"""