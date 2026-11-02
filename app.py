import os, time, threading, requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify

app = Flask(__name__)

PORTAL_URL = "https://cmsys.eng.rizvi.edu.in"
LOGIN_URL = f"{PORTAL_URL}/login"
DASHBOARD_URL = f"{PORTAL_URL}/student/dashboard"
PORTAL_EMAIL = os.environ.get("PORTAL_EMAIL")
PORTAL_PASSWORD = os.environ.get("PORTAL_PASSWORD")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

monitor_event = threading.Event()
status_lock = threading.Lock()
status_data = {"status": "Idle", "last_check": "Never", "remaining": 0}
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except: pass

def login():
    try:
        payload = {"username": PORTAL_EMAIL, "password": PORTAL_PASSWORD}
        session.post(LOGIN_URL, data=payload, timeout=10)
        return True
    except: return False

def monitor_loop():
    start_time = time.time()
    MAX_DURATION = 600
    while monitor_event.is_set():
        elapsed = time.time() - start_time
        remaining = MAX_DURATION - int(elapsed)
        if elapsed >= MAX_DURATION:
            with status_lock:
                status_data["status"] = "Idle - Time Over (10 min)"
                status_data["remaining"] = 0
            monitor_event.clear()
            break
        with status_lock: status_data["remaining"] = remaining
        try:
            with status_lock: status_data["status"] = "Monitoring Active"
            res = session.get(DASHBOARD_URL, timeout=15)
            if "/login" in res.url.lower():
                with status_lock: status_data["status"] = "Re-logging in..."
                login()
                time.sleep(2)
                continue
            soup = BeautifulSoup(res.text, 'html.parser\')
            text = soup.get_text().lower()
            if "mark your attendance" in text or "mark attendance" in text:
                with status_lock: status_data["status"] = "Attendance Button Detected!"
                send_telegram_alert("🚨 ATTENDANCE IS ALIVE! Open portal immediately: https://cmsys.eng.rizvi.edu.in")
                time.sleep(60)
            else:
                with status_lock: status_data["last_check"] = time.strftime("%H:%M:%S")
        except:
            with status_lock: status_data["status"] = "Error, retrying..."
        for _ in range(15):
            if not monitor_event.is_set(): break
            time.sleep(1)
    with status_lock:
        if status_data["status"] != "Idle - Time Over (10 min)":
            status_data["status"] = "Idle"
            status_data["remaining"] = 0

@app.route(\'/\')
def index(): return render_template(\'index.html\')
@app.route(\'/start\', methods=[\'POST\'])
def start():
    if monitor_event.is_set(): return jsonify({"success": False, "message": "Already Running"})
    monitor_event.set()
    threading.Thread(target=monitor_loop, daemon=True).start()
    return jsonify({"success": True, "message": "Monitoring Started for 10 min - 15s interval"})
@app.route(\'/stop\', methods=[\'POST\'])
def stop():
    monitor_event.clear()
    with status_lock:
        status_data["status"] = "Idle"
        status_data["remaining"] = 0
    return jsonify({"success": True, "message": "Monitoring Stopped"})
@app.route(\'/status\')
def status():
    with status_lock: return jsonify(status_data)

if __name__ == \'__main__\':
    app.run(host=\'0.0.0.0\', port=int(os.environ.get("PORT", 10000)))
