from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message as MailMessage
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime, timedelta, date
from functools import wraps
import uuid, hashlib, os, random, string
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAIL_SERVER']         = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT']           = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']        = True
app.config['MAIL_USE_SSL']        = False
app.config['MAIL_USERNAME']       = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD']       = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

db       = SQLAlchemy(app)
mail     = Mail(app)
socketio = SocketIO(app, manage_session=False, async_mode='threading')

OTP_EXPIRY_MINUTES = 10
OTP_LENGTH         = 6

# Live socket tracking for push notifications
user_sockets   = {}   # {user_id: sid}
doctor_sockets = {}   # {doctor_id_str: sid}

# ─── Models ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id          = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username    = db.Column(db.String(50), unique=True, nullable=False)
    email       = db.Column(db.String(120), unique=True, nullable=False)
    password    = db.Column(db.String(256), nullable=False)
    anonymous   = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    public_key  = db.Column(db.Text, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

class OTPCode(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(120), nullable=False, index=True)
    code_hash  = db.Column(db.String(64), nullable=False)
    purpose    = db.Column(db.String(20), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used       = db.Column(db.Boolean, default=False)

class Doctor(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(100), nullable=False)
    specialty     = db.Column(db.String(100), nullable=False)
    category      = db.Column(db.String(50), nullable=False)
    experience    = db.Column(db.Integer, default=0)
    rating        = db.Column(db.Float, default=4.5)
    avatar_color  = db.Column(db.String(20), default='#e8b4c8')
    available     = db.Column(db.Boolean, default=True)
    is_verified   = db.Column(db.Boolean, default=False)
    email         = db.Column(db.String(120), unique=True, nullable=True)
    password      = db.Column(db.String(256), nullable=True)
    public_key    = db.Column(db.Text, nullable=True)
    total_ratings = db.Column(db.Integer, default=0)
    rating_sum    = db.Column(db.Float, default=0.0)

class Appointment(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    doctor_id    = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False)
    user_id      = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    note         = db.Column(db.Text, nullable=True)
    status       = db.Column(db.String(20), default='pending')
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    doctor       = db.relationship('Doctor', backref='appointments')
    user         = db.relationship('User', backref='appointments')

class ChatMessage(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    room_id      = db.Column(db.String(100), nullable=False, index=True)
    sender       = db.Column(db.String(50), nullable=False)
    content      = db.Column(db.Text, nullable=False)
    is_encrypted = db.Column(db.Boolean, default=False)
    timestamp    = db.Column(db.DateTime, default=datetime.utcnow)

class VideoCallRequest(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    room_id    = db.Column(db.String(100), nullable=False)
    patient_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    doctor_id  = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False)
    status     = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    patient    = db.relationship('User', backref='video_calls')
    doctor     = db.relationship('Doctor', backref='video_calls')

class PeriodLog(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    start_date   = db.Column(db.Date, nullable=False)
    end_date     = db.Column(db.Date, nullable=True)
    flow         = db.Column(db.String(20), default='medium')
    symptoms     = db.Column(db.String(300), nullable=True)
    mood         = db.Column(db.String(50), nullable=True)
    notes        = db.Column(db.Text, nullable=True)
    cycle_length = db.Column(db.Integer, nullable=True)
    user         = db.relationship('User', backref='period_logs')

class Admin(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def hash_password(p): return hashlib.sha256(p.encode()).hexdigest()
def hash_otp(o):      return hashlib.sha256(o.encode()).hexdigest()
def generate_otp():   return ''.join(random.choices(string.digits, k=OTP_LENGTH))

def send_otp_email(to, otp, purpose):
    action = "complete your registration" if purpose == 'register' else "log in"
    mail.send(MailMessage("Your Bloom verification code", recipients=[to],
        body=f"Your code to {action}:\n\n  {otp}\n\nExpires in {OTP_EXPIRY_MINUTES} minutes."))

def upsert_otp(email, otp, purpose):
    OTPCode.query.filter_by(email=email, purpose=purpose).delete()
    db.session.add(OTPCode(email=email, code_hash=hash_otp(otp), purpose=purpose,
        expires_at=datetime.utcnow()+timedelta(minutes=OTP_EXPIRY_MINUTES)))
    db.session.commit()

def verify_otp_code(email, otp, purpose):
    r = OTPCode.query.filter_by(email=email, purpose=purpose, used=False)\
                     .order_by(OTPCode.expires_at.desc()).first()
    if not r: return False, "No active OTP found."
    if datetime.utcnow() > r.expires_at: return False, "OTP expired."
    if r.code_hash != hash_otp(otp): return False, "Incorrect code."
    r.used = True; db.session.commit(); return True, ''

def _send_otp(email, purpose):
    otp = generate_otp(); upsert_otp(email, otp, purpose)
    try: send_otp_email(email, otp, purpose)
    except: print(f"\n[DEV] OTP {email} ({purpose}): {otp}\n")

def login_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*a,**k)
    return d

def doctor_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'doctor_id' not in session: return redirect(url_for('doctor_login'))
        return f(*a,**k)
    return d

def admin_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'admin_id' not in session: return redirect(url_for('admin_login'))
        return f(*a,**k)
    return d

# ─── Patient Auth ─────────────────────────────────────────────────────────────

@app.route('/')
def index(): return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        pwd   = request.form.get('password','').strip()
        user  = User.query.filter_by(email=email, password=hash_password(pwd)).first()
        if not user: return render_template('login.html', error="Invalid credentials.")
        if not user.is_verified:
            _send_otp(email,'register'); session.update({'pending_email':email,'pending_purpose':'register'})
            return redirect(url_for('verify_otp_page'))
        otp = generate_otp(); upsert_otp(email, otp, 'login')
        try: send_otp_email(email, otp, 'login')
        except: print(f"\n[DEV] Login OTP {email}: {otp}\n")
        session.update({'pending_email':email,'pending_purpose':'login'})
        return redirect(url_for('verify_otp_page'))
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    email = request.form.get('email','').strip().lower()
    ex    = User.query.filter_by(email=email).first()
    if ex and ex.is_verified: return render_template('login.html', error="Email already registered.", tab='register')
    _send_otp(email,'register'); session.update({'pending_email':email,'pending_purpose':'register'})
    return redirect(url_for('verify_otp_page'))

@app.route('/verify-otp', methods=['GET','POST'])
def verify_otp_page():
    email=session.get('pending_email'); purpose=session.get('pending_purpose')
    if not email or not purpose: return redirect(url_for('login'))
    if request.method == 'POST':
        if request.is_json: _send_otp(email,purpose); return jsonify({'status':'ok'})
        otp_input = ''.join([request.form.get(f'otp{i}','') for i in range(1,OTP_LENGTH+1)]).strip()
        ok, reason = verify_otp_code(email, otp_input, purpose)
        if not ok: return render_template('verify_otp.html', email=email, error=reason)
        # Clear pending session keys
        session.pop('pending_email', None)
        session.pop('pending_purpose', None)
        if purpose == 'register':
            # New user — no account yet, go to setup page to create one
            session['setup_email'] = email
            return redirect(url_for('setup_username'))
        # Login — user already exists
        user = User.query.filter_by(email=email).first()
        if not user: return redirect(url_for('login'))
        session['user_id'] = user.id; session['username'] = user.username
        return redirect(url_for('dashboard'))
    return render_template('verify_otp.html', email=email)

@app.route('/setup-username', methods=['GET','POST'])
def setup_username():
    email = session.get('setup_email')
    if not email: return redirect(url_for('login'))
    if request.method == 'POST':
        uname = request.form.get('username','').strip()
        pwd   = request.form.get('password','').strip()
        if not uname or not pwd: return render_template('setup_username.html', email=email, error="Username and password required.")
        if User.query.filter_by(username=uname).first(): return render_template('setup_username.html', email=email, error="Username already taken.")
        user = User.query.filter_by(email=email).first()
        if user: user.username=uname; user.password=hash_password(pwd); user.is_verified=True; db.session.commit()
        else: db.session.add(User(username=uname,email=email,password=hash_password(pwd),is_verified=True)); db.session.commit()
        session.pop('setup_email',None)
        user = User.query.filter_by(email=email).first()
        session['user_id']=user.id; session['username']=user.username
        return redirect(url_for('dashboard'))
    return render_template('setup_username.html', email=email)

@app.route('/resend-otp', methods=['POST'])
def resend_otp():
    e=session.get('pending_email'); p=session.get('pending_purpose')
    if not e or not p: return jsonify({'status':'error','message':'Session expired.'}),400
    _send_otp(e,p); return jsonify({'status':'ok','message':f'Code sent to {e}.'})

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

# ─── Patient Routes ────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    doctors = Doctor.query.filter_by(is_verified=True).all()
    rooms   = db.session.query(ChatMessage.room_id).filter(
        ChatMessage.room_id.like(f"{session['user_id']}_%")).distinct().all()
    history = []
    for (rid,) in rooms:
        lm  = ChatMessage.query.filter_by(room_id=rid).order_by(ChatMessage.timestamp.desc()).first()
        doc = Doctor.query.get(int(rid.split('_')[1]))
        if doc and lm: history.append({'doctor':doc,'last_msg':lm,'room_id':rid})
    appts       = Appointment.query.filter_by(user_id=session['user_id']).order_by(Appointment.scheduled_at.desc()).all()
    last_period = PeriodLog.query.filter_by(user_id=session['user_id']).order_by(PeriodLog.start_date.desc()).first()
    return render_template('dashboard.html', doctors=doctors, username=session.get('username'),
                           history=history, appointments=appts, last_period=last_period)

@app.route('/chat/<int:doctor_id>')
@login_required
def chat(doctor_id):
    doctor   = Doctor.query.get_or_404(doctor_id)
    room_id  = f"{session['user_id']}_{doctor_id}"
    messages = ChatMessage.query.filter_by(room_id=room_id).order_by(ChatMessage.timestamp).all()
    return render_template('chat.html', doctor=doctor, messages=messages,
                           room_id=room_id, username=session.get('username'))

@app.route('/delete_chat/<room_id>', methods=['POST'])
@login_required
def delete_chat(room_id):
    if room_id.startswith(session['user_id']):
        ChatMessage.query.filter_by(room_id=room_id).delete(); db.session.commit()
    return redirect(url_for('dashboard'))

# ─── Period Tracker ────────────────────────────────────────────────────────────

@app.route('/period-tracker')
@login_required
def period_tracker():
    logs = PeriodLog.query.filter_by(user_id=session['user_id']).order_by(PeriodLog.start_date.desc()).all()
    return render_template('period_tracker.html', logs=logs, username=session.get('username'))

@app.route('/api/period/log', methods=['POST'])
@login_required
def log_period():
    data       = request.get_json()
    uid        = session['user_id']
    start      = datetime.strptime(data['start_date'],'%Y-%m-%d').date()
    prev       = PeriodLog.query.filter_by(user_id=uid).order_by(PeriodLog.start_date.desc()).first()
    cycle_len  = (start - prev.start_date).days if prev else None
    log = PeriodLog(user_id=uid, start_date=start,
        end_date=datetime.strptime(data['end_date'],'%Y-%m-%d').date() if data.get('end_date') else None,
        flow=data.get('flow','medium'), symptoms=','.join(data.get('symptoms',[])),
        mood=data.get('mood',''), notes=data.get('notes',''), cycle_length=cycle_len)
    db.session.add(log); db.session.commit()
    return jsonify({'status':'ok','id':log.id,'cycle_length':cycle_len})

@app.route('/api/period/logs')
@login_required
def get_period_logs():
    logs = PeriodLog.query.filter_by(user_id=session['user_id']).order_by(PeriodLog.start_date.asc()).all()
    return jsonify([{'id':l.id,'start_date':l.start_date.isoformat(),
        'end_date':l.end_date.isoformat() if l.end_date else None,
        'flow':l.flow,'symptoms':l.symptoms.split(',') if l.symptoms else [],
        'mood':l.mood,'notes':l.notes,'cycle_length':l.cycle_length} for l in logs])

@app.route('/api/period/delete/<int:lid>', methods=['DELETE'])
@login_required
def delete_period_log(lid):
    l = PeriodLog.query.filter_by(id=lid, user_id=session['user_id']).first_or_404()
    db.session.delete(l); db.session.commit(); return jsonify({'status':'ok'})

# ─── Appointments (Patient) ────────────────────────────────────────────────────

@app.route('/api/appointments/request', methods=['POST'])
@login_required
def request_appointment():
    data = request.get_json()
    doc  = Doctor.query.get(data['doctor_id'])
    if not doc: return jsonify({'error':'Doctor not found'}),404
    appt = Appointment(doctor_id=data['doctor_id'], user_id=session['user_id'],
        scheduled_at=datetime.strptime(data['scheduled_at'],'%Y-%m-%dT%H:%M'),
        note=data.get('note',''), status='pending')
    db.session.add(appt); db.session.commit()
    doc_sid = doctor_sockets.get(str(data['doctor_id']))
    if doc_sid:
        socketio.emit('new_appointment_request', {
            'appointment_id': appt.id, 'patient': session.get('username'),
            'datetime': appt.scheduled_at.strftime('%b %d, %Y at %I:%M %p'), 'note': appt.note,
        }, room=doc_sid)
    return jsonify({'status':'ok','id':appt.id})

# ─── Video Call ────────────────────────────────────────────────────────────────

@app.route('/video/<room_id>')
def video_call(room_id):
    parts = room_id.split('_')
    if len(parts) != 2: return redirect(url_for('dashboard'))
    uid, did = parts
    is_caller = request.args.get('caller') == 'true'
    if session.get('user_id') == uid:
        doc = Doctor.query.get_or_404(int(did))
        return render_template('video_call.html', room_id=room_id, my_role='user',
            is_caller=is_caller, peer_name=doc.name, peer_role=doc.specialty,
            peer_color=doc.avatar_color, peer_initial=doc.name.split()[1][0],
            back_url=url_for('chat', doctor_id=int(did)))
    if session.get('doctor_id') == int(did):
        usr = User.query.get_or_404(uid)
        return render_template('video_call.html', room_id=room_id, my_role='doctor',
            is_caller=is_caller, peer_name=usr.username, peer_role='Patient',
            peer_color='#b5c9a8', peer_initial=usr.username[0].upper(),
            back_url=url_for('doctor_chat', room_id=room_id))
    return redirect(url_for('login'))

# ─── E2E Keys & Rating ────────────────────────────────────────────────────────

@app.route('/api/save-public-key', methods=['POST'])
@login_required
def save_public_key():
    u = User.query.get(session['user_id'])
    if u: u.public_key = request.get_json().get('public_key'); db.session.commit()
    return jsonify({'status':'ok'})

@app.route('/api/public-key/<room_id>')
@login_required
def get_public_key(room_id):
    parts = room_id.split('_')
    if len(parts)!=2: return jsonify({'error':'invalid'}),400
    uid, did = parts
    if session.get('user_id')==uid:
        doc = Doctor.query.get(did)
        return jsonify({'public_key': doc.public_key if doc else None})
    if str(session.get('doctor_id'))==did:
        usr = User.query.get(uid)
        return jsonify({'public_key': usr.public_key if usr else None})
    return jsonify({'error':'unauthorized'}),403

@app.route('/api/rate-doctor', methods=['POST'])
@login_required
def rate_doctor():
    data=request.get_json(); doc=Doctor.query.get(data['doctor_id'])
    if doc: doc.rating_sum+=float(data['rating']); doc.total_ratings+=1; doc.rating=round(doc.rating_sum/doc.total_ratings,1); db.session.commit()
    return jsonify({'status':'ok','new_rating':doc.rating})

# ─── Doctor Auth & Panel ───────────────────────────────────────────────────────

@app.route('/doctor/login', methods=['GET','POST'])
def doctor_login():
    if request.method=='POST':
        doc = Doctor.query.filter_by(email=request.form.get('email','').strip().lower(),
                                     password=hash_password(request.form.get('password','').strip())).first()
        if not doc: return render_template('doctor_login.html', error="Invalid credentials.")
        if not doc.is_verified: return render_template('doctor_login.html', error="Pending admin verification.")
        session['doctor_id']=doc.id; session['doctor_name']=doc.name
        return redirect(url_for('doctor_dashboard'))
    return render_template('doctor_login.html')

@app.route('/doctor/logout')
def doctor_logout(): session.pop('doctor_id',None); session.pop('doctor_name',None); return redirect(url_for('doctor_login'))

@app.route('/doctor/dashboard')
@doctor_required
def doctor_dashboard():
    doctor = Doctor.query.get(session['doctor_id'])
    did    = session['doctor_id']
    rooms  = db.session.query(ChatMessage.room_id).filter(ChatMessage.room_id.like(f"%_{did}")).distinct().all()
    chats  = []
    for (rid,) in rooms:
        lm   = ChatMessage.query.filter_by(room_id=rid).order_by(ChatMessage.timestamp.desc()).first()
        user = User.query.get(rid.split('_')[0])
        if user and lm:
            period_logs = PeriodLog.query.filter_by(user_id=user.id).order_by(PeriodLog.start_date.desc()).limit(5).all()
            chats.append({'user':user,'last_msg':lm,'room_id':rid,'period_logs':period_logs})
    appts         = Appointment.query.filter_by(doctor_id=did).order_by(Appointment.scheduled_at).all()
    pending_calls = VideoCallRequest.query.filter_by(doctor_id=did, status='pending').all()
    return render_template('doctor_dashboard.html', doctor=doctor, chats=chats,
                           appointments=appts, pending_calls=pending_calls)

@app.route('/doctor/chat/<room_id>')
@doctor_required
def doctor_chat(room_id):
    if not room_id.endswith(f"_{session['doctor_id']}"): return redirect(url_for('doctor_dashboard'))
    user=User.query.get_or_404(room_id.split('_')[0]); doctor=Doctor.query.get(session['doctor_id'])
    msgs=ChatMessage.query.filter_by(room_id=room_id).order_by(ChatMessage.timestamp).all()
    return render_template('doctor_chat.html', user=user, doctor=doctor, messages=msgs, room_id=room_id)

@app.route('/doctor/availability', methods=['POST'])
@doctor_required
def doctor_availability():
    doc=Doctor.query.get(session['doctor_id']); doc.available=not doc.available; db.session.commit()
    return jsonify({'available':doc.available})

@app.route('/doctor/save-public-key', methods=['POST'])
@doctor_required
def doctor_save_public_key():
    doc=Doctor.query.get(session['doctor_id'])
    if doc: doc.public_key=request.get_json().get('public_key'); db.session.commit()
    return jsonify({'status':'ok'})

@app.route('/doctor/appointment/<int:aid>/status', methods=['POST'])
@doctor_required
def update_appointment(aid):
    appt=Appointment.query.get_or_404(aid)
    if appt.doctor_id!=session['doctor_id']: return jsonify({'error':'unauthorized'}),403
    appt.status=request.get_json().get('status',appt.status); db.session.commit()
    sid=user_sockets.get(appt.user_id)
    if sid: socketio.emit('appointment_status_update',{'appointment_id':appt.id,'status':appt.status,
        'doctor_name':appt.doctor.name,'datetime':appt.scheduled_at.strftime('%b %d at %I:%M %p')},room=sid)
    return jsonify({'status':appt.status})

# ─── Admin ─────────────────────────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        adm=Admin.query.filter_by(username=request.form.get('username','').strip(),
                                  password=hash_password(request.form.get('password','').strip())).first()
        if not adm: return render_template('admin_login.html', error="Invalid credentials.")
        session['admin_id']=adm.id; return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout(): session.pop('admin_id',None); return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    stats={'total_users':User.query.filter_by(is_verified=True).count(),
           'total_doctors':Doctor.query.count(),'verified_doctors':Doctor.query.filter_by(is_verified=True).count(),
           'pending_doctors':Doctor.query.filter_by(is_verified=False).count(),
           'total_messages':ChatMessage.query.count(),'total_appointments':Appointment.query.count(),
           'total_calls':VideoCallRequest.query.count()}
    return render_template('admin_dashboard.html', stats=stats,
        doctors=Doctor.query.order_by(Doctor.is_verified).all(),
        users=User.query.filter_by(is_verified=True).order_by(User.created_at.desc()).limit(20).all())

@app.route('/admin/doctor/verify/<int:did>', methods=['POST'])
@admin_required
def admin_verify_doctor(did):
    d=Doctor.query.get_or_404(did); d.is_verified=True; db.session.commit()
    return jsonify({'status':'ok','name':d.name})

@app.route('/admin/doctor/delete/<int:did>', methods=['POST'])
@admin_required
def admin_delete_doctor(did):
    db.session.delete(Doctor.query.get_or_404(did)); db.session.commit()
    return jsonify({'status':'ok'})

@app.route('/admin/doctor/add', methods=['POST'])
@admin_required
def admin_add_doctor():
    data=request.get_json()
    if Doctor.query.filter_by(email=data['email']).first(): return jsonify({'error':'Email exists'}),400
    db.session.add(Doctor(name=data['name'],specialty=data['specialty'],category=data['category'],
        experience=int(data.get('experience',0)),email=data['email'],password=hash_password(data['password']),
        avatar_color=data.get('avatar_color','#e8b4c8'),is_verified=True)); db.session.commit()
    return jsonify({'status':'ok'})

# ─── Socket: Connect / Disconnect ─────────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    uid=session.get('user_id'); did=session.get('doctor_id')
    if uid: user_sockets[uid]=request.sid
    if did: doctor_sockets[str(did)]=request.sid

@socketio.on('disconnect')
def on_disconnect():
    uid=session.get('user_id'); did=session.get('doctor_id')
    if uid: user_sockets.pop(uid,None)
    if did: doctor_sockets.pop(str(did),None)

# ─── Socket: Chat ──────────────────────────────────────────────────────────────

@socketio.on('join_chat')
def on_join_chat(data):
    rid=data.get('room_id',''); uid=session.get('user_id'); did=session.get('doctor_id')
    parts=rid.split('_')
    if len(parts)!=2: emit('error',{'message':'Invalid room.'}); return
    u,d=parts
    if (uid and u==uid) or (did and d==str(did)): join_room(rid); emit('joined',{'room_id':rid})
    else: emit('error',{'message':'Unauthorized.'})

@socketio.on('send_message')
def on_send_message(data):
    rid=data.get('room_id',''); content=(data.get('content') or '').strip()
    enc=data.get('is_encrypted',False); uid=session.get('user_id'); did=session.get('doctor_id')
    if not content: emit('error',{'message':'Message cannot be empty'}); return
    if len(content) > 5000: emit('error',{'message':'Message too long (max 5000 characters)'}); return
    parts=rid.split('_')
    if len(parts)!=2: emit('error',{'message':'Invalid chat room'}); return
    u,d=parts
    if uid and u==uid: sender='user'; display=session.get('username','Patient')
    elif did and d==str(did): sender='doctor'; display=session.get('doctor_name','Doctor')
    else: emit('error',{'message':'Unauthorized'}); return
    try:
        msg=ChatMessage(room_id=rid,sender=sender,content=content,is_encrypted=enc)
        db.session.add(msg); db.session.commit()
        emit('new_message',{'sender':sender,'display_name':display,'content':content,'is_encrypted':enc,
            'timestamp':msg.timestamp.strftime('%I:%M %p')},room=rid)
    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Message send failed: {e}")
        emit('error',{'message':'Failed to send message. Please try again.'})

@socketio.on('typing')
def on_typing(data):
    role='doctor' if session.get('doctor_id') else 'user'
    emit('peer_typing',{'typing':data.get('typing',False),'role':role},
         room=data.get('room_id',''),include_self=False)

@socketio.on('leave_chat')
def on_leave_chat(data): leave_room(data.get('room_id',''))

# ─── Socket: Video Call Signaling ─────────────────────────────────────────────

@socketio.on('request_video_call')
def on_request_video_call(data):
    rid=data.get('room_id',''); parts=rid.split('_')
    if len(parts)!=2: return
    uid,did=parts; user_id=session.get('user_id')
    if not user_id or uid!=user_id: return
    call=VideoCallRequest(room_id=rid,patient_id=user_id,doctor_id=int(did),status='pending')
    db.session.add(call); db.session.commit()
    doc_sid=doctor_sockets.get(did)
    pat=User.query.get(user_id)
    if doc_sid:
        socketio.emit('incoming_call_request',{'call_id':call.id,'room_id':rid,
            'patient':pat.username if pat else 'Patient','video_url':f'/video/{rid}'},room=doc_sid)
        emit('call_request_sent',{'call_id':call.id,'status':'notified'})
    else:
        emit('call_request_sent',{'call_id':call.id,'status':'offline',
             'message':'Doctor is currently offline.'})

@socketio.on('accept_call')
def on_accept_call(data):
    call=VideoCallRequest.query.get(data.get('call_id')); did=session.get('doctor_id')
    if not call or call.doctor_id!=did: return
    call.status='accepted'; db.session.commit()
    sid=user_sockets.get(call.patient_id)
    if sid: socketio.emit('call_accepted',{'video_url':f'/video/{call.room_id}?caller=true'},room=sid)

@socketio.on('decline_call')
def on_decline_call(data):
    call=VideoCallRequest.query.get(data.get('call_id')); did=session.get('doctor_id')
    if not call or call.doctor_id!=did: return
    call.status='declined'; db.session.commit()
    sid=user_sockets.get(call.patient_id)
    if sid: socketio.emit('call_declined',{'message':'Doctor is unavailable right now.'},room=sid)

@socketio.on('join_video_room')
def on_join_video_room(data):
    rid=data.get('room_id',''); join_room(f'video_{rid}')
    emit('peer_joined_video',{},room=f'video_{rid}',include_self=False)

@socketio.on('webrtc_offer')
def on_offer(data):
    emit('webrtc_offer',{'sdp':data['sdp']},room=f"video_{data['room_id']}",include_self=False)

@socketio.on('webrtc_answer')
def on_answer(data):
    emit('webrtc_answer',{'sdp':data['sdp']},room=f"video_{data['room_id']}",include_self=False)

@socketio.on('webrtc_ice')
def on_ice(data):
    emit('webrtc_ice',{'candidate':data['candidate']},room=f"video_{data['room_id']}",include_self=False)

@socketio.on('end_call')
def on_end_call(data):
    rid=data.get('room_id','')
    call=VideoCallRequest.query.filter_by(room_id=rid).order_by(VideoCallRequest.id.desc()).first()
    if call: call.status='ended'; db.session.commit()
    emit('call_ended',{},room=f'video_{rid}',include_self=False); leave_room(f'video_{rid}')

# ─── Seed ──────────────────────────────────────────────────────────────────────

def seed_data():
    if Doctor.query.count()==0:
        db.session.add_all([
            Doctor(name="Dr. Priya Sharma",  specialty="Gynaecologist & Obstetrician",category="menstrual",experience=12,rating=4.9,avatar_color="#f4a7b9",email="priya@bloom.dev", password=hash_password("doctor123"),is_verified=True),
            Doctor(name="Dr. Ananya Rao",    specialty="Sexual Health Counsellor",    category="sexual",   experience=8, rating=4.7,avatar_color="#b5c9a8",email="ananya@bloom.dev",password=hash_password("doctor123"),is_verified=True),
            Doctor(name="Dr. Meera Pillai",  specialty="Psychiatrist & Therapist",    category="mental",   experience=15,rating=4.8,avatar_color="#c4b5d4",email="meera@bloom.dev", password=hash_password("doctor123"),is_verified=True),
            Doctor(name="Dr. Sunita Verma",  specialty="General Physician",           category="general",  experience=10,rating=4.6,avatar_color="#f6c89f",email="sunita@bloom.dev",password=hash_password("doctor123"),is_verified=True),
            Doctor(name="Dr. Kavita Nair",   specialty="Reproductive Endocrinologist",category="menstrual",experience=9, rating=4.7,avatar_color="#a8c4c4",email="kavita@bloom.dev",password=hash_password("doctor123"),is_verified=True),
            Doctor(name="Dr. Ritu Malhotra", specialty="Clinical Psychologist",       category="mental",   experience=7, rating=4.8,avatar_color="#d4b5b5",email="ritu@bloom.dev",  password=hash_password("doctor123"),is_verified=True),
        ]); db.session.commit()
    if Admin.query.count()==0:
        db.session.add(Admin(username='admin',password=hash_password('admin123'))); db.session.commit()
        print("\n[SEED] Admin: admin/admin123  |  Doctors: doctor123\n")

if __name__ == '__main__':
    with app.app_context(): db.create_all(); seed_data()
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)