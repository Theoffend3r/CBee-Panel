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
from typing import Dict, List, Optional, Set, Any, Union
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
    if not remark:
        remark = uuid[:8]
    return f"vless://{uuid}@{domain}:443?encryption=none&security=tls&type=ws&host={domain}&path={quote(path)}&sni={domain}&fp=chrome&alpn=http/1.1#SLV-{remark}"

def make_vmess_link(uuid: str, domain: str, path: str, remark: str = "") -> str:
    if not remark:
        remark = uuid[:8]
    vmess_config = {
        "v": "2",
        "ps": f"SLV-{remark}",
        "add": domain,
        "port": "443",
        "id": uuid,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": domain,
        "path": path,
        "tls": "tls"
    }
    return f"vmess://{base64.b64encode(json.dumps(vmess_config).encode()).decode()}"

def make_trojan_link(uuid: str, domain: str, path: str, remark: str = "") -> str:
    if not remark:
        remark = uuid[:8]
    return f"trojan://{uuid}@{domain}:443?path={quote(path)}&security=tls&type=ws&host={domain}&sni={domain}#SLV-{remark}"

def get_domain() -> str:
    return os.environ.get("DOMAIN", "slv-panel.onrender.com")

def get_base_url() -> str:
    return f"https://{get_domain()}"

def format_bytes(bytes_val: int) -> str:
    if bytes_val == 0:
        return "0 B"
    k = 1024
    sizes = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while bytes_val >= k and i < len(sizes) - 1:
        bytes_val /= k
        i += 1
    return f"{bytes_val:.2f} {sizes[i]}"

def format_date(date_str: Optional[str]) -> str:
    if not date_str:
        return "بدون انقضا"
    try:
        d = datetime.fromisoformat(date_str)
        return d.strftime("%Y/%m/%d %H:%M")
    except:
        return date_str

def count_connections_for_link(uid: str) -> int:
    if uid not in ws_connections:
        return 0
    return len(ws_connections[uid])

def close_connections_for_link(uid: str):
    if uid in ws_connections:
        for conn_id, conn_data in list(ws_connections[uid].items()):
            try:
                asyncio.create_task(conn_data["ws"].close(code=1000, reason="Link deleted"))
            except:
                pass
        ws_connections[uid].clear()
        del ws_connections[uid]

# ==================== احراز هویت ====================

async def get_current_user(session_id: str = Cookie(None)):
    if not session_id or session_id not in SESSION_STORE:
        return None
    return SESSION_STORE.get(session_id)

async def require_admin(user: str = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
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
    save_db()
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
    protocol: str = Form("vless"),
    user: str = Depends(require_admin)
):
    if not name or not re.match(r'^[a-zA-Z0-9_\-]+$', name):
        raise HTTPException(status_code=400, detail="Invalid name. Use only English letters, numbers, underscore or dash.")
    
    if name in LINKS:
        raise HTTPException(status_code=400, detail="Name already exists.")
    
    uid = str(uuid.uuid4())
    path = f"/ws/{uid}"
    
    expires_at = None
    if days > 0:
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    
    LINKS[name] = {
        "uid": uid,
        "name": name,
        "path": path,
        "limit": limit_gb * 1024 * 1024 * 1024 if limit_gb > 0 else 0,
        "used": 0,
        "expires_at": expires_at,
        "max_ips": max_ips,
        "active": True,
        "created_at": datetime.now().isoformat(),
        "remark": name,
        "protocol": protocol
    }
    
    save_db()
    
    domain = get_domain()
    
    if protocol == "vless":
        share_link = make_vless_link(uid, domain, path, name)
    elif protocol == "vmess":
        share_link = make_vmess_link(uid, domain, path, name)
    elif protocol == "trojan":
        share_link = make_trojan_link(uid, domain, path, name)
    else:
        share_link = make_vless_link(uid, domain, path, name)
    
    sub_link = f"{get_base_url()}/sub/{uid}"
    
    return {
        "status": "ok",
        "link": LINKS[name],
        "share_link": share_link,
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
    
    uid = LINKS[name]["uid"]
    close_connections_for_link(uid)
    
    del LINKS[name]
    save_db()
    return {"status": "ok"}

@app.get("/sub/{uid}")
async def get_subscription(uid: str):
    link_name = None
    link_data = None
    for name, data in LINKS.items():
        if data["uid"] == uid:
            link_name = name
            link_data = data
            break
    
    if not link_data:
        raise HTTPException(status_code=404, detail="Not found")
    
    domain = get_domain()
    path = link_data["path"]
    protocol = link_data.get("protocol", "vless")
    
    if protocol == "vless":
        vless_link = make_vless_link(uid, domain, path, link_name)
        config = vless_link
    elif protocol == "vmess":
        vmess_link = make_vmess_link(uid, domain, path, link_name)
        config = vmess_link
    elif protocol == "trojan":
        trojan_link = make_trojan_link(uid, domain, path, link_name)
        config = trojan_link
    else:
        config = make_vless_link(uid, domain, path, link_name)
    
    encoded = base64.b64encode(config.encode()).decode()
    return Response(content=encoded, media_type="text/plain")

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
    asyncio.create_task(restart_telegram_bot())
    
    return {"status": "ok"}

# ==================== آمار و سلامت ====================

@app.get("/stats")
async def get_stats(user: str = Depends(require_admin)):
    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    uptime_seconds = time.time() - psutil.boot_time()
    
    total_traffic = sum(link.get("used", 0) for link in LINKS.values())
    active_links = sum(1 for link in LINKS.values() if link.get("active", True))
    total_connections = sum(count_connections_for_link(link.get("uid", "")) for link in LINKS.values())
    
    return {
        "cpu": cpu_percent,
        "memory": memory.percent,
        "memory_used": memory.used,
        "memory_total": memory.total,
        "uptime": uptime_seconds,
        "total_traffic": total_traffic,
        "active_links": active_links,
        "total_links": len(LINKS),
        "active_connections": total_connections
    }

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ==================== WebSocket Proxy ====================

active_websockets: Dict[str, Set[WebSocket]] = {}
ws_connections: Dict[str, dict] = {}

async def handle_vless_websocket(websocket: WebSocket, uid: str):
    client_ip = "unknown"
    try:
        forwarded = websocket.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        elif websocket.client:
            client_ip = websocket.client.host
    except:
        pass
    
    logger.info(f"🔌 WebSocket connection from {client_ip} for UID: {uid}")
    
    link_name = None
    link_data = None
    for name, data in LINKS.items():
        if data.get("uid") == uid:
            link_name = name
            link_data = data
            break
    
    if not link_data:
        await websocket.close(code=1000, reason="Link not found")
        return
    
    if not link_data.get("active", True):
        await websocket.close(code=1008, reason="Inactive")
        return
    
    max_ips = link_data.get("max_ips", 0)
    if max_ips > 0:
        conn_count = count_connections_for_link(uid)
        if conn_count >= max_ips:
            await websocket.close(code=1008, reason="Max IP limit reached")
            return
    
    if not check_link_quota(link_name):
        await websocket.close(code=1008, reason="Quota exceeded or expired")
        return
    
    if uid not in ws_connections:
        ws_connections[uid] = {}
    ws_connections[uid][id(websocket)] = {
        "ws": websocket,
        "client_ip": client_ip,
        "connected_at": datetime.now().isoformat()
    }
    
    try:
        await websocket.accept()
        
        first_msg = await websocket.receive()
        if first_msg["type"] != "websocket.receive":
            await websocket.close(code=1000)
            return
        
        data = first_msg.get("bytes") or (first_msg.get("text") or "").encode()
        if not data:
            await websocket.close(code=1000)
            return
        
        try:
            command, address, port, remaining = parse_vless_header(data)
        except Exception as e:
            logger.error(f"VLESS parse error: {e}")
            await websocket.close(code=1000, reason="Invalid VLESS header")
            return
        
        try:
            reader, writer = await asyncio.open_connection(address, port)
        except Exception as e:
            logger.error(f"Target connection failed: {e}")
            await websocket.close(code=1000, reason=f"Target: {e}")
            return
        
        if remaining:
            writer.write(remaining)
            await writer.drain()
        
        task1 = asyncio.create_task(relay_ws_to_tcp(websocket, writer, link_name))
        task2 = asyncio.create_task(relay_tcp_to_ws(websocket, reader, link_name))
        
        await asyncio.gather(task1, task2, return_exceptions=True)
        
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected for UID: {uid}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if uid in ws_connections and id(websocket) in ws_connections[uid]:
            del ws_connections[uid][id(websocket)]
            if not ws_connections[uid]:
                del ws_connections[uid]

def check_link_quota(link_name: str) -> bool:
    if link_name not in LINKS:
        return False
    
    link = LINKS[link_name]
    
    if not link.get("active", True):
        return False
    
    limit = link.get("limit", 0)
    used = link.get("used", 0)
    if limit > 0 and used >= limit:
        return False
    
    expires_at = link.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at)
            if expiry < datetime.now():
                return False
        except:
            pass
    
    return True

def update_link_usage(link_name: str, bytes_used: int):
    if link_name in LINKS:
        LINKS[link_name]["used"] = LINKS[link_name].get("used", 0) + bytes_used
        if LINKS[link_name]["used"] % 10000 < bytes_used:
            save_db()

async def relay_ws_to_tcp(ws: WebSocket, writer: asyncio.StreamWriter, link_name: str):
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            
            data = msg.get("bytes") or (msg.get("text") or "").encode()
            if not data:
                continue
            
            if not check_link_quota(link_name):
                await ws.close(code=1008, reason="Quota exceeded")
                break
            
            update_link_usage(link_name, len(data))
            
            writer.write(data)
            if writer.transport.get_write_buffer_size() > 256 * 1024:
                await writer.drain()
                
    except (WebSocketDisconnect, Exception) as e:
        logger.debug(f"WS→TCP relay error: {e}")
    finally:
        try:
            writer.write_eof()
        except Exception:
            pass

async def relay_tcp_to_ws(ws: WebSocket, reader: asyncio.StreamReader, link_name: str):
    try:
        while True:
            data = await reader.read(256 * 1024)
            if not data:
                break
            
            if not check_link_quota(link_name):
                await ws.close(code=1008, reason="Quota exceeded")
                break
            
            await ws.send_bytes(data)
            
    except (WebSocketDisconnect, Exception) as e:
        logger.debug(f"TCP→WS relay error: {e}")

def parse_vless_header(chunk: bytes):
    if len(chunk) < 24:
        raise ValueError("Chunk too small")
    
    pos = 1
    pos += 16
    
    addon_len = chunk[pos]
    pos += 1 + addon_len
    
    command = chunk[pos]
    pos += 1
    
    port = int.from_bytes(chunk[pos:pos+2], "big")
    pos += 2
    
    addr_type = chunk[pos]
    pos += 1
    
    if addr_type == 1:
        address = ".".join(str(b) for b in chunk[pos:pos+4])
        pos += 4
    elif addr_type == 2:
        dlen = chunk[pos]
        pos += 1
        address = chunk[pos:pos+dlen].decode("utf-8", errors="ignore")
        pos += dlen
    elif addr_type == 3:
        ab = chunk[pos:pos+16]
        pos += 16
        address = ":".join(f"{ab[i]:02x}{ab[i+1]:02x}" for i in range(0, 16, 2))
    else:
        raise ValueError(f"Unknown address type: {addr_type}")
    
    return command, address, port, chunk[pos:]

@app.websocket("/ws/{uid}")
async def websocket_endpoint(websocket: WebSocket, uid: str):
    await handle_vless_websocket(websocket, uid)

# ==================== Telegram Bot ====================

TELEGRAM_BOT_TASK: Optional[asyncio.Task] = None
TELEGRAM_BOT_INSTANCE: Optional[Any] = None
NOTIFIED_UIDS: Set[str] = set()

def is_admin_chat(chat_id: int, admin_id: str) -> bool:
    if not admin_id:
        return False
    try:
        return str(chat_id) == str(admin_id)
    except:
        return False

async def restart_telegram_bot():
    global TELEGRAM_BOT_TASK, TELEGRAM_BOT_INSTANCE
    
    await stop_telegram_bot()
    
    token = CONFIG.get("telegram_token", "")
    admin_id = CONFIG.get("telegram_admin_id", "")
    
    if not token or not admin_id:
        logger.info("📢 Telegram bot not configured (token or admin_id missing)")
        return
    
    try:
        import telebot
        from telebot.async_telebot import AsyncTeleBot
        
        test_bot = AsyncTeleBot(token)
        try:
            me = await test_bot.get_me()
            logger.info(f"✅ Telegram bot token valid: @{me.username}")
        except Exception as e:
            logger.error(f"❌ Telegram bot token invalid: {e}")
            return
        
        bot = AsyncTeleBot(token)
        TELEGRAM_BOT_INSTANCE = bot
        
        @bot.message_handler(commands=['start'])
        async def start_cmd(message):
            if not is_admin_chat(message.chat.id, admin_id):
                logger.warning(f"⛔ Unauthorized /start from {message.chat.id}")
                return
            
            await bot.reply_to(
                message,
                "🐝 **SLV Panel Bot**\n\n"
                "سلام! به ربات مدیریت پنل خوش آمدید.\n\n"
                "📋 **دستورات موجود:**\n"
                "`/stats` - وضعیت پنل\n"
                "`/users` - لیست کاربران\n"
                "`/create نام حجم_GB روز` - ساخت کاربر جدید\n"
                "`/disable نام` - غیرفعال کردن کاربر\n"
                "`/enable نام` - فعال کردن کاربر\n"
                "`/reset نام` - صفر کردن مصرف\n"
                "`/addaddr آدرس` - افزودن آی‌پی تمیز\n"
                "`/help` - راهنما\n\n"
                "📢 **کانال:** @CbeeNet",
                parse_mode="Markdown"
            )
        
        @bot.message_handler(commands=['stats'])
        async def stats_cmd(message):
            if not is_admin_chat(message.chat.id, admin_id):
                return
            
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            total_traffic = sum(link.get("used", 0) for link in LINKS.values())
            active_links = sum(1 for link in LINKS.values() if link.get("active", True))
            
            await bot.reply_to(
                message,
                f"📊 **وضعیت پنل**\n\n"
                f"💻 **CPU:** {cpu}%\n"
                f"🧠 **RAM:** {mem.percent}%\n"
                f"📡 **اینباندها:** {len(LINKS)} (فعال: {active_links})\n"
                f"📦 **ترافیک کل:** {format_bytes(total_traffic)}\n"
                f"🔗 **کانال:** @CbeeNet",
                parse_mode="Markdown"
            )
        
        @bot.message_handler(commands=['users'])
        async def users_cmd(message):
            if not is_admin_chat(message.chat.id, admin_id):
                return
            
            if not LINKS:
                await bot.reply_to(message, "❌ هیچ کاربری وجود ندارد")
                return
            
            text = "👥 **لیست کاربران:**\n\n"
            for name, data in LINKS.items():
                status = "🟢" if data.get("active", True) else "🔴"
                used = data.get("used", 0)
                limit = data.get("limit", 0)
                limit_str = format_bytes(limit) if limit > 0 else "♾️"
                expiry = data.get("expires_at")
                expiry_str = format_date(expiry) if expiry else "بدون انقضا"
                text += f"{status} **{name}**\n"
                text += f"   مصرف: {format_bytes(used)} / {limit_str}\n"
                text += f"   انقضا: {expiry_str}\n\n"
            
            await bot.reply_to(message, text, parse_mode="Markdown")
        
        @bot.message_handler(commands=['create'])
        async def create_cmd(message):
            if not is_admin_chat(message.chat.id, admin_id):
                return
            
            parts = message.text.split()
            if len(parts) < 4:
                await bot.reply_to(
                    message,
                    "❌ **فرمت اشتباه**\n"
                    "استفاده: `/create نام حجم_GB روز`\n"
                    "مثال: `/create ali 10 30`",
                    parse_mode="Markdown"
                )
                return
            
            name = parts[1]
            try:
                limit_gb = int(parts[2])
                days = int(parts[3])
            except ValueError:
                await bot.reply_to(message, "❌ حجم و روز باید عدد باشند")
                return
            
            if not re.match(r'^[a-zA-Z0-9_\-]+$', name):
                await bot.reply_to(message, "❌ نام باید فقط انگلیسی، عدد، زیرخط یا خط تیره باشد")
                return
            
            if name in LINKS:
                await bot.reply_to(message, f"❌ نام `{name}` قبلاً وجود دارد", parse_mode="Markdown")
                return
            
            uid = str(uuid.uuid4())
            path = f"/ws/{uid}"
            
            expires_at = None
            if days > 0:
                expires_at = (datetime.now() + timedelta(days=days)).isoformat()
            
            LINKS[name] = {
                "uid": uid,
                "name": name,
                "path": path,
                "limit": limit_gb * 1024 * 1024 * 1024 if limit_gb > 0 else 0,
                "used": 0,
                "expires_at": expires_at,
                "max_ips": 0,
                "active": True,
                "created_at": datetime.now().isoformat(),
                "remark": name,
                "protocol": "vless"
            }
            
            save_db()
            
            domain = get_domain()
            vless_link = make_vless_link(uid, domain, path, name)
            sub_link = f"{get_base_url()}/sub/{uid}"
            
            await bot.reply_to(
                message,
                f"✅ **کاربر `{name}` ساخته شد!**\n\n"
                f"🔗 **لینک VLESS:**\n`{vless_link}`\n\n"
                f"📋 **لینک اشتراک:**\n`{sub_link}`\n\n"
                f"📊 **محدودیت:** {limit_gb} GB\n"
                f"📅 **انقضا:** {days} روز",
                parse_mode="Markdown"
            )
        
        @bot.message_handler(commands=['disable', 'enable', 'reset'])
        async def toggle_reset_cmd(message):
            if not is_admin_chat(message.chat.id, admin_id):
                return
            
            parts = message.text.split()
            if len(parts) != 2:
                cmd = parts[0].replace('/', '')
                await bot.reply_to(
                    message,
                    f"❌ استفاده: `/{cmd} نام`\nمثال: `/{cmd} ali`",
                    parse_mode="Markdown"
                )
                return
            
            name = parts[1]
            if name not in LINKS:
                await bot.reply_to(message, f"❌ کاربر `{name}` یافت نشد", parse_mode="Markdown")
                return
            
            cmd = message.text.split()[0].replace('/', '')
            
            if cmd == 'disable':
                LINKS[name]["active"] = False
                await bot.reply_to(message, f"⏹️ کاربر `{name}` غیرفعال شد", parse_mode="Markdown")
            elif cmd == 'enable':
                LINKS[name]["active"] = True
                await bot.reply_to(message, f"▶️ کاربر `{name}` فعال شد", parse_mode="Markdown")
            elif cmd == 'reset':
                LINKS[name]["used"] = 0
                await bot.reply_to(message, f"🔄 مصرف کاربر `{name}` صفر شد", parse_mode="Markdown")
            
            save_db()
        
        @bot.message_handler(commands=['addaddr'])
        async def addaddr_cmd(message):
            if not is_admin_chat(message.chat.id, admin_id):
                return
            
            parts = message.text.split()
            if len(parts) != 2:
                await bot.reply_to(
                    message,
                    "❌ استفاده: `/addaddr آدرس`\nمثال: `/addaddr 104.21.0.1`",
                    parse_mode="Markdown"
                )
                return
            
            address = parts[1]
            if not address or len(address) < 3:
                await bot.reply_to(message, "❌ آدرس نامعتبر")
                return
            
            if address in CUSTOM_ADDRESSES:
                await bot.reply_to(message, f"❌ آدرس `{address}` قبلاً وجود دارد", parse_mode="Markdown")
                return
            
            CUSTOM_ADDRESSES.append(address)
            save_db()
            await bot.reply_to(message, f"✅ آدرس `{address}` افزوده شد", parse_mode="Markdown")
        
        @bot.message_handler(commands=['help'])
        async def help_cmd(message):
            if not is_admin_chat(message.chat.id, admin_id):
                return
            
            await bot.reply_to(
                message,
                "📖 **راهنمای ربات**\n\n"
                "`/stats` - وضعیت پنل\n"
                "`/users` - لیست کاربران\n"
                "`/create نام حجم_GB روز` - ساخت کاربر\n"
                "`/disable نام` - غیرفعال کردن\n"
                "`/enable نام` - فعال کردن\n"
                "`/reset نام` - صفر کردن مصرف\n"
                "`/addaddr آدرس` - افزودن آی‌پی تمیز\n"
                "`/help` - این پیام\n\n"
                "📢 **کانال:** @CbeeNet",
                parse_mode="Markdown"
            )
        
        async def telegram_notifier():
            while True:
                try:
                    await asyncio.sleep(60)
                    
                    if not CONFIG.get("telegram_token") or not CONFIG.get("telegram_admin_id"):
                        continue
                    
                    if not TELEGRAM_BOT_INSTANCE:
                        continue
                    
                    for name, data in LINKS.items():
                        if not data.get("active", True):
                            continue
                        
                        uid = data.get("uid", "")
                        
                        limit = data.get("limit", 0)
                        used = data.get("used", 0)
                        if limit > 0 and used >= limit:
                            key = f"quota_{uid}"
                            if key not in NOTIFIED_UIDS:
                                NOTIFIED_UIDS.add(key)
                                try:
                                    await TELEGRAM_BOT_INSTANCE.send_message(
                                        admin_id,
                                        f"⚠️ **هشدار اتمام حجم!**\n\n"
                                        f"کاربر: `{name}`\n"
                                        f"مصرف: {format_bytes(used)} / {format_bytes(limit)}",
                                        parse_mode="Markdown"
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to send quota alert: {e}")
                        
                        expires_at = data.get("expires_at")
                        if expires_at:
                            try:
                                expiry = datetime.fromisoformat(expires_at)
                                if expiry < datetime.now():
                                    key = f"expiry_{uid}"
                                    if key not in NOTIFIED_UIDS:
                                        NOTIFIED_UIDS.add(key)
                                        try:
                                            await TELEGRAM_BOT_INSTANCE.send_message(
                                                admin_id,
                                                f"⏰ **هشدار انقضا!**\n\n"
                                                f"کاربر: `{name}`\n"
                                                f"تاریخ انقضا: {format_date(expires_at)}",
                                                parse_mode="Markdown"
                                            )
                                        except Exception as e:
                                            logger.error(f"Failed to send expiry alert: {e}")
                            except:
                                pass
                            
                except Exception as e:
                    logger.error(f"Telegram notifier error: {e}")
        
        TELEGRAM_BOT_TASK = asyncio.create_task(bot.infinity_polling())
        asyncio.create_task(telegram_notifier())
        
        logger.info("📢 Telegram bot started successfully")
        
    except ImportError:
        logger.warning("⚠️ pyTelegramBotAPI not installed. Telegram bot disabled.")
    except Exception as e:
        logger.error(f"❌ Failed to start Telegram bot: {e}")

async def stop_telegram_bot():
    global TELEGRAM_BOT_TASK, TELEGRAM_BOT_INSTANCE
    
    if TELEGRAM_BOT_TASK:
        TELEGRAM_BOT_TASK.cancel()
        try:
            await TELEGRAM_BOT_TASK
        except:
            pass
        TELEGRAM_BOT_TASK = None
    
    TELEGRAM_BOT_INSTANCE = None
    logger.info("📢 Telegram bot stopped")

# ==================== قالب‌های HTML ====================

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="fa" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ورود · SLV Panel</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a2e;
            --bg-card-hover: #252540;
            --text-primary: #e8e8f0;
            --text-secondary: #a0a0b8;
            --text-muted: #6a6a8a;
            --border-color: #2a2a4a;
            --honey: #f5a623;
            --honey-dark: #d48f1a;
            --honey-glow: rgba(245, 166, 35, 0.15);
            --shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
            --radius: 16px;
            --transition: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background-image: radial-gradient(ellipse at 20% 50%, rgba(245, 166, 35, 0.05) 0%, transparent 60%),
                              radial-gradient(ellipse at 80% 50%, rgba(245, 166, 35, 0.03) 0%, transparent 60%);
        }
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 5 L55 17.5 L55 42.5 L30 55 L5 42.5 L5 17.5 Z' fill='none' stroke='rgba(245,166,35,0.05)' stroke-width='1'/%3E%3C/svg%3E");
            background-size: 60px 60px;
            pointer-events: none;
            z-index: 0;
        }
        .login-wrapper { position: relative; z-index: 1; width: 100%; max-width: 420px; padding: 20px; }
        .login-box {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius);
            padding: 40px 32px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(20px);
            position: relative;
            overflow: hidden;
        }
        .login-box::before {
            content: '';
            position: absolute;
            top: -50%; left: -50%;
            width: 200%; height: 200%;
            background: conic-gradient(from 0deg at 50% 50%, transparent 0%, var(--honey-glow) 25%, transparent 50%, var(--honey-glow) 75%, transparent 100%);
            animation: rotateGlow 10s linear infinite;
            opacity: 0.1;
            pointer-events: none;
        }
        @keyframes rotateGlow { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .login-header { text-align: center; margin-bottom: 32px; position: relative; }
        .login-header .hex-icon {
            display: inline-block;
            width: 72px; height: 83px;
            background: linear-gradient(135deg, var(--honey), var(--honey-dark));
            clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
            line-height: 83px;
            font-size: 2.2rem;
            margin-bottom: 16px;
            box-shadow: 0 4px 20px rgba(245, 166, 35, 0.3);
        }
        .login-header h1 { font-size: 1.8rem; font-weight: 700; background: linear-gradient(135deg, var(--honey), #ffd700); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
        .login-header p { color: var(--text-secondary); font-size: 0.9rem; margin-top: 4px; }
        .login-form { position: relative; }
        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; color: var(--text-secondary); font-size: 0.85rem; font-weight: 500; margin-bottom: 6px; }
        .form-group input {
            width: 100%;
            padding: 12px 16px;
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            color: var(--text-primary);
            font-size: 1rem;
            transition: var(--transition);
            outline: none;
        }
        .form-group input:focus { border-color: var(--honey); box-shadow: 0 0 0 3px var(--honey-glow); }
        .form-group input::placeholder { color: var(--text-muted); }
        .btn-login {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, var(--honey), var(--honey-dark));
            border: none;
            border-radius: 10px;
            color: #fff;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: var(--transition);
            position: relative;
            overflow: hidden;
        }
        .btn-login:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(245, 166, 35, 0.3); }
        .btn-login:active { transform: translateY(0); }
        #loginError {
            color: #ff6b6b;
            font-size: 0.85rem;
            text-align: center;
            margin-top: 12px;
            display: none;
            padding: 8px 12px;
            background: rgba(255, 107, 107, 0.1);
            border-radius: 8px;
            border: 1px solid rgba(255, 107, 107, 0.2);
        }
        .login-footer { text-align: center; margin-top: 24px; color: var(--text-muted); font-size: 0.8rem; }
        .login-footer .heart { display: inline-block; animation: pulse 1.5s infinite; color: #ff6b6b; }
        @keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.3); } }
        .login-footer a { color: var(--honey); text-decoration: none; }
        .login-footer a:hover { text-decoration: underline; }
        @media (max-width: 480px) {
            .login-box { padding: 28px 20px; }
            .login-header h1 { font-size: 1.4rem; }
            .login-header .hex-icon { width: 56px; height: 65px; line-height: 65px; font-size: 1.8rem; }
        }
    </style>
</head>
<body>
    <div class="login-wrapper">
        <div class="login-box">
            <div class="login-header">
                <div class="hex-icon">🐝</div>
                <h1>SLV Panel</h1>
                <p>ورود به پنل مدیریت</p>
            </div>
            <form class="login-form" id="loginForm" onsubmit="login(event)">
                <div class="form-group">
                    <label for="username">نام کاربری</label>
                    <input type="text" id="username" placeholder="admin" value="admin" required>
                </div>
                <div class="form-group">
                    <label for="password">رمز عبور</label>
                    <input type="password" id="password" placeholder="رمز عبور خود را وارد کنید" required>
                </div>
                <button type="submit" class="btn-login">🚀 ورود به پنل</button>
                <div id="loginError"></div>
            </form>
            <div class="login-footer">
                ساخته شده با <span class="heart">💛</span> توسط <strong style="color: var(--honey);">CBeeNet</strong>
                <br><span style="font-size: 0.75rem;">📢 <a href="https://t.me/CbeeNet" target="_blank">@CbeeNet</a></span>
            </div>
        </div>
    </div>
    <script>
    async function login(e) {
        e.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        const errorDiv = document.getElementById('loginError');
        errorDiv.style.display = 'none';
        errorDiv.textContent = '';
        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData.toString()
            });
            const data = await res.json();
            if (res.ok && data.status === 'ok') {
                window.location.href = '/dashboard';
            } else {
                errorDiv.textContent = data.detail || 'نام کاربری یا رمز عبور اشتباه است';
                errorDiv.style.display = 'block';
            }
        } catch(err) {
            errorDiv.textContent = 'خطا در ارتباط با سرور';
            errorDiv.style.display = 'block';
            console.error('Login error:', err);
        }
    }
    </script>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fa" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>داشبورد · SLV Panel</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a2e;
            --bg-card-hover: #252540;
            --text-primary: #e8e8f0;
            --text-secondary: #a0a0b8;
            --text-muted: #6a6a8a;
            --border-color: #2a2a4a;
            --honey: #f5a623;
            --honey-dark: #d48f1a;
            --honey-glow: rgba(245, 166, 35, 0.15);
            --shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
            --radius: 16px;
            --transition: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            --success: #2ecc71;
            --danger: #e74c3c;
            --warning: #f39c12;
        }
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: var(--bg-primary); color: var(--text-primary); min-height: 100vh; }
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 5 L55 17.5 L55 42.5 L30 55 L5 42.5 L5 17.5 Z' fill='none' stroke='rgba(245,166,35,0.04)' stroke-width='1'/%3E%3C/svg%3E");
            background-size: 60px 60px;
            pointer-events: none;
            z-index: 0;
        }
        .header {
            position: sticky;
            top: 0; z-index: 100;
            background: rgba(10, 10, 15, 0.85);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-color);
            padding: 16px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header-left { display: flex; align-items: center; gap: 16px; }
        .header .hex-icon {
            display: inline-block;
            width: 40px; height: 46px;
            background: linear-gradient(135deg, var(--honey), var(--honey-dark));
            clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
            line-height: 46px;
            text-align: center;
            font-size: 1.2rem;
        }
        .header h1 { font-size: 1.4rem; font-weight: 700; background: linear-gradient(135deg, var(--honey), #ffd700); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
        .header-right { display: flex; align-items: center; gap: 16px; }
        .btn-logout {
            padding: 8px 20px;
            background: transparent;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: var(--transition);
        }
        .btn-logout:hover { background: var(--bg-card); color: var(--text-primary); }
        .container { max-width: 1400px; margin: 0 auto; padding: 24px 32px 60px; position: relative; z-index: 1; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 32px;
        }
        .stat-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius);
            padding: 20px 24px;
            transition: var(--transition);
        }
        .stat-card:hover { border-color: var(--honey); box-shadow: 0 4px 20px var(--honey-glow); }
        .stat-card .label { color: var(--text-muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; }
        .stat-card .value { font-size: 2rem; font-weight: 700; margin-top: 4px; background: linear-gradient(135deg, var(--text-primary), var(--text-secondary)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
        .tabs { display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap; }
        .tab-btn {
            padding: 10px 24px;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: var(--transition);
            font-size: 0.9rem;
        }
        .tab-btn:hover { border-color: var(--honey); color: var(--text-primary); }
        .tab-btn.active { background: linear-gradient(135deg, var(--honey), var(--honey-dark)); border-color: var(--honey); color: #fff; }
        .hex-grid {
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin-bottom: 32px;
            justify-content: center;
        }
        .hex-card {
            width: 140px; height: 160px;
            background: linear-gradient(145deg, var(--bg-secondary), var(--bg-card));
            clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: var(--text-primary);
            font-weight: 600;
            font-size: 0.9rem;
            cursor: pointer;
            transition: var(--transition);
            border: 1px solid var(--border-color);
            padding: 20px;
            text-align: center;
        }
        .hex-card:hover { transform: scale(1.05) translateY(-4px); border-color: var(--honey); box-shadow: 0 8px 30px var(--honey-glow); }
        .hex-card .protocol-icon { font-size: 1.8rem; margin-bottom: 8px; }
        .hex-card .badge { font-size: 0.65rem; color: var(--text-muted); margin-top: 4px; }
        .table-wrapper {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius);
            overflow: hidden;
            margin-top: 16px;
        }
        .table-wrapper table { width: 100%; border-collapse: collapse; }
        .table-wrapper th {
            background: var(--bg-primary);
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 14px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }
        .table-wrapper td { padding: 14px 16px; border-bottom: 1px solid var(--border-color); color: var(--text-primary); font-size: 0.9rem; }
        .table-wrapper tr:hover td { background: var(--bg-card); }
        .status-badge {
            display: inline-block;
            padding: 3px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .status-badge.active { background: rgba(46, 204, 113, 0.2); color: var(--success); }
        .status-badge.inactive { background: rgba(231, 76, 60, 0.2); color: var(--danger); }
        .btn-sm {
            padding: 4px 12px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.75rem;
            transition: var(--transition);
            margin-right: 4px;
        }
        .btn-sm.primary { background: var(--honey); color: #fff; }
        .btn-sm.primary:hover { background: var(--honey-dark); }
        .btn-sm.danger { background: var(--danger); color: #fff; }
        .btn-sm.danger:hover { background: #c0392b; }
        .btn-sm.success { background: var(--success); color: #fff; }
        .btn-sm.success:hover { background: #27ae60; }
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(10px);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }
        .modal-overlay.show { display: flex; }
        .modal {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius);
            padding: 32px;
            max-width: 500px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }
        .modal h2 { margin-bottom: 20px; color: var(--text-primary); }
        .modal .form-group { margin-bottom: 16px; }
        .modal .form-group label { display: block; color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 4px; }
        .modal .form-group input, .modal .form-group select {
            width: 100%;
            padding: 10px 14px;
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-size: 0.95rem;
        }
        .modal .form-group input:focus { border-color: var(--honey); outline: none; }
        .modal .modal-actions { display: flex; gap: 12px; margin-top: 20px; justify-content: flex-end; }
        .modal .modal-actions button { padding: 10px 24px; border: none; border-radius: 8px; cursor: pointer; font-size: 0.9rem; transition: var(--transition); }
        .modal .modal-actions .btn-cancel { background: var(--bg-primary); color: var(--text-secondary); }
        .modal .modal-actions .btn-cancel:hover { background: var(--bg-card); }
        .modal .modal-actions .btn-submit { background: linear-gradient(135deg, var(--honey), var(--honey-dark)); color: #fff; }
        .modal .modal-actions .btn-submit:hover { box-shadow: 0 4px 20px var(--honey-glow); }
        .footer {
            text-align: center;
            padding: 24px 0;
            color: var(--text-muted);
            font-size: 0.85rem;
            border-top: 1px solid var(--border-color);
            margin-top: 40px;
        }
        .footer .heart { display: inline-block; animation: pulse 1.5s infinite; color: #ff6b6b; }
        @keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.3); } }
        .footer a { color: var(--honey); text-decoration: none; }
        .footer a:hover { text-decoration: underline; }
        @media (max-width: 768px) {
            .header { padding: 12px 16px; flex-wrap: wrap; gap: 8px; }
            .header h1 { font-size: 1.1rem; }
            .container { padding: 16px; }
            .stats-grid { grid-template-columns: 1fr 1fr; }
            .hex-card { width: 110px; height: 130px; font-size: 0.75rem; }
            .table-wrapper { overflow-x: auto; }
        }
        @media (max-width: 480px) {
            .stats-grid { grid-template-columns: 1fr; }
            .header-right .btn-logout { padding: 6px 12px; font-size: 0.8rem; }
        }
    </style>
</head>
<body>
    <header class="header">
        <div class="header-left">
            <div class="hex-icon">🐝</div>
            <h1>SLV Panel</h1>
        </div>
        <div class="header-right">
            <button class="btn-logout" onclick="logout()">🚪 خروج</button>
        </div>
    </header>
    <div class="container">
        <div class="stats-grid" id="statsGrid">
            <div class="stat-card"><div class="label">اتصالات فعال</div><div class="value" id="activeConns">0</div></div>
            <div class="stat-card"><div class="label">ترافیک کل</div><div class="value" id="totalTraffic">0 MB</div></div>
            <div class="stat-card"><div class="label">اینباندها</div><div class="value" id="totalLinks">0</div></div>
            <div class="stat-card"><div class="label">فعال</div><div class="value" id="activeLinks">0</div></div>
        </div>
        <div class="tabs">
            <button class="tab-btn active" data-tab="links" onclick="switchTab('links')">🔗 اینباندها</button>
            <button class="tab-btn" data-tab="addresses" onclick="switchTab('addresses')">🌐 آی‌پی تمیز</button>
            <button class="tab-btn" data-tab="settings" onclick="switchTab('settings')">⚙️ تنظیمات</button>
        </div>
        <div id="tab-links" class="tab-content">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:16px;">
                <h3 style="color:var(--text-primary);">مدیریت اینباندها</h3>
                <button class="btn-sm primary" style="padding:10px 20px; font-size:0.9rem;" onclick="showCreateModal()">➕ ساخت اینباند جدید</button>
            </div>
            <div class="hex-grid" id="protocolGrid">
                <div class="hex-card" onclick="filterLinks('all')"><div class="protocol-icon">📦</div><div>همه</div><div class="badge" id="allCount">0</div></div>
                <div class="hex-card" onclick="filterLinks('vless')"><div class="protocol-icon">🚀</div><div>VLESS</div><div class="badge" id="vlessCount">0</div></div>
                <div class="hex-card" onclick="filterLinks('vmess')"><div class="protocol-icon">🔐</div><div>VMess</div><div class="badge" id="vmessCount">0</div></div>
                <div class="hex-card" onclick="filterLinks('trojan')"><div class="protocol-icon">🛡️</div><div>Trojan</div><div class="badge" id="trojanCount">0</div></div>
            </div>
            <div class="table-wrapper" id="linksTable">
                <table><thead><tr><th>نام</th><th>پروتکل</th><th>مصرف</th><th>سقف</th><th>انقضا</th><th>وضعیت</th><th>عملیات</th></tr></thead><tbody id="linksBody"><tr><td colspan="7" style="text-align:center; color:var(--text-muted);">در حال بارگذاری...</td></tr></tbody></table>
            </div>
        </div>
        <div id="tab-addresses" class="tab-content" style="display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:16px;">
                <h3 style="color:var(--text-primary);">مدیریت آی‌پی‌های تمیز</h3>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                    <button class="btn-sm primary" onclick="showAddAddressModal()">➕ افزودن</button>
                    <button class="btn-sm danger" onclick="deleteAllAddresses()">🗑️ حذف همه</button>
                </div>
            </div>
            <div class="table-wrapper"><table><thead><tr><th>#</th><th>آدرس</th><th>عملیات</th></tr></thead><tbody id="addressesBody"><tr><td colspan="3" style="text-align:center; color:var(--text-muted);">در حال بارگذاری...</td></tr></tbody></table></div>
        </div>
        <div id="tab-settings" class="tab-content" style="display:none;">
            <h3 style="color:var(--text-primary); margin-bottom:16px;">تنظیمات پنل</h3>
            <div class="table-wrapper" style="padding:24px;">
                <form id="settingsForm" onsubmit="saveSettings(event)">
                    <div class="form-group"><label for="tgToken">توکن ربات تلگرام</label><input type="text" id="tgToken" placeholder="توکن ربات خود را وارد کنید" style="width:100%; padding:10px 14px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:8px; color:var(--text-primary);"></div>
                    <div class="form-group"><label for="tgAdminId">آیدی ادمین تلگرام</label><input type="text" id="tgAdminId" placeholder="آیدی عددی ادمین را وارد کنید" style="width:100%; padding:10px 14px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:8px; color:var(--text-primary);"></div>
                    <button type="submit" class="btn-sm primary" style="padding:10px 24px; font-size:0.9rem;">💾 ذخیره تنظیمات</button>
                    <span id="settingsStatus" style="margin-left:12px; color:var(--success);"></span>
                </form>
                <hr style="border-color:var(--border-color); margin:24px 0;">
                <h4 style="color:var(--text-secondary); margin-bottom:12px;">تغییر رمز عبور</h4>
                <form id="passwordForm" onsubmit="changePassword(event)">
                    <div class="form-group"><label for="currentPassword">رمز فعلی</label><input type="password" id="currentPassword" placeholder="رمز فعلی" style="width:100%; padding:10px 14px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:8px; color:var(--text-primary);"></div>
                    <div class="form-group"><label for="newPassword">رمز جدید</label><input type="password" id="newPassword" placeholder="رمز جدید" style="width:100%; padding:10px 14px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:8px; color:var(--text-primary);"></div>
                    <button type="submit" class="btn-sm primary" style="padding:10px 24px; font-size:0.9rem;">🔑 تغییر رمز</button>
                    <span id="passwordStatus" style="margin-left:12px; color:var(--success);"></span>
                </form>
            </div>
        </div>
        <div class="footer">
            ساخته شده با <span class="heart">💛</span> توسط <strong style="color: var(--honey);">CBeeNet</strong>
            <br><span style="font-size: 0.75rem;">📢 <a href="https://t.me/CbeeNet" target="_blank">@CbeeNet</a></span>
        </div>
    </div>
    <div class="modal-overlay" id="createModal">
        <div class="modal">
            <h2>➕ ساخت اینباند جدید</h2>
            <form id="createForm" onsubmit="createLink(event)">
                <div class="form-group"><label for="linkName">نام (فقط انگلیسی)</label><input type="text" id="linkName" placeholder="مثال: my-user" required></div>
                <div class="form-group"><label for="linkLimit">محدودیت حجم (GB) - 0 = نامحدود</label><input type="number" id="linkLimit" value="10" min="0"></div>
                <div class="form-group"><label for="linkDays">مدت اعتبار (روز) - 0 = بدون انقضا</label><input type="number" id="linkDays" value="30" min="0"></div>
                <div class="form-group"><label for="linkMaxIps">حداکثر IP همزمان - 0 = نامحدود</label><input type="number" id="linkMaxIps" value="0" min="0"></div>
                <div class="form-group"><label for="linkProtocol">پروتکل</label>
                    <select id="linkProtocol">
                        <option value="vless">VLESS</option>
                        <option value="vmess">VMess</option>
                        <option value="trojan">Trojan</option>
                    </select>
                </div>
                <div class="modal-actions">
                    <button type="button" class="btn-cancel" onclick="closeModal('createModal')">انصراف</button>
                    <button type="submit" class="btn-submit">🚀 ساخت</button>
                </div>
            </form>
            <div id="createResult" style="margin-top:12px;"></div>
        </div>
    </div>
    <div class="modal-overlay" id="addressModal">
        <div class="modal">
            <h2>➕ افزودن آی‌پی تمیز</h2>
            <form id="addressForm" onsubmit="addAddress(event)">
                <div class="form-group"><label for="addressInput">آدرس (IP یا دامنه)</label><input type="text" id="addressInput" placeholder="مثال: 104.21.0.1 یا cf.example.com" required></div>
                <div class="modal-actions">
                    <button type="button" class="btn-cancel" onclick="closeModal('addressModal')">انصراف</button>
                    <button type="submit" class="btn-submit">➕ افزودن</button>
                </div>
            </form>
            <div id="addressResult" style="margin-top:12px;"></div>
        </div>
    </div>
    <script>
        let currentFilter = 'all';
        let linksData = {};
        let addressesData = [];
        
        async function apiRequest(url, options = {}) {
            const res = await fetch(url, { ...options, credentials: 'include' });
            if (res.status === 401) { window.location.href = '/login'; return null; }
            return res;
        }
        
        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
        
        function formatDate(dateStr) {
            if (!dateStr) return 'بدون انقضا';
            try { const d = new Date(dateStr); return d.toLocaleDateString('fa-IR'); } catch { return dateStr; }
        }
        
        function switchTab(tab) {
            document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById('tab-' + tab).style.display = 'block';
            document.querySelector(`.tab-btn[data-tab="${tab}"]`).classList.add('active');
            if (tab === 'links') loadLinks();
            else if (tab === 'addresses') loadAddresses();
            else if (tab === 'settings') loadSettings();
        }
        
        async function loadStats() {
            try {
                const res = await apiRequest('/stats');
                if (!res) return;
                const data = await res.json();
                document.getElementById('activeConns').textContent = data.active_connections || 0;
                document.getElementById('totalTraffic').textContent = formatBytes(data.total_traffic || 0);
                document.getElementById('totalLinks').textContent = data.total_links || 0;
                document.getElementById('activeLinks').textContent = data.active_links || 0;
            } catch(e) { console.error('Error loading stats:', e); }
        }
        
        async function loadLinks() {
            try {
                const res = await apiRequest('/api/links');
                if (!res) return;
                const data = await res.json();
                linksData = data.links || {};
                const names = Object.keys(linksData);
                document.getElementById('allCount').textContent = names.length;
                document.getElementById('vlessCount').textContent = names.filter(n => linksData[n].protocol === 'vless').length;
                document.getElementById('vmessCount').textContent = names.filter(n => linksData[n].protocol === 'vmess').length;
                document.getElementById('trojanCount').textContent = names.filter(n => linksData[n].protocol === 'trojan').length;
                renderLinks();
            } catch(e) { console.error('Error loading links:', e); }
        }
        
        function renderLinks() {
            const tbody = document.getElementById('linksBody');
            const names = Object.keys(linksData);
            if (names.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--text-muted);">هیچ اینباندی وجود ندارد</td></tr>';
                return;
            }
            let filtered = names;
            if (currentFilter !== 'all') {
                filtered = names.filter(n => linksData[n].protocol === currentFilter);
            }
            let html = '';
            for (const name of filtered) {
                const link = linksData[name];
                const isActive = link.active !== false;
                const isExp = link.expires_at ? new Date(link.expires_at) < new Date() : false;
                const status = isActive && !isExp ? 'فعال' : (isExp ? 'منقضی' : 'غیرفعال');
                const statusClass = isActive && !isExp ? 'active' : 'inactive';
                html += `<tr>
                    <td><strong>${name}</strong></td>
                    <td>${(link.protocol || 'vless').toUpperCase()}</td>
                    <td>${formatBytes(link.used || 0)}</td>
                    <td>${link.limit > 0 ? formatBytes(link.limit) : '♾️'}</td>
                    <td>${formatDate(link.expires_at)}</td>
                    <td><span class="status-badge ${statusClass}">${status}</span></td>
                    <td>
                        <button class="btn-sm primary" onclick="copyLink('${name}')">📋 کپی</button>
                        <button class="btn-sm ${isActive ? 'danger' : 'success'}" onclick="toggleLink('${name}')">${isActive ? '⏹️' : '▶️'}</button>
                        <button class="btn-sm danger" onclick="deleteLink('${name}')">🗑️</button>
                    </td>
                </tr>`;
            }
            tbody.innerHTML = html;
        }
        
        function filterLinks(protocol) {
            currentFilter = protocol;
            document.querySelectorAll('.hex-card').forEach(el => el.style.borderColor = 'var(--border-color)');
            document.querySelectorAll('.hex-card').forEach(el => {
                if (el.textContent.includes(protocol === 'all' ? 'همه' : protocol.toUpperCase())) {
                    el.style.borderColor = 'var(--honey)';
                }
            });
            renderLinks();
        }
        
        async function createLink(e) {
            e.preventDefault();
            const name = document.getElementById('linkName').value.trim();
            const limit = parseInt(document.getElementById('linkLimit').value) || 0;
            const days = parseInt(document.getElementById('linkDays').value) || 0;
            const maxIps = parseInt(document.getElementById('linkMaxIps').value) || 0;
            const protocol = document.getElementById('linkProtocol').value;
            const resultDiv = document.getElementById('createResult');
            if (!name) { resultDiv.innerHTML = '<span style="color:var(--danger);">❌ نام را وارد کنید</span>'; return; }
            try {
                const formData = new URLSearchParams();
                formData.append('name', name);
                formData.append('limit_gb', String(limit));
                formData.append('days', String(days));
                formData.append('max_ips', String(maxIps));
                formData.append('protocol', protocol);
                const res = await apiRequest('/api/links', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formData.toString()
                });
                if (!res) return;
                const data = await res.json();
                if (res.ok && data.status === 'ok') {
                    resultDiv.innerHTML = `<span style="color:var(--success);">✅ اینباند "${name}" ساخته شد!</span><br><small style="color:var(--text-muted);">لینک: <code>${data.share_link || ''}</code></small>`;
                    closeModal('createModal');
                    loadLinks();
                    loadStats();
                } else {
                    resultDiv.innerHTML = `<span style="color:var(--danger);">❌ ${data.detail || 'خطا در ساخت'}</span>`;
                }
            } catch(e) {
                resultDiv.innerHTML = `<span style="color:var(--danger);">❌ خطا: ${e.message}</span>`;
            }
        }
        
        async function toggleLink(name) {
            if (!confirm(`تغییر وضعیت "${name}"؟`)) return;
            try {
                const link = linksData[name];
                const newStatus = link.active === false;
                const formData = new URLSearchParams();
                formData.append('active', String(newStatus));
                const res = await apiRequest(`/api/links/${encodeURIComponent(name)}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formData.toString()
                });
                if (res && res.ok) { loadLinks(); loadStats(); }
            } catch(e) { console.error('Error toggling link:', e); }
        }
        
        async function deleteLink(name) {
            if (!confirm(`آیا از حذف "${name}" مطمئن هستید؟`)) return;
            try {
                const res = await apiRequest(`/api/links/${encodeURIComponent(name)}`, { method: 'DELETE' });
                if (res && res.ok) { loadLinks(); loadStats(); }
            } catch(e) { console.error('Error deleting link:', e); }
        }
        
        function copyLink(name) {
            const link = linksData[name];
            if (!link) return;
            const domain = window.location.hostname;
            const protocol = link.protocol || 'vless';
            let config = '';
            if (protocol === 'vless') {
                config = `vless://${link.uid}@${domain}:443?encryption=none&security=tls&type=ws&host=${domain}&path=${link.path || '/ws/'+link.uid}&sni=${domain}&fp=chrome&alpn=http/1.1#SLV-${name}`;
            } else if (protocol === 'vmess') {
                const vmessConfig = { v: "2", ps: `SLV-${name}`, add: domain, port: "443", id: link.uid, aid: "0", net: "ws", type: "none", host: domain, path: link.path || '/ws/'+link.uid, tls: "tls" };
                config = `vmess://${btoa(JSON.stringify(vmessConfig))}`;
            } else if (protocol === 'trojan') {
                config = `trojan://${link.uid}@${domain}:443?path=${encodeURIComponent(link.path || '/ws/'+link.uid)}&security=tls&type=ws&host=${domain}&sni=${domain}#SLV-${name}`;
            }
            navigator.clipboard.writeText(config).then(() => { alert('✅ لینک کپی شد!'); }).catch(() => { prompt('لینک را کپی کنید:', config); });
        }
        
        function showCreateModal() {
            document.getElementById('createModal').classList.add('show');
            document.getElementById('createResult').innerHTML = '';
            document.getElementById('createForm').reset();
        }
        
        async function loadAddresses() {
            try {
                const res = await apiRequest('/api/addresses');
                if (!res) return;
                const data = await res.json();
                addressesData = data.addresses || [];
                renderAddresses();
            } catch(e) { console.error('Error loading addresses:', e); }
        }
        
        function renderAddresses() {
            const tbody = document.getElementById('addressesBody');
            if (addressesData.length === 0) {
                tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:var(--text-muted);">هیچ آدرسی وجود ندارد</td></tr>';
                return;
            }
            let html = '';
            for (let i = 0; i < addressesData.length; i++) {
                html += `<tr><td>${i+1}</td><td><code>${addressesData[i]}</code></td><td><button class="btn-sm danger" onclick="deleteAddress(${i})">🗑️</button></td></tr>`;
            }
            tbody.innerHTML = html;
        }
        
        async function addAddress(e) {
            e.preventDefault();
            const address = document.getElementById('addressInput').value.trim();
            const resultDiv = document.getElementById('addressResult');
            if (!address) { resultDiv.innerHTML = '<span style="color:var(--danger);">❌ آدرس را وارد کنید</span>'; return; }
            try {
                const formData = new URLSearchParams();
                formData.append('address', address);
                const res = await apiRequest('/api/addresses', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formData.toString()
                });
                if (!res) return;
                const data = await res.json();
                if (res.ok) {
                    resultDiv.innerHTML = `<span style="color:var(--success);">✅ آدرس "${address}" افزوده شد</span>`;
                    closeModal('addressModal');
                    loadAddresses();
                } else {
                    resultDiv.innerHTML = `<span style="color:var(--danger);">❌ ${data.detail || 'خطا'}</span>`;
                }
            } catch(e) {
                resultDiv.innerHTML = `<span style="color:var(--danger);">❌ خطا: ${e.message}</span>`;
            }
        }
        
        async function deleteAddress(index) {
            if (!confirm(`حذف آدرس "${addressesData[index]}"؟`)) return;
            try {
                const res = await apiRequest(`/api/addresses/${index}`, { method: 'DELETE' });
                if (res && res.ok) loadAddresses();
            } catch(e) { console.error('Error deleting address:', e); }
        }
        
        async function deleteAllAddresses() {
            if (!confirm('آیا از حذف همه آدرس‌ها مطمئن هستید؟')) return;
            try {
                const res = await apiRequest('/api/addresses', { method: 'DELETE' });
                if (res && res.ok) loadAddresses();
            } catch(e) { console.error('Error deleting all addresses:', e); }
        }
        
        function showAddAddressModal() {
            document.getElementById('addressModal').classList.add('show');
            document.getElementById('addressResult').innerHTML = '';
            document.getElementById('addressForm').reset();
        }
        
        async function loadSettings() {
            try {
                const res = await apiRequest('/api/settings');
                if (!res) return;
                const data = await res.json();
                document.getElementById('tgToken').value = data.telegram_token || '';
                document.getElementById('tgAdminId').value = data.telegram_admin_id || '';
            } catch(e) { console.error('Error loading settings:', e); }
        }
        
        async function saveSettings(e) {
            e.preventDefault();
            const token = document.getElementById('tgToken').value.trim();
            const adminId = document.getElementById('tgAdminId').value.trim();
            const statusEl = document.getElementById('settingsStatus');
            try {
                const formData = new URLSearchParams();
                formData.append('telegram_token', token);
                formData.append('telegram_admin_id', adminId);
                const res = await apiRequest('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formData.toString()
                });
                if (!res) return;
                if (res.ok) { statusEl.textContent = '✅ ذخیره شد'; statusEl.style.color = 'var(--success)'; }
                else { statusEl.textContent = '❌ خطا'; statusEl.style.color = 'var(--danger)'; }
            } catch(e) {
                statusEl.textContent = '❌ خطا در ارتباط';
                statusEl.style.color = 'var(--danger)';
            }
        }
        
        async function changePassword(e) {
            e.preventDefault();
            const current = document.getElementById('currentPassword').value;
            const newPass = document.getElementById('newPassword').value;
            const statusEl = document.getElementById('passwordStatus');
            if (!current || !newPass) {
                statusEl.textContent = '❌ هر دو فیلد را پر کنید';
                statusEl.style.color = 'var(--danger)';
                return;
            }
            try {
                const formData = new URLSearchParams();
                formData.append('current', current);
                formData.append('new', newPass);
                const res = await apiRequest('/api/change-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formData.toString()
                });
                if (!res) return;
                if (res.ok) {
                    statusEl.textContent = '✅ رمز با موفقیت تغییر کرد';
                    statusEl.style.color = 'var(--success)';
                    document.getElementById('passwordForm').reset();
                } else {
                    statusEl.textContent = `❌ ${data.detail || 'خطا'}`;
                    statusEl.style.color = 'var(--danger)';
                }
            } catch(e) {
                statusEl.textContent = '❌ خطا در ارتباط';
                statusEl.style.color = 'var(--danger)';
            }
        }
        
        function closeModal(id) { document.getElementById(id).classList.remove('show'); }
        document.querySelectorAll('.modal-overlay').forEach(el => {
            el.addEventListener('click', function(e) { if (e.target === this) this.classList.remove('show'); });
        });
        
        async function logout() {
            try { await apiRequest('/api/logout', { method: 'POST' }); } catch(e) {}
            window.location.href = '/login';
        }
        
        document.addEventListener('DOMContentLoaded', function() {
            loadStats();
            loadLinks();
            loadAddresses();
            loadSettings();
            setInterval(loadStats, 10000);
        });
    </script>
</body>
</html>
"""

# ==================== مسیرهای صفحات HTML ====================

@app.get("/")
async def root():
    return RedirectResponse(url="/login")

@app.get("/login")
async def login_page():
    return HTMLResponse(LOGIN_HTML)

@app.get("/dashboard")
async def dashboard_page(user: str = Depends(require_admin)):
    return HTMLResponse(DASHBOARD_HTML)

# ==================== Keep-Alive ====================

@app.on_event("startup")
async def start_keep_alive():
    async def keep_alive():
        while True:
            await asyncio.sleep(600)
            try:
                async with httpx.AsyncClient() as client:
                    await client.get(f"http://localhost:{os.environ.get('PORT', 8000)}/health")
                logger.info("💓 Keep-alive ping sent")
            except Exception as e:
                logger.error(f"Keep-alive error: {e}")
    
    asyncio.create_task(keep_alive())

# ==================== اجرا ====================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
