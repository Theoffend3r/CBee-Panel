from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
import uuid
from datetime import datetime

from storage.database import get_resellers, get_inbounds, add_inbound
from core.protocols import (
    generate_vless_config, generate_vmess_config, 
    generate_trojan_config, generate_shadowsocks_config,
    generate_socks_config, generate_http_config, 
    generate_https_config, generate_grpc_config, generate_quic_config,
    generate_share_link, PROTOCOL_TYPES
)

router = APIRouter(prefix="/api/reseller", tags=["Reseller"])

async def verify_reseller_token(token: str = Header(...)):
    resellers = await get_resellers()
    reseller = next((r for r in resellers if r["token"] == token), None)
    if not reseller:
        raise HTTPException(401, "Invalid token")
    return reseller

@router.post("/inbound")
async def reseller_create_inbound(
    protocol: str,
    port: int,
    transport: str,
    path: str = "/",
    host: str = "example.com",
    tls: bool = False,
    username: str = "",
    password: str = "",
    method: str = "chacha20-ietf-poly1305",
    service_name: str = "grpc",
    reseller: dict = Depends(verify_reseller_token)
):
    if protocol not in PROTOCOL_TYPES:
        raise HTTPException(400, "Protocol not supported")
    
    uuid_str = str(uuid.uuid4())
    if protocol == "vless":
        config = generate_vless_config(port, uuid_str, path, host, transport, tls)
    elif protocol == "vmess":
        config = generate_vmess_config(port, uuid_str, path, host, transport, tls)
    elif protocol == "trojan":
        config = generate_trojan_config(port, uuid_str, path, host, transport, tls)
    elif protocol == "shadowsocks":
        config = generate_shadowsocks_config(port, password or uuid_str, method, transport, tls)
    elif protocol == "socks":
        config = generate_socks_config(port, username, password, transport)
    elif protocol == "http":
        config = generate_http_config(port, username, password, transport, tls)
    elif protocol == "https":
        config = generate_https_config(port, "/certs/cert.pem", "/certs/key.pem", transport)
    elif protocol == "grpc":
        config = generate_grpc_config(port, service_name, tls)
    elif protocol == "quic":
        config = generate_quic_config(port)
    else:
        raise HTTPException(400, "Protocol not supported")
    
    inbound = {
        "id": str(uuid.uuid4()),
        "protocol": protocol,
        "port": port,
        "transport": transport,
        "settings": config,
        "enabled": True,
        "owner_id": reseller["id"],
        "used_bytes": 0,
        "total_bytes": 0,
        "created_at": datetime.now().isoformat(),
        "expiry_date": None,
        "max_ips": 0,
        "uuid": uuid_str,
        "path": path,
        "host": host,
        "tls": tls
    }
    await add_inbound(inbound)
    return {"status": "ok", "inbound": inbound}

@router.get("/inbounds")
async def reseller_list_inbounds(reseller: dict = Depends(verify_reseller_token)):
    inbounds = await get_inbounds()
    my_inbounds = [i for i in inbounds if i["owner_id"] == reseller["id"]]
    return {"inbounds": my_inbounds}