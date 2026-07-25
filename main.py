import asyncio
import os
import json
import secrets
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CBee-Panel")

from storage.database import load_state, save_state, get_inbounds
from core.relay import handle_vless_connection, HTTPRelay, stats, connections, hourly_traffic
from api.admin import router as admin_router
from api.resellers import router as reseller_router
from api.telegram_bot import telegram_bot

app = FastAPI(title="CBee Panel", version="2.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("web/static/css", exist_ok=True)
os.makedirs("web/templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")

app.include_router(admin_router)
app.include_router(reseller_router)

async def get_inbound_by_port(port: int):
    inbounds = await get_inbounds()
    for i in inbounds:
        if i.get("port") == port:
            return i
    return None

async def check_usage(uid: str, bytes_used: int) -> bool:
    inbounds = await get_inbounds()
    inbound = next((i for i in inbounds if i["id"] == uid), None)
    if not inbound:
        return False
    if not inbound.get("enabled", True):
        return False
    total = inbound.get("total_bytes", 0)
    used = inbound.get("used_bytes", 0)
    if total > 0 and used + bytes_used > total:
        return False
    expiry = inbound.get("expiry_date")
    if expiry:
        try:
            expiry_date = datetime.fromisoformat(expiry)
            if expiry_date < datetime.now():
                return False
        except:
            pass
    inbound["used_bytes"] = used + bytes_used
    from storage.database import update_inbound
    await update_inbound(uid, {"used_bytes": used + bytes_used})
    return True

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="fa">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ورود · CBee Panel</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="login-container">
        <div class="login-box">
            <div class="login-header">🐝 CBee Panel</div>
            <form id="loginForm" onsubmit="login(event)">
                <input type="text" id="username" placeholder="نام کاربری" required>
                <input type="password" id="password" placeholder="رمز عبور" required>
                <button type="submit">ورود به داشبورد</button>
            </form>
            <div id="loginError" style="color:red;display:none;"></div>
        </div>
    </div>
    <script>
    async function login(e) {
        e.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        try {
            const res = await fetch('/api/admin/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, password})
            });
            const data = await res.json();
            if (res.ok) {
                localStorage.setItem('token', data.token);
                window.location.href = '/dashboard';
            } else {
                document.getElementById('loginError').textContent = data.detail || 'خطا در ورود';
                document.getElementById('loginError').style.display = 'block';
            }
        } catch(err) {
            document.getElementById('loginError').textContent = 'خطا در ارتباط با سرور';
            document.getElementById('loginError').style.display = 'block';
        }
    }
    </script>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fa">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>داشبورد · CBee Panel</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="header">
        <h1>🐝 CBee Panel</h1>
        <p>مدیریت حرفه‌ای پروتکل‌ها</p>
        <button onclick="logout()" style="position:absolute;right:20px;top:20px;background:#d48f1a;border:none;padding:8px 16px;border-radius:5px;color:#fff;cursor:pointer;">خروج</button>
    </div>
    <div class="container">
        <div class="stats-grid">
            <div class="stat-card">
                <h3>اتصالات فعال</h3>
                <p id="activeConns">0</p>
            </div>
            <div class="stat-card">
                <h3>کل ترافیک</h3>
                <p id="totalBytes">0 MB</p>
            </div>
            <div class="stat-card">
                <h3>درخواست‌ها</h3>
                <p id="totalReqs">0</p>
            </div>
        </div>
        <div class="hex-grid" id="protocolGrid">
            <div class="hex-card" onclick="filterProtocol('vless')">VLESS</div>
            <div class="hex-card" onclick="filterProtocol('vmess')">VMess</div>
            <div class="hex-card" onclick="filterProtocol('trojan')">Trojan</div>
            <div class="hex-card" onclick="filterProtocol('shadowsocks')">Shadowsocks</div>
            <div class="hex-card" onclick="filterProtocol('socks')">SOCKS</div>
            <div class="hex-card" onclick="filterProtocol('http')">HTTP</div>
            <div class="hex-card" onclick="filterProtocol('https')">HTTPS</div>
            <div class="hex-card" onclick="filterProtocol('grpc')">gRPC</div>
            <div class="hex-card" onclick="filterProtocol('quic')">QUIC</div>
            <div class="hex-card" onclick="filterProtocol('all')" style="background:#d48f1a;">همه</div>
        </div>
        <div id="inboundList" style="margin-top:30px;width:100%;max-width:900px;">
            <h3 style="color:#2c2c2c;">لیست اینباندها</h3>
            <div id="inboundItems"></div>
        </div>
    </div>
    <footer style="text-align:center;padding:30px 0;color:#888;font-size:0.9rem;border-top:1px solid #eee;margin-top:40px;">
        ساخته شده با <span style="display:inline-block;animation:pulse 1.5s infinite;font-size:1.2rem;">💛</span> توسط <strong style="color:#f5a623;">CBeeNet</strong>
        <br>
        <span style="font-size:0.8rem;">📢 کانال تلگرام: <a href="https://t.me/CbeeNet" target="_blank" style="color:#f5a623;text-decoration:none;">@CbeeNet</a></span>
    </footer>
    <style>
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.3); }
            100% { transform: scale(1); }
        }
    </style>
    <script src="/static/js/dashboard.js"></script>
</body>
</html>
"""

@app.get("/")
async def root():
    return RedirectResponse(url="/login")

@app.get("/login")
async def login_page():
    return HTMLResponse(LOGIN_HTML)

@app.get("/dashboard")
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML)

@app.get("/api/stats")
async def get_stats():
    return {
        "active_connections": stats.get("active_connections", 0),
        "total_bytes": stats.get("total_bytes", 0),
        "total_requests": stats.get("total_requests", 0),
        "connections": len(connections)
    }

@app.websocket("/vless/{path:path}")
async def vless_websocket(websocket: WebSocket, path: str):
    await websocket.accept()
    await handle_vless_connection(websocket, get_inbound_by_port, check_usage)

http_relay = HTTPRelay()

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def relay_http(request: Request, path: str):
    if path.startswith("api/") or path.startswith("static/") or path in ["login", "dashboard", ""]:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Not found"}, status_code=404)
    port = request.url.port or 443
    inbound = await get_inbound_by_port(port)
    if not inbound:
        return JSONResponse({"error": "Inbound not found"}, status_code=404)
    target = f"http://{inbound.get('host', 'localhost')}:{inbound.get('target_port', port)}"
    return await http_relay.forward(request, target)

async def startup():
    logger.info("🐝 CBee Panel v2.0 starting...")
    await load_state()
    asyncio.create_task(telegram_bot.start())
    logger.info("CBee Panel started successfully")

async def shutdown():
    await telegram_bot.stop()
    logger.info("CBee Panel shutting down")

app.add_event_handler("startup", startup)
app.add_event_handler("shutdown", shutdown)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)