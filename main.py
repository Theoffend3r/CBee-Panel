import asyncio
import json
import os
import secrets
import time
import base64
import hashlib
import logging
import re
import socket
import struct
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from urllib.parse import quote, unquote

import httpx
import psutil
import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyCookie

# ==================== تنظیمات اولیه ====================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SLV-Panel")

app = FastAPI(title="SLV Panel", version="2.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== پیکربندی و ذخیره‌سازی ====================

DATA_FILE = "panel_db.json"
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

# ساختار داده‌ها
LINKS: Dict[str, dict] = {}
CUSTOM_ADDRESSES: List[str] = []
CONFIG: dict = {}
SESSION_STORE: Dict[str, str] = {}  # session_id -> username

def load_db():
    global LINKS, CUSTOM_ADDRESSES, CONFIG
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                LINKS = data.get("links", {})
                CUSTOM_ADDRESSES = data.get("addresses", [])
                CONFIG = data.get("config", {})
                # اطمینان از وجود کلیدهای ضروری
                CONFIG.setdefault("telegram_token", "")
                CONFIG.setdefault("telegram_admin_id", "")
                CONFIG.setdefault("lang", "fa")
                logger.info(f"✅ Loaded {len(LINKS)} links and {len(CUSTOM_ADDRESSES)} addresses from {DATA_FILE}")
        else:
            logger.info("📄 No existing database found, starting fresh.")
    except Exception as e:
        logger.error(f"❌ Error loading database: {e}")

def save_db():
    global LINKS, CUSTOM_ADDRESSES, CONFIG
    try:
        data = {
            "links": LINKS,
            "addresses": CUSTOM_ADDRESSES,
            "config": CONFIG
        }
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"💾 Saved {len(LINKS)} links and {len(CUSTOM_ADDRESSES)} addresses to {DATA_FILE}")
    except Exception as e:
        logger.error(f"❌ Error saving database: {e}")

# بارگذاری اولیه
load_db()

# ==================== توابع کمکی ====================

def hash_password(password: str) -> str:
    return hashlib.sha256((password + SECRET_KEY).encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

def generate_session_id() -> str:
    return secrets.token_urlsafe(32)

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def make_vless_link(uuid: str, domain: str, path: str, remark: str = "") -> str:
    # ساخت لینک VLESS استاندارد
    if not remark:
        remark = uuid[:8]
    return f"vless://{uuid}@{domain}:443?encryption=none&security=tls&type=ws&host={domain}&path={quote(path)}&sni={domain}&fp=chrome&alpn=http/1.1#SLV-{remark}"

def count_connections_for_link(uid: str) -> int:
    # شمارش اتصالات فعال برای یک اینباند خاص
    # این بخش نیاز به پیاده‌سازی کامل‌تر دارد
    return 0

def close_connections_for_link(uid: str):
    # بستن اتصالات فعال برای یک اینباند
    # این بخش نیاز به پیاده‌سازی کامل‌تر دارد
    pass

# ==================== احراز هویت ====================

async def get_current_user(session_id: str = Cookie(None)):
    if not session_id or session_id not in SESSION_STORE:
        return None
    return SESSION_STORE.get(session_id)

async def require_admin(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # در اینجا می‌توانید بررسی کنید که کاربر ادمین است
    return user

# ==================== مسیرهای API ====================

@app.post("/api/login")
async def api_login(request: Request, username: str = Form("admin"), password: str = Form(...)):
    if username != "admin":
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not verify_password(password, hash_password(ADMIN_PASSWORD)):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session_id = generate_session_id()
    SESSION_STORE[session_id] = "admin"
    
    response = JSONResponse({"status": "ok", "message": "Login successful"})
    response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=3600*24*7)
    return response

@app.post("/api/logout")
async def api_logout(session_id: str = Cookie(None)):
    if session_id and session_id in SESSION_STORE:
        del SESSION_STORE[session_id]
    response = JSONResponse({"status": "ok"})
    response.delete_cookie("session_id")
    return response

@app.get("/api/me")
async def api_me(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": "admin"}

@app.post("/api/change-password")
async def api_change_password(current: str = Form(...), new: str = Form(...), user: str = Depends(require_admin)):
    global ADMIN_PASSWORD
    if not verify_password(current, hash_password(ADMIN_PASSWORD)):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    ADMIN_PASSWORD = new
    # ذخیره رمز جدید در فایل env یا دیتابیس
    # در اینجا رمز را در حافظه نگه می‌داریم
    save_db()  # برای ذخیره سایر تنظیمات
    return {"status": "ok", "message": "Password changed successfully"}

# ==================== مدیریت اینباندها ====================

@app.get("/api/links")
async def api_get_links(user: str = Depends(require_admin)):
    return {"links": LINKS}

@app.post("/api/links")
async def api_create_link(
    name: str = Form(...),
    limit_gb: int = Form(0),
    days: int = Form(30),
    max_ips: int = Form(0),
    user: str = Depends(require_admin)
):
    # اعتبارسنجی
    if not name or not re.match(r'^[a-zA-Z0-9_\-]+$', name):
        raise HTTPException(status_code=400, detail="Invalid name. Use only English letters, numbers, underscore or dash.")
    
    if name in LINKS:
        raise HTTPException(status_code=400, detail="Name already exists.")
    
    # تولید UUID و path
    uid = str(uuid.uuid4())
    path = f"/ws/{uid}"
    
    # محاسبه تاریخ انقضا
    expires_at = None
    if days > 0:
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    
    # ذخیره در دیکشنری
    LINKS[name] = {
        "uid": uid,
        "name": name,
        "path": path,
        "limit": limit_gb * 1024 * 1024 * 1024 if limit_gb > 0 else 0,  # bytes
        "used": 0,
        "expires_at": expires_at,
        "max_ips": max_ips,
        "active": True,
        "created_at": datetime.now().isoformat(),
        "remark": name
    }
    
    save_db()
    
    # ساخت لینک
    domain = get_domain()
    vless_link = make_vless_link(uid, domain, path, name)
    sub_link = f"{get_base_url()}/sub/{uid}"
    
    return {
        "status": "ok",
        "link": LINKS[name],
        "vless": vless_link,
        "sub": sub_link
    }

@app.patch("/api/links/{name}")
async def api_update_link(
    name: str,
    active: Optional[bool] = Form(None),
    limit_gb: Optional[int] = Form(None),
    max_ips: Optional[int] = Form(None),
    days: Optional[int] = Form(None),
    reset_usage: Optional[bool] = Form(False),
    user: str = Depends(require_admin)
):
    if name not in LINKS:
        raise HTTPException(status_code=404, detail="Link not found")
    
    link = LINKS[name]
    
    if active is not None:
        link["active"] = active
    
    if limit_gb is not None:
        link["limit"] = limit_gb * 1024 * 1024 * 1024
    
    if max_ips is not None:
        link["max_ips"] = max_ips
    
    if days is not None:
        if days > 0:
            link["expires_at"] = (datetime.now() + timedelta(days=days)).isoformat()
        else:
            link["expires_at"] = None
    
    if reset_usage:
        link["used"] = 0
    
    save_db()
    return {"status": "ok", "link": link}

@app.delete("/api/links/{name}")
async def api_delete_link(name: str, user: str = Depends(require_admin)):
    if name not in LINKS:
        raise HTTPException(status_code=404, detail="Link not found")
    
    # بستن اتصالات فعال
    uid = LINKS[name]["uid"]
    close_connections_for_link(uid)
    
    del LINKS[name]
    save_db()
    return {"status": "ok"}

@app.get("/sub/{uid}")
async def get_subscription(uid: str):
    # پیدا کردن اینباند با uid
    link_name = None
    link_data = None
    for name, data in LINKS.items():
        if data["uid"] == uid:
            link_name = name
            link_data = data
            break
    
    if not link_data:
        raise HTTPException(status_code=404, detail="Not found")
    
    # ساخت کانفیگ VLESS
    domain = get_domain()
    path = link_data["path"]
    vless_link = make_vless_link(uid, domain, path, link_name)
    
    # تبدیل به base64
    config = base64.b64encode(vless_link.encode()).decode()
    
    return Response(content=config, media_type="text/plain")

# ==================== مدیریت آدرس‌های تمیز ====================

@app.get("/api/addresses")
async def api_get_addresses(user: str = Depends(require_admin)):
    return {"addresses": CUSTOM_ADDRESSES}

@app.post("/api/addresses")
async def api_add_address(address: str = Form(...), user: str = Depends(require_admin)):
    if not address or len(address) < 3:
        raise HTTPException(status_code=400, detail="Invalid address")
    
    if address in CUSTOM_ADDRESSES:
        raise HTTPException(status_code=400, detail="Address already exists")
    
    CUSTOM_ADDRESSES.append(address)
    save_db()
    return {"status": "ok", "addresses": CUSTOM_ADDRESSES}

@app.delete("/api/addresses/{index}")
async def api_delete_address(index: int, user: str = Depends(require_admin)):
    if index < 0 or index >= len(CUSTOM_ADDRESSES):
        raise HTTPException(status_code=404, detail="Address not found")
    
    del CUSTOM_ADDRESSES[index]
    save_db()
    return {"status": "ok"}

@app.delete("/api/addresses")
async def api_delete_all_addresses(user: str = Depends(require_admin)):
    CUSTOM_ADDRESSES.clear()
    save_db()
    return {"status": "ok"}

# ==================== تنظیمات ====================

@app.get("/api/settings")
async def api_get_settings(user: str = Depends(require_admin)):
    return {
        "telegram_token": CONFIG.get("telegram_token", ""),
        "telegram_admin_id": CONFIG.get("telegram_admin_id", ""),
        "lang": CONFIG.get("lang", "fa")
    }

@app.post("/api/settings")
async def api_update_settings(
    telegram_token: Optional[str] = Form(None),
    telegram_admin_id: Optional[str] = Form(None),
    lang: Optional[str] = Form(None),
    user: str = Depends(require_admin)
):
    if telegram_token is not None:
        CONFIG["telegram_token"] = telegram_token
    if telegram_admin_id is not None:
        CONFIG["telegram_admin_id"] = telegram_admin_id
    if lang is not None and lang in ["en", "fa"]:
        CONFIG["lang"] = lang
    
    save_db()
    
    # راه‌اندازی مجدد ربات تلگرام
    asyncio.create_task(restart_telegram_bot())
    
    return {"status": "ok"}

# ==================== آمار و سلامت ====================

def get_domain() -> str:
    # تلاش برای دریافت دامنه از هدرها یا متغیر محیطی
    # در اینجا یک دامنه پیش‌فرض برمی‌گردانیم
    return os.environ.get("DOMAIN", "slv-panel.onrender.com")

def get_base_url() -> str:
    return f"https://{get_domain()}"

@app.get("/stats")
async def get_stats(user: str = Depends(require_admin)):
    # آمار سرور
    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    uptime_seconds = time.time() - psutil.boot_time()
    
    # آمار اینباندها
    total_traffic = sum(link.get("used", 0) for link in LINKS.values())
    active_links = sum(1 for link in LINKS.values() if link.get("active", True))
    
    return {
        "cpu": cpu_percent,
        "memory": memory.percent,
        "memory_used": memory.used,
        "memory_total": memory.total,
        "uptime": uptime_seconds,
        "total_traffic": total_traffic,
        "active_links": active_links,
        "total_links": len(LINKS),
        "active_connections": 0  # باید از WebSocket ها شمارش شود
    }

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ==================== صفحات HTML ====================

# قالب‌های HTML در ادامه قرار داده می‌شوند...

# ==================== WebSocket Proxy ====================

# این بخش به صورت کامل پیاده‌سازی خواهد شد...

# ==================== ربات تلگرام ====================

# این بخش به صورت کامل پیاده‌سازی خواهد شد...

# ==================== اجرا ====================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
