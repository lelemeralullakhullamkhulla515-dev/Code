import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, jsonify

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
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": LOGIN_URL
})

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except:
        pass

def login():
    try:
        res_get = session.get(LOGIN_URL, timeout=10)
        soup = BeautifulSoup(res_get.text, 'html.parser')
        
        inputs = soup.find_all("input")
        payload = {}
        
        for tag in inputs:
            name = tag.get("name")
            if name:
                val = tag.get("value", "")
                lower_name = name.lower()
                if any(k in lower_name for k in ["user", "email", "login", "id", "username"]):
                    payload[name] = PORTAL_EMAIL
                elif any(k in lower_name for k in ["pass", "pwd", "secret", "password"]):
                    payload[name] = PORTAL_PASSWORD
                else:
                    payload[name] = val
                    
        # Fallback fields if not matched
        if not any(v == PORTAL_EMAIL for v in payload.values()):
            payload["username"] = PORTAL_EMAIL
        if not any(v == PORTAL_PASSWORD for v in payload.values()):
            payload["password"] = PORTAL_PASSWORD

        res = session.post(LOGIN_URL, data=payload, timeout=10)
        
        check_res = session.get(DASHBOARD_URL, timeout=10)
        if "/login" not in check_res.url.lower():
            return True
    except Exception as e:
        print(f"Login Exception: {e}")
    return False

def monitor_loop():
    start_time = time.time()
    MAX_DURATION = 900  # 15 minutes
    
    while monitor_event.is_set():
        elapsed = time.time() - start_time
        remaining = MAX_DURATION - int(elapsed)
        
        if elapsed >= MAX_DURATION:
            with status_lock:
                status_data["status"] = "Idle - Time Over (15 min)"
                status_data["remaining"] = 0
            monitor_event.clear()
            break
            
        with status_lock:
            status_data["remaining"] = remaining
            
        try:
            with status_lock:
                status_data["status"] = "Monitoring Active"
                
            res = session.get(DASHBOARD_URL, timeout=15)
            
            if "/login" in res.url.lower():
                with status_lock:
                    status_data["status"] = "Re-logging in..."
                if not login():
                    time.sleep(5)
                    continue
                time.sleep(2)
                continue
                
            soup = BeautifulSoup(res.text, 'html.parser')
            text = soup.get_text().lower()
            
            if "mark your attendance" in text or "mark attendance" in text:
                with status_lock:
                    status_data["status"] = "Attendance Button Detected!"
                send_telegram_alert("🚨 ATTENDANCE IS ALIVE! Open portal immediately: https://cmsys.eng.rizvi.edu.in")
                time.sleep(60)
            else:
                with status_lock:
                    status_data["last_check"] = time.strftime("%H:%M:%S")
                time.sleep(15)
                
        except:
            with status_lock:
                status_data["status"] = "Error, retrying..."
            for _ in range(15):
                if not monitor_event.is_set():
                    break
                time.sleep(1)
                
    with status_lock:
        status_data["status"] = "Idle"
        status_data["remaining"] = 0

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Attendance Monitor</title>
    <style>
        body { background: #0F0F0F; color: #FFF; font-family: sans-serif; text-align: center; padding: 20px; }
        button { padding: 15px 28px; border: none; border-radius: 12px; font-size: 18px; margin: 10px; width: 80%; max-width: 320px; cursor: pointer; }
        .start { background: #00C853; color: white; }
        .stop { background: #D50000; color: white; }
        #status { margin-top: 20px; padding: 18px; border: 1px solid #333; border-radius: 12px; font-size: 18px; background: #1E1E1E; }
        #timer { color: #00E676; font-size: 16px; margin-top: 8px; }
    </style>
</head>
<body>
    <h2>Attendance Agent - 15s Full Background</h2>
    <p style="color: #aaa;">Max 15 sec pe auto refresh | Max 15 min</p>
    <button class="start" onclick="fetch('/start', {method: 'POST'}).then(r => r.json()).then(d => alert(d.message))">Start Monitoring</button><br>
    <button class="stop" onclick="fetch('/stop', {method: 'POST'}).then(r => r.json()).then(d => alert(d.message))">Stop Monitoring</button>
    <div id="status">Status: Idle</div>
    <div id="timer"></div>
    <script>
        setInterval(async () => {
            let res = await fetch('/status');
            let d = await res.json();
            document.getElementById('status').innerText = `Status: ${d.status} | Last Check: ${d.last_check}`;
            if (d.remaining > 0) {
                let m = Math.floor(d.remaining / 60);
                let s = d.remaining % 60;
                document.getElementById('timer').innerText = `Auto Stop in: ${m}:${s.toString().padStart(2, '0')}`;
            } else { document.getElementById('timer').innerText = ""; }
        }, 3000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/start', methods=['POST'])
def start():
    if monitor_event.is_set():
        return jsonify({"success": False, "message": "Already Running"})
    if not login():
        return jsonify({"success": False, "message": "Login Failed. Check credentials or portal security."})
    monitor_event.set()
    threading.Thread(target=monitor_loop, daemon=True).start()
    return jsonify({"success": True, "message": "Monitoring Started for 15 min - 15s interval"})

@app.route('/stop', methods=['POST'])
def stop():
    monitor_event.clear()
    with status_lock:
        status_data["status"] = "Idle"
        status_data["remaining"] = 0
    return jsonify({"success": True, "message": "Monitoring Stopped"})

@app.route('/status')
def status():
    with status_lock:
        return jsonify(status_data)
        
