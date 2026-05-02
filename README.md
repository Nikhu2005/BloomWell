# 🌸 BloomWell – Setup & Run Guide

## What Was Built (MVP Summary)
BloomWell is a privacy-first women's wellness web app. This MVP includes:
- **Anonymous login system** (register with auto-generated username)
- **Doctor listing** with category filters (menstrual, sexual, mental, general)
- **Real-time chat interface** with typing indicators and auto-reply
- **Dashboard** with stats, consultation history, and category navigation
- **Delete chat** feature for privacy control
- SQLite database – zero external services needed

---

## 📁 Project Structure
```
bloomwell/
├── app.py                  ← Flask backend (routes, models, logic)
├── requirements.txt        ← Python dependencies
├── database.db             ← Auto-created on first run
├── templates/
│   ├── login.html          ← Login & Register page
│   ├── dashboard.html      ← Main dashboard (doctors, history, categories)
│   └── chat.html           ← Chat interface with doctor
└── static/
    └── style.css           ← All styling
```

---

## ⚙️ How to Run Locally (Step-by-Step)

### Step 1 – Install Python
Make sure Python 3.9+ is installed:
```bash
python --version
```
Download from https://python.org if needed.

### Step 2 – Create a Virtual Environment (recommended)
```bash
cd bloomwell
python -m venv venv

# Activate it:
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate
```

### Step 3 – Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4 – Run the App
```bash
python app.py
```

### Step 5 – Open in Browser
Visit: **http://localhost:5000**

The database (`database.db`) and 6 seed doctors are auto-created on first run.

---

## 🌐 Deploy to the Internet (Free Options)

### Option A: Render.com (Easiest – Free Tier)
1. Push your code to GitHub
2. Go to https://render.com → New Web Service
3. Connect your GitHub repo
4. Set **Start Command**: `python app.py`
5. Set **Environment**: Python 3
6. Deploy → you get a live URL

### Option B: Railway.app
1. Push code to GitHub
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Set start command: `python app.py`
4. Free tier available

### Option C: PythonAnywhere (Free)
1. Sign up at https://pythonanywhere.com
2. Upload files via Files tab
3. Create a Web App → Flask → point to `app.py`

---

## 🔑 Environment Variables (for production)
In production, replace the secret key in `app.py`:
```python
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-dev-key')
```
Set `SECRET_KEY` as an environment variable in your hosting platform.

---

## 🚀 Next Steps (Future Features)
- [ ] OTP / email verification login
- [ ] Real-time chat with WebSockets (Flask-SocketIO)
- [ ] Video consultations (WebRTC)
- [ ] Doctor verification admin panel
- [ ] Push notifications
- [ ] Migrate to PostgreSQL for production
- [ ] End-to-end encryption with proper key exchange
