from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime

class User(BaseModel):
    id: str
    username: str
    password_hash: str
    is_admin: bool = False
    reseller_id: Optional[str] = None
    created_at: datetime = datetime.now()
    inbounds: List[str] = []

class Inbound(BaseModel):
    id: str
    protocol: str  # vless, vmess, trojan, shadowsocks, socks, http, https, grpc, quic
    port: int
    transport: str  # websocket, xhttp, grpc, tcp, quic
    settings: Dict  # شامل uuid, password, path, host, method, ...
    mode: Optional[str] = None  # stream-up, packet-up
    enabled: bool = True
    owner_id: str
    used_bytes: int = 0
    total_bytes: int = 0
    created_at: datetime = datetime.now()
    expiry_date: Optional[datetime] = None
    max_ips: int = 0
    tls: bool = False
    tls_settings: Optional[Dict] = None  # برای تنظیمات TLS

class Reseller(BaseModel):
    id: str
    username: str
    password_hash: str
    token: str
    created_at: datetime = datetime.now()
    inbounds: List[str] = []

class GlobalSettings(BaseModel):
    config_name_template: str = "CBee-{USER}-{INDEX}"
    default_expiry_days: int = 30
    default_traffic_gb: int = 100
