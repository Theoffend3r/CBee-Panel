from fastapi import APIRouter, HTTPException, Request, Depends
from typing import Optional, List
import uuid
import secrets
import hashlib
from datetime import datetime, timedelta

from storage.database import (
    get_users, get_inbounds, get_resellers,
    add_user, add_inbound, add_reseller,
    update_inbound, delete_inbound, load_state, save_state
)
from core.protocols import (
    generate_vless_config, generate_vmess_config, 
    generate_trojan_config, generate_shadowsocks_config,
    generate_socks_config, generate_http_config, 
    generate_https_config, generate_grpc_config, generate_quic_config,
    generate_share_link, PROTOCOL_TYPES, TRANSPORT_TYPES
)

router = APIRouter(prefix="/api/admin", tags=["Admin"])

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

@router.get("/protocols")
async def list_protocols():
    """لیست تمام پروتکل‌های پشتیبانی شده"""
    return {"protocols": PROTOCOL_TYPES}

@router.get("/transports")
async def list_transports():
    """لیست تمام روش‌های انتقال پشتیبانی شده"""
    return {"transports": TRANSPORT_TYPES}

@router.post("/user")
async def create_user(username: str, password: str, is_admin: bool = False):
    users = await get_users()
    if any(u["username"] == username for u in users):
        raise HTTPException(400, "User already exists")
    new_user = {
        "id": str(uuid.uuid4()),
        "username": username,
        "password_hash": hash_password(password),
        "is_admin": is_admin,
        "reseller_id": None,
        "created_at": datetime.now().isoformat(),
        "inbounds": []
    }
    await add_user(new_user)
    return {"status": "ok", "user": {k: v for k, v in new_user.items() if k != "password_hash"}}

@router.get("/users")
async def list_users():
    users = await get_users()
    return {"users": [{k: v for k, v in u.items() if k != "password_hash"} for u in users]}

@router.delete("/user/{user_id}")
async def delete_user(user_id: str):
    state = await load_state()
    state["users"] = [u for u in state["users"] if u["id"] != user_id]
    await save_state(state)
    return {"status": "ok"}

@router.post("/inbound")
async def create_inbound(
    protocol: str,
    port: int,
    transport: str,
    owner_id: str,
    path: str = "/",
    host: str = "example.com",
    total_bytes: int = 0,
    expiry_days: int = 30,
    max_ips: int = 0,
    tls: bool = False,
    tls_cert: Optional[str] = None,
    tls_key: Optional[str] = None,
    username: str = "",
    password: str = "",
    method: str = "chacha20-ietf-poly1305",
    service_name: str = "grpc",
    quic_key: str = "",
    quic_security: str = "none",
    quic_header: str = "none"
):
    # بررسی وجود owner
    users = await get_users()
    owner = next((u for u in users if u["id"] == owner_id), None)
    if not owner:
        raise HTTPException(404, "Owner not found")
    
    # بررسی تکراری نبودن پورت
    inbounds = await get_inbounds()
    if any(i["port"] == port for i in inbounds):
        raise HTTPException(400, "Port already in use")
    
    if protocol not in ["vless", "vmess", "trojan", "shadowsocks", "socks", "http", "https", "grpc", "quic"]:
        raise HTTPException(400, "Protocol not supported")
    
    uuid_str = str(uuid.uuid4())
    tls_settings = None
    if tls and tls_cert and tls_key:
        tls_settings = {"certificates": [{"certificateFile": tls_cert, "keyFile": tls_key}]}
    
    if protocol == "vless":
        config = generate_vless_config(port, uuid_str, path, host, transport, tls, tls_settings)
    elif protocol == "vmess":
        config = generate_vmess_config(port, uuid_str, path, host, transport, tls, tls_settings)
    elif protocol == "trojan":
        config = generate_trojan_config(port, uuid_str, path, host, transport, tls, tls_settings)
    elif protocol == "shadowsocks":
        config = generate_shadowsocks_config(port, password or uuid_str, method, transport, tls)
    elif protocol == "socks":
        config = generate_socks_config(port, username, password, transport)
    elif protocol == "http":
        config = generate_http_config(port, username, password, transport, tls)
    elif protocol == "https":
        config = generate_https_config(port, tls_cert or "/certs/cert.pem", tls_key or "/certs/key.pem", transport)
    elif protocol == "grpc":
        config = generate_grpc_config(port, service_name, tls, tls_settings)
    elif protocol == "quic":
        config = generate_quic_config(port, quic_key, quic_security, quic_header)
    else:
        raise HTTPException(400, "Protocol not supported")
    
    inbound = {
        "id": str(uuid.uuid4()),
        "protocol": protocol,
        "port": port,
        "transport": transport,
        "settings": config,
        "enabled": True,
        "owner_id": owner_id,
        "used_bytes": 0,
        "total_bytes": total_bytes * 1024 * 1024 * 1024 if total_bytes > 0 else 0,
        "created_at": datetime.now().isoformat(),
        "expiry_date": (datetime.now() + timedelta(days=expiry_days)).isoformat() if expiry_days > 0 else None,
        "max_ips": max_ips,
        "uuid": uuid_str,
        "path": path,
        "host": host,
        "tls": tls,
        "tls_settings": tls_settings
    }
    await add_inbound(inbound)
    share_link = generate_share_link(protocol, config, host, port, uuid_str, path, tls)
    return {
        "status": "ok",
        "inbound": inbound,
        "share_link": share_link
    }

@router.get("/inbounds")
async def list_inbounds():
    inbounds = await get_inbounds()
    return {"inbounds": inbounds}

@router.get("/inbound/{inbound_id}")
async def get_inbound(inbound_id: str):
    inbounds = await get_inbounds()
    inbound = next((i for i in inbounds if i["id"] == inbound_id), None)
    if not inbound:
        raise HTTPException(404, "Inbound not found")
    return inbound

@router.put("/inbound/{inbound_id}")
async def update_inbound_endpoint(
    inbound_id: str, 
    enabled: Optional[bool] = None, 
    total_bytes: Optional[int] = None,
    expiry_days: Optional[int] = None,
    tls: Optional[bool] = None
):
    updates = {}
    if enabled is not None:
        updates["enabled"] = enabled
    if total_bytes is not None:
        updates["total_bytes"] = total_bytes * 1024 * 1024 * 1024
    if expiry_days is not None:
        updates["expiry_date"] = (datetime.now() + timedelta(days=expiry_days)).isoformat()
    if tls is not None:
        updates["tls"] = tls
    await update_inbound(inbound_id, updates)
    return {"status": "ok"}

@router.delete("/inbound/{inbound_id}")
async def delete_inbound_endpoint(inbound_id: str):
    await delete_inbound(inbound_id)
    return {"status": "ok"}

@router.post("/reseller")
async def create_reseller(username: str, password: str):
    resellers = await get_resellers()
    if any(r["username"] == username for r in resellers):
        raise HTTPException(400, "Reseller already exists")
    new_reseller = {
        "id": str(uuid.uuid4()),
        "username": username,
        "password_hash": hash_password(password),
        "token": secrets.token_urlsafe(32),
        "created_at": datetime.now().isoformat(),
        "inbounds": []
    }
    await add_reseller(new_reseller)
    return {"status": "ok", "reseller": {k: v for k, v in new_reseller.items() if k != "password_hash"}}

@router.get("/resellers")
async def list_resellers():
    resellers = await get_resellers()
    return {"resellers": [{k: v for k, v in r.items() if k != "password_hash"} for r in resellers]}

@router.post("/login")
async def login(username: str, password: str):
    users = await get_users()
    user = next((u for u in users if u["username"] == username), None)
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    token = secrets.token_urlsafe(32)
    return {
        "status": "ok",
        "token": token,
        "user": {k: v for k, v in user.items() if k != "password_hash"}
}
