import json
import os
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
import aiofiles
from .models import User, Inbound, Reseller, GlobalSettings

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_FILE = DATA_DIR / "cbee_state.json"
SAVE_LOCK = asyncio.Lock()

async def load_from_github() -> Optional[Dict]:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    fname = os.environ.get("GITHUB_FILE", "cbee_state.json")
    if not token or not repo:
        return None
    import httpx
    import base64
    url = f"https://api.github.com/repos/{repo}/contents/{fname}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "CBeePanel"
    }
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers=headers, timeout=10.0)
            if r.status_code == 200:
                data = r.json()
                content = base64.b64decode(data["content"]).decode()
                return json.loads(content)
        except Exception as e:
            print(f"GitHub load error: {e}")
    return None

async def save_to_github(data: Dict):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    fname = os.environ.get("GITHUB_FILE", "cbee_state.json")
    if not token or not repo:
        return
    import httpx
    import base64
    url = f"https://api.github.com/repos/{repo}/contents/{fname}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "CBeePanel"
    }
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers, timeout=10.0)
        sha = None
        if r.status_code == 200:
            sha = r.json().get("sha")
        content = base64.b64encode(json.dumps(data, default=str).encode()).decode()
        payload = {"message": "Update state", "content": content}
        if sha:
            payload["sha"] = sha
        await client.put(url, headers=headers, json=payload, timeout=10.0)

async def load_state() -> Dict:
    default = {
        "users": [],
        "inbounds": [],
        "resellers": [],
        "global_settings": {},
        "password_hash": ""
    }
    github_data = await load_from_github()
    if github_data:
        return github_data
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if DATA_FILE.exists():
            async with aiofiles.open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
                return data
    except Exception as e:
        print(f"Local load error: {e}")
    return default

async def save_state(data: Dict):
    async with SAVE_LOCK:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(DATA_FILE, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, default=str, indent=2))
        except Exception as e:
            print(f"Local save error: {e}")
        await save_to_github(data)

async def get_users() -> List[Dict]:
    state = await load_state()
    return state.get("users", [])

async def get_inbounds() -> List[Dict]:
    state = await load_state()
    return state.get("inbounds", [])

async def get_resellers() -> List[Dict]:
    state = await load_state()
    return state.get("resellers", [])

async def add_user(user: Dict):
    state = await load_state()
    state["users"].append(user)
    await save_state(state)

async def add_inbound(inbound: Dict):
    state = await load_state()
    state["inbounds"].append(inbound)
    await save_state(state)

async def update_inbound(inbound_id: str, updates: Dict):
    state = await load_state()
    for i, item in enumerate(state["inbounds"]):
        if item["id"] == inbound_id:
            state["inbounds"][i].update(updates)
            break
    await save_state(state)

async def delete_inbound(inbound_id: str):
    state = await load_state()
    state["inbounds"] = [i for i in state["inbounds"] if i["id"] != inbound_id]
    await save_state(state)

async def add_reseller(reseller: Dict):
    state = await load_state()
    state["resellers"].append(reseller)
    await save_state(state)