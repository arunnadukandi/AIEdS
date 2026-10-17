# AIEdS — Setup & Run Guide

## Quick Start (Windows Laptop — Claude Mode)

### 1. Install dependencies
Open a terminal in the `login/` folder and run:
```
pip install -r requirements.txt
```

### 2. Create your .env file
Copy the template and fill in your Anthropic API key:
```
copy .env.template .env
```
Then open `.env` in Notepad and replace `sk-ant-REPLACE_WITH_YOUR_KEY_HERE` with your real key.
Get your key at: https://console.anthropic.com/

### 3. Run the app
```
streamlit run login.py
```
The app opens at http://localhost:8501

---

## Switching between Claude and Ollama

Open `login/.env` and change one line:

| Mode | Setting |
|------|---------|
| Claude (laptop, no Ollama) | `LLM_PROVIDER=claude` |
| Ollama (workstation with Ollama) | `LLM_PROVIDER=ollama` |

That's the **only** change needed to switch providers. Everything else is automatic.

---

## First-time admin login
The default admin credentials are set in the database. If none exist, create one via the Sign Up tab with role = Admin, or run:
```python
# In a Python shell from the login/ folder:
import sqlite3, hashlib, os
db = sqlite3.connect("sahayak.db")
salt = "admin_salt"
pw_hash = hashlib.sha256((salt + "admin123").encode()).hexdigest()
db.execute("INSERT OR IGNORE INTO users (username,password_hash,salt,role,full_name) VALUES (?,?,?,'admin','Administrator')", ("admin", pw_hash, salt))
db.commit()
```
Then login with username `admin`, password `admin123`.

---

## File structure
```
login/
├── login.py              ← Entry point (streamlit run this)
├── chatbot.py            ← AI chatbot (uses llm_client.py)
├── llm_client.py         ← LLM abstraction: Claude ↔ Ollama
├── .env                  ← Your API keys (never commit this)
├── .env.template         ← Template for .env
├── requirements.txt      ← Python dependencies
├── sahayak.db            ← SQLite database (auto-created)
└── pages/
    ├── student.py        ← Student dashboard (4 modules)
    ├── chatbot.py        ← (routed from student dashboard)
    ├── _quiz.py          ← Adaptive quiz
    ├── assignments.py    ← Assignment module
    ├── study_materials.py← Study material downloads
    ├── instructor.py     ← Instructor dashboard
    └── admin.py          ← Admin panel
```
