import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)

PORTAL_URL = "https://cmsys.eng.rizvi.edu.in"
LOGIN_URL = f"{PORTAL_URL}/login"
DASHBOARD_URL = f"{PORTAL_URL}/student/dashboard"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

monitor_event = threading.Event()
status_lock = threading.Lock()
status_data = {"status": "Idle", "last_check": "Never", "remaining": 0}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
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

def perform_login(email, password):
    try:
        res_get = session.get(LOGIN_URL, timeout=10)
        soup = BeautifulSoup(res_get.text, 'html.parser')
        
        payload = {}
        for tag in soup.find_all("input"):
            name = tag.get("name")
            if name:
                val = tag.get("value", "")
                lower_name = name.lower()
                if any(k in lower_name for k in ["user", "email", "login", "id", "username"]):
                    payload[name] = email
                elif any(k in lower_name for k in ["pass", "pwd", "secret", "password"]):
                    payload[name] = password
                else:
                    payload[name] = val
                    
        if not any(email in str(v) for v in payload.values()):
            payload["email"] = email
            payload["password"] = password

        session.post(LOGIN_URL, data=payload, timeout=15)
        
        check_res = session.get(DASHBOARD_URL, timeout=10)
        if "/login" not in check_res.url.lower():
            return True
    except Exception as e:
        print(f"Login Error: {e}")
    return False

def monitor_loop(email, password):
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
                    status_data["status"] = "Session expired, re-logging in..."
                if not perform_login(email, password):
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
    <title>Rizvi Attendance Monitor</title>
    <style>
        body { background: #0F0F0F; color: #FFF; font-family: sans-serif; text-align: center; padding: 20px; }
        input { padding: 12px; margin: 8px; width: 80%; max-width: 300px; border-radius: 8px; border: 1px solid #444; background: #1E1E1E; color: #FFF; font-size: 16px; }
        button { padding: 14px 28px; border: none; border-radius: 12px; font-size: 16px; margin: 10px; width: 80%; max-width: 320px; cursor: pointer; font-weight: bold; }
        .start { background: #00C853; color: white; }
        .stop { background: #D50000; color: white; }
        #status { margin-top: 20px; padding: 16px; border: 1px solid #333; border-radius: 12px; font-size: 16px; background: #1E1E1E; }
        #timer { color: #00E676; font-size: 15px; margin-top: 6px; }
    </style>
</head>
<body>
    <h2>Rizvi Attendance Agent</h2>
    <p style="color: #aaa; font-size: 14px;">Mobile Friendly | Direct Login</p>
    
    <div>
        <input type="text" id="email" placeholder="Portal Email / ID"><br>
        <input type="password" id="password" placeholder="Portal Password"><br>
        <button class="start" onclick="startMonitoring()">Start Monitoring</button><br>
        <button class="stop" onclick="stopMonitoring()">Stop Monitoring</button>
    </div>

    <div id="status">Status: Idle</div>
    <div id="timer"></div>

    <script>
        async function startMonitoring() {
            let email = document.getElementById('email').value;
            let password = document.getElementById('password').value;
            if(!email || !password) {
                alert("Pehle email aur password daal bhai!");
                return;
            }
            let res = await fetch('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email: email, password: password})
            });
            let d = await res.json();
            alert(d.message);
        }

        async function stopMonitoring() {
            let res = await fetch('/stop', {method: 'POST'});
            let d = await res.json();
            alert(d.message);
        }

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
    
    data = request.get_json() or {}
    email = data.get("email") or os.environ.get("PORTAL_EMAIL")
    password = data.get("password") or os.environ.get("PORTAL_PASSWORD")
    
    if not email or not password:
        return jsonify({"success": False, "message": "Email and Password required!"})
        
    if not perform_login(email, password):
        return jsonify({"success": False, "message": "Login Failed! Check credentials or portal security."})
        
    monitor_event.set()
    threading.Thread(target=monitor_loop, args=(email, password), daemon=True).start()
    return jsonify({"success": True, "message": "Monitoring Started Successfully!"})

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
        
