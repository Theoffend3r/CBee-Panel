import asyncio
import secrets
from datetime import datetime
from typing import Optional, Dict
from fastapi import WebSocket, WebSocketDisconnect
import httpx

RELAY_BUF = 256 * 1024

connections: Dict[str, Dict] = {}
stats = {
    "total_bytes": 0,
    "total_requests": 0,
    "active_connections": 0
}
hourly_traffic: Dict[str, int] = {}

def get_client_ip(ws: WebSocket) -> str:
    fwd = ws.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real_ip = ws.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return ws.client.host if ws.client else "unknown"

async def parse_vless_header(chunk: bytes):
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

async def relay_ws_to_tcp(ws: WebSocket, writer: asyncio.StreamWriter, conn_id: str, uid: str, check_usage_func):
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes") or (msg.get("text") or "").encode()
            if not data:
                continue
            if not await check_usage_func(uid, len(data)):
                await ws.close(code=1008, reason="quota/disabled/unknown")
                break
            stats["total_requests"] += 1
            if conn_id in connections:
                connections[conn_id]["bytes"] += len(data)
            writer.write(data)
            if writer.transport.get_write_buffer_size() > RELAY_BUF:
                await writer.drain()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        try:
            writer.write_eof()
        except Exception:
            pass

async def relay_tcp_to_ws(ws: WebSocket, reader: asyncio.StreamReader, conn_id: str, uid: str):
    try:
        while True:
            data = await reader.read(RELAY_BUF)
            if not data:
                break
            await ws.send_bytes(data)
    except (WebSocketDisconnect, Exception):
        pass

async def handle_vless_connection(ws: WebSocket, get_inbound_by_port_func, check_usage_func):
    client_ip = get_client_ip(ws)
    conn_id = secrets.token_hex(8)
    try:
        first_msg = await ws.receive()
        if first_msg["type"] != "websocket.receive":
            await ws.close(code=1000)
            return
        data = first_msg.get("bytes") or (first_msg.get("text") or "").encode()
        if not data:
            await ws.close(code=1000)
            return
        try:
            command, address, port, remaining = await parse_vless_header(data)
        except Exception as e:
            await ws.close(code=1000, reason=f"Invalid VLESS header: {e}")
            return
        inbound = await get_inbound_by_port_func(port)
        if not inbound or not inbound.get("enabled", True):
            await ws.close(code=1000, reason="Inbound not found or disabled")
            return
        uid = inbound.get("id")
        connections[conn_id] = {
            "client_ip": client_ip,
            "target": f"{address}:{port}",
            "bytes": 0,
            "started": datetime.now(),
            "uid": uid
        }
        stats["active_connections"] += 1
        try:
            reader, writer = await asyncio.open_connection(address, port)
        except Exception as e:
            await ws.close(code=1000, reason=f"Target connection failed: {e}")
            return
        if remaining:
            writer.write(remaining)
            await writer.drain()
        task1 = asyncio.create_task(relay_ws_to_tcp(ws, writer, conn_id, uid, check_usage_func))
        task2 = asyncio.create_task(relay_tcp_to_ws(ws, reader, conn_id, uid))
        await asyncio.gather(task1, task2, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    finally:
        if conn_id in connections:
            del connections[conn_id]
        stats["active_connections"] = max(0, stats["active_connections"] - 1)

class HTTPRelay:
    def __init__(self, timeout=30, max_connections=100):
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_connections)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_keepalive_connections=20)
        )
    async def forward(self, request, target_url: str):
        async with self.semaphore:
            body = await request.body()
            headers = {
                k: v for k, v in request.headers.items() 
                if k.lower() not in ['host', 'content-length', 'connection']
            }
            try:
                resp = await self.client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body,
                    follow_redirects=True
                )
                from fastapi.responses import Response
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    headers=dict(resp.headers)
                )
            except httpx.TimeoutException:
                return Response(content="Gateway Timeout", status_code=504)
            except Exception as e:
                return Response(content=f"Proxy Error: {str(e)}", status_code=502)
