import uuid
import json
from typing import Dict, Optional

PROTOCOL_TYPES = [
    "vless", "vmess", "trojan", "shadowsocks", 
    "socks", "http", "https", "grpc", "quic"
]

TRANSPORT_TYPES = [
    "websocket", "xhttp", "grpc", "tcp", "quic"
]

def generate_vless_config(port: int, uuid_str: str, path: str = '/', 
                          host: str = 'example.com', transport: str = 'websocket',
                          tls: bool = False, tls_settings: Optional[Dict] = None) -> Dict:
    config = {
        "vless": {
            "port": port,
            "clients": [{"id": uuid_str, "flow": "xtls-rprx-vision"}],
            "streamSettings": {
                "network": transport,
                "security": "tls" if tls else "none"
            }
        }
    }
    if tls and tls_settings:
        config["vless"]["streamSettings"]["tlsSettings"] = tls_settings
    if transport == 'websocket':
        config["vless"]["streamSettings"]["wsSettings"] = {
            "path": path,
            "headers": {"Host": host}
        }
    elif transport == 'xhttp':
        config["vless"]["streamSettings"]["xhttpSettings"] = {
            "path": path,
            "host": host
        }
    elif transport == 'grpc':
        config["vless"]["streamSettings"]["grpcSettings"] = {
            "serviceName": path.strip('/')
        }
    elif transport == 'quic':
        config["vless"]["streamSettings"]["quicSettings"] = {
            "security": "none",
            "key": "",
            "header": {"type": "none"}
        }
    return config

def generate_vmess_config(port: int, uuid_str: str, path: str = '/', 
                          host: str = 'example.com', transport: str = 'websocket',
                          tls: bool = False, tls_settings: Optional[Dict] = None) -> Dict:
    config = {
        "vmess": {
            "port": port,
            "clients": [{"id": uuid_str, "alterId": 0}],
            "streamSettings": {
                "network": transport,
                "security": "tls" if tls else "none"
            }
        }
    }
    if tls and tls_settings:
        config["vmess"]["streamSettings"]["tlsSettings"] = tls_settings
    if transport == 'websocket':
        config["vmess"]["streamSettings"]["wsSettings"] = {
            "path": path,
            "headers": {"Host": host}
        }
    elif transport == 'xhttp':
        config["vmess"]["streamSettings"]["xhttpSettings"] = {
            "path": path,
            "host": host
        }
    return config

def generate_trojan_config(port: int, password: str, path: str = '/', 
                           host: str = 'example.com', transport: str = 'websocket',
                           tls: bool = False, tls_settings: Optional[Dict] = None) -> Dict:
    config = {
        "trojan": {
            "port": port,
            "clients": [{"password": password}],
            "streamSettings": {
                "network": transport,
                "security": "tls" if tls else "none"
            }
        }
    }
    if tls and tls_settings:
        config["trojan"]["streamSettings"]["tlsSettings"] = tls_settings
    if transport == 'websocket':
        config["trojan"]["streamSettings"]["wsSettings"] = {
            "path": path,
            "headers": {"Host": host}
        }
    return config

def generate_shadowsocks_config(port: int, password: str, method: str = 'chacha20-ietf-poly1305',
                                transport: str = 'tcp', tls: bool = False) -> Dict:
    return {
        "shadowsocks": {
            "port": port,
            "clients": [{"password": password, "method": method}],
            "network": transport,
            "security": "tls" if tls else "none"
        }
    }

def generate_socks_config(port: int, username: str = '', password: str = '',
                          transport: str = 'tcp') -> Dict:
    return {
        "socks": {
            "port": port,
            "clients": [{"user": username, "pass": password}],
            "network": transport
        }
    }

def generate_http_config(port: int, username: str = '', password: str = '',
                         transport: str = 'tcp', tls: bool = False) -> Dict:
    return {
        "http": {
            "port": port,
            "clients": [{"user": username, "pass": password}],
            "network": transport,
            "security": "tls" if tls else "none"
        }
    }

def generate_https_config(port: int, cert_file: str, key_file: str,
                          transport: str = 'tcp') -> Dict:
    return {
        "https": {
            "port": port,
            "clients": [],
            "streamSettings": {
                "network": transport,
                "security": "tls",
                "tlsSettings": {
                    "certificates": [{"certificateFile": cert_file, "keyFile": key_file}]
                }
            }
        }
    }

def generate_grpc_config(port: int, service_name: str = 'grpc',
                         tls: bool = False, tls_settings: Optional[Dict] = None) -> Dict:
    config = {
        "grpc": {
            "port": port,
            "clients": [],
            "streamSettings": {
                "network": "grpc",
                "security": "tls" if tls else "none",
                "grpcSettings": {"serviceName": service_name}
            }
        }
    }
    if tls and tls_settings:
        config["grpc"]["streamSettings"]["tlsSettings"] = tls_settings
    return config

def generate_quic_config(port: int, key: str = '', security: str = 'none',
                         header_type: str = 'none') -> Dict:
    return {
        "quic": {
            "port": port,
            "clients": [],
            "streamSettings": {
                "network": "quic",
                "security": security,
                "quicSettings": {
                    "security": security,
                    "key": key,
                    "header": {"type": header_type}
                }
            }
        }
    }

def generate_share_link(protocol: str, config: Dict, host: str, port: int, 
                        uuid_str: str, path: str = '/', tls: bool = False) -> str:
    from urllib.parse import quote
    if protocol == 'vless':
        tls_param = "tls" if tls else "none"
        return f"vless://{uuid_str}@{host}:{port}?path={quote(path)}&security={tls_param}&encryption=none&type=ws#CBee-{uuid_str[:8]}"
    elif protocol == 'vmess':
        vmess_config = {
            "v": "2",
            "ps": f"CBee-{uuid_str[:8]}",
            "add": host,
            "port": str(port),
            "id": uuid_str,
            "aid": "0",
            "net": "ws",
            "type": "none",
            "host": host,
            "path": path,
            "tls": "tls" if tls else "none"
        }
        return f"vmess://{quote(json.dumps(vmess_config))}"
    elif protocol == 'trojan':
        return f"trojan://{uuid_str}@{host}:{port}?path={quote(path)}&security={'tls' if tls else 'none'}&type=ws#CBee-{uuid_str[:8]}"
    elif protocol == 'shadowsocks':
        return f"ss://{uuid_str}@{host}:{port}#CBee-{uuid_str[:8]}"
    elif protocol == 'socks':
        return f"socks://{host}:{port}#CBee-{uuid_str[:8]}"
    elif protocol == 'http':
        return f"http://{host}:{port}#CBee-{uuid_str[:8]}"
    elif protocol == 'https':
        return f"https://{host}:{port}#CBee-{uuid_str[:8]}"
    return ""