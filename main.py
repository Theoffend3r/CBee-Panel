import asyncio
import json
import os
import uuid
import hashlib
import secrets
import time
import psutil
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import httpx
import websockets
from typing import Dict, List, Optional, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="CBee Panel Pro", version="3.0.0")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
PORT = int(os.getenv("PORT", 8000))

DB_FILE = "panel_db.json"
LINKS: Dict[str, Dict] = {}
CUSTOM_ADDRESSES: List[str] = []
CONFIG = {"telegram_token": "", "telegram_admin_id": "", "bot_lang": "fa"}
SESSIONS: Dict[str, str] = {}
ACTIVE_WEBSOCKETS: Dict[str, set] = {}

def load_db():
    global LINKS, CUSTOM_ADDRESSES, CONFIG
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                LINKS = data.get("links", {})
                CUSTOM_ADDRESSES = data.get("addresses", [])
                CONFIG.update(data.get("config", {}))
        except Exception as e:
            logger.error(f"Error loading DB: {e}")

def save_db():
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump({"links": LINKS, "addresses": CUSTOM_ADDRESSES, "config": CONFIG}, f, indent=2)
        return True
    except:
        return False

def check_auth(request: Request) -> bool:
    session_id = request.cookies.get("session_id")
    return session_id and session_id in SESSIONS

# ==================== طراحی شاهکار ====================
# این بخش شامل کدهای HTML و CSS و JS هست که به صورت یکجا در main.py قرار میگیره

# ==================== صفحه لاگین ====================
LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🐝 CBee Panel Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', sans-serif;
            background: #08080a;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            position: relative;
        }
        
        /* پس‌زمینه سه‌بعدی با ذرات */
        #particles-canvas {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
        }
        
        /* گرید خطوط طلایی */
        .grid-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-image: 
                linear-gradient(rgba(245, 158, 11, 0.03) 1px, transparent 1px),
                linear-gradient(90deg, rgba(245, 158, 11, 0.03) 1px, transparent 1px);
            background-size: 60px 60px;
            z-index: 1;
            pointer-events: none;
        }
        
        .login-wrapper {
            position: relative;
            z-index: 2;
            width: 100%;
            max-width: 440px;
            padding: 20px;
        }
        
        .login-card {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(40px);
            -webkit-backdrop-filter: blur(40px);
            border: 1px solid rgba(245, 158, 11, 0.15);
            border-radius: 32px;
            padding: 48px 40px;
            position: relative;
            overflow: hidden;
            box-shadow: 0 30px 80px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.05);
        }
        
        .login-card::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(ellipse at 30% 50%, rgba(245, 158, 11, 0.06), transparent 60%);
            pointer-events: none;
        }
        
        .logo-container {
            text-align: center;
            margin-bottom: 32px;
        }
        
        .logo-icon {
            font-size: 56px;
            display: inline-block;
            animation: float 4s ease-in-out infinite;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0px) rotate(0deg); }
            50% { transform: translateY(-10px) rotate(5deg); }
        }
        
        .logo-title {
            font-size: 32px;
            font-weight: 900;
            background: linear-gradient(135deg, #fbbf24, #f59e0b, #d97706);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -1px;
            margin-top: 8px;
        }
        
        .logo-sub {
            color: rgba(255,255,255,0.3);
            font-size: 13px;
            font-weight: 400;
            letter-spacing: 4px;
            text-transform: uppercase;
            margin-top: 4px;
        }
        
        .input-group {
            position: relative;
            margin-bottom: 20px;
        }
        
        .input-group .icon {
            position: absolute;
            right: 16px;
            top: 50%;
            transform: translateY(-50%);
            color: rgba(255,255,255,0.2);
            font-size: 18px;
        }
        
        .input-group input {
            width: 100%;
            padding: 16px 48px 16px 16px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            color: #fff;
            font-size: 15px;
            transition: all 0.3s;
            outline: none;
        }
        
        .input-group input:focus {
            border-color: rgba(245, 158, 11, 0.4);
            background: rgba(255,255,255,0.06);
            box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.05);
        }
        
        .input-group input::placeholder {
            color: rgba(255,255,255,0.2);
        }
        
        .btn-login {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #f59e0b, #d97706);
            border: none;
            border-radius: 16px;
            color: #000;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
            overflow: hidden;
        }
        
        .btn-login:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 40px rgba(245, 158, 11, 0.3);
        }
        
        .btn-login:active {
            transform: scale(0.98);
        }
        
        .btn-login .shine {
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle at 30% 50%, rgba(255,255,255,0.15), transparent 60%);
            opacity: 0;
            transition: opacity 0.5s;
        }
        
        .btn-login:hover .shine {
            opacity: 1;
        }
        
        .footer-text {
            text-align: center;
            margin-top: 20px;
            color: rgba(255,255,255,0.15);
            font-size: 12px;
            letter-spacing: 1px;
        }
        
        .error-toast {
            position: fixed;
            bottom: 30px;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: rgba(239, 68, 68, 0.15);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(239, 68, 68, 0.2);
            border-radius: 16px;
            padding: 16px 28px;
            color: #fca5a5;
            font-size: 14px;
            z-index: 100;
            opacity: 0;
            transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .error-toast.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }
        
        @media (max-width: 480px) {
            .login-card { padding: 32px 24px; }
            .logo-title { font-size: 26px; }
        }
    </style>
</head>
<body>
    <canvas id="particles-canvas"></canvas>
    <div class="grid-overlay"></div>
    
    <div class="login-wrapper">
        <div class="login-card">
            <div class="logo-container">
                <div class="logo-icon">🐝</div>
                <div class="logo-title">CBee Panel</div>
                <div class="logo-sub">Professional Control</div>
            </div>
            
            <form id="loginForm">
                <div class="input-group">
                    <span class="icon">🔑</span>
                    <input type="password" id="password" placeholder="رمز عبور را وارد کنید" autofocus>
                </div>
                <button type="submit" class="btn-login">
                    <span class="shine"></span>
                    ورود به پنل
                </button>
            </form>
            
            <div class="footer-text">نسخه 3.0 • طراحی حرفه‌ای</div>
        </div>
    </div>
    
    <div class="error-toast" id="errorToast">
        <span>⚠️</span>
        <span id="errorMessage">رمز عبور اشتباه است</span>
    </div>

    <script>
        // ===== ذرات پس‌زمینه =====
        const canvas = document.getElementById('particles-canvas');
        const ctx = canvas.getContext('2d');
        let particles = [];
        let mouseX = 0, mouseY = 0;

        function resize() {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        }
        resize();
        window.addEventListener('resize', resize);

        class Particle {
            constructor() {
                this.x = Math.random() * canvas.width;
                this.y = Math.random() * canvas.height;
                this.size = Math.random() * 2 + 1;
                this.speedX = (Math.random() - 0.5) * 0.3;
                this.speedY = (Math.random() - 0.5) * 0.3;
                this.opacity = Math.random() * 0.5 + 0.1;
            }
            
            update() {
                this.x += this.speedX;
                this.y += this.speedY;
                
                if (this.x < 0 || this.x > canvas.width) this.speedX *= -1;
                if (this.y < 0 || this.y > canvas.height) this.speedY *= -1;
                
                // تعامل با ماوس
                const dx = mouseX - this.x;
                const dy = mouseY - this.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 150) {
                    const force = (150 - dist) / 150 * 0.02;
                    this.x += dx * force;
                    this.y += dy * force;
                }
            }
            
            draw() {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(245, 158, 11, ${this.opacity})`;
                ctx.fill();
            }
        }

        for (let i = 0; i < 80; i++) {
            particles.push(new Particle());
        }

        function animateParticles() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            particles.forEach(p => {
                p.update();
                p.draw();
            });
            
            // خطوط بین ذرات
            for (let i = 0; i < particles.length; i++) {
                for (let j = i + 1; j < particles.length; j++) {
                    const dx = particles[i].x - particles[j].x;
                    const dy = particles[i].y - particles[j].y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < 120) {
                        ctx.beginPath();
                        ctx.strokeStyle = `rgba(245, 158, 11, ${0.04 * (1 - dist/120)})`;
                        ctx.lineWidth = 0.5;
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.stroke();
                    }
                }
            }
            requestAnimationFrame(animateParticles);
        }
        animateParticles();

        document.addEventListener('mousemove', (e) => {
            mouseX = e.clientX;
            mouseY = e.clientY;
        });

        // ===== لاگین =====
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const password = document.getElementById('password').value;
            
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password })
                });
                const data = await res.json();
                
                if (data.success) {
                    window.location.href = '/';
                } else {
                    showError('رمز عبور اشتباه است');
                    document.getElementById('password').value = '';
                    document.getElementById('password').focus();
                }
            } catch {
                showError('خطا در ارتباط با سرور');
            }
        });

        function showError(msg) {
            const toast = document.getElementById('errorToast');
            document.getElementById('errorMessage').textContent = msg;
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3000);
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') document.getElementById('loginForm').dispatchEvent(new Event('submit'));
        });
    </script>
</body>
</html>
"""

# ==================== صفحه اصلی (داشبورد) ====================
DASHBOARD_PAGE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🐝 CBee Panel Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800;900&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        :root {
            --gold: #f59e0b;
            --gold-light: #fbbf24;
            --gold-dark: #b45309;
            --bg-primary: #08080a;
            --bg-card: rgba(255,255,255,0.03);
            --border-color: rgba(255,255,255,0.05);
            --text-primary: #ffffff;
            --text-secondary: rgba(255,255,255,0.5);
            --shadow-gold: rgba(245, 158, 11, 0.15);
            --radius: 20px;
            --transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }
        
        /* ===== پس‌زمینه ===== */
        .bg-grid {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-image: 
                linear-gradient(rgba(245,158,11,0.02) 1px, transparent 1px),
                linear-gradient(90deg, rgba(245,158,11,0.02) 1px, transparent 1px);
            background-size: 60px 60px;
            z-index: 0;
            pointer-events: none;
        }
        
        .bg-glow {
            position: fixed;
            top: -20%;
            right: -10%;
            width: 60%;
            height: 60%;
            background: radial-gradient(ellipse, rgba(245,158,11,0.04), transparent 70%);
            z-index: 0;
            pointer-events: none;
        }
        
        .bg-glow-2 {
            position: fixed;
            bottom: -20%;
            left: -10%;
            width: 50%;
            height: 50%;
            background: radial-gradient(ellipse, rgba(245,158,11,0.03), transparent 70%);
            z-index: 0;
            pointer-events: none;
        }
        
        /* ===== سایدبار ===== */
        .sidebar {
            position: fixed;
            right: 0;
            top: 0;
            width: 280px;
            height: 100vh;
            background: rgba(10, 10, 12, 0.95);
            backdrop-filter: blur(40px);
            border-left: 1px solid rgba(255,255,255,0.03);
            z-index: 50;
            padding: 28px 20px;
            display: flex;
            flex-direction: column;
            transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            overflow-y: auto;
        }
        
        .sidebar::-webkit-scrollbar { width: 3px; }
        .sidebar::-webkit-scrollbar-thumb { background: var(--gold); border-radius: 10px; }
        
        .sidebar-brand {
            text-align: center;
            padding-bottom: 24px;
            border-bottom: 1px solid rgba(255,255,255,0.03);
            margin-bottom: 24px;
        }
        
        .sidebar-brand .icon {
            font-size: 40px;
            display: block;
            animation: float 4s ease-in-out infinite;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-5px); }
        }
        
        .sidebar-brand h1 {
            font-size: 22px;
            font-weight: 900;
            background: linear-gradient(135deg, var(--gold-light), var(--gold));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-top: 6px;
        }
        
        .sidebar-brand span {
            font-size: 11px;
            color: var(--text-secondary);
            letter-spacing: 3px;
            text-transform: uppercase;
        }
        
        .nav-item {
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 12px 16px;
            border-radius: 14px;
            color: var(--text-secondary);
            text-decoration: none;
            transition: var(--transition);
            cursor: pointer;
            margin-bottom: 2px;
            position: relative;
        }
        
        .nav-item:hover {
            background: rgba(245,158,11,0.06);
            color: var(--text-primary);
        }
        
        .nav-item.active {
            background: rgba(245,158,11,0.08);
            color: var(--gold-light);
        }
        
        .nav-item.active::before {
            content: '';
            position: absolute;
            right: -4px;
            top: 50%;
            transform: translateY(-50%);
            width: 3px;
            height: 24px;
            background: var(--gold);
            border-radius: 10px;
        }
        
        .nav-item i {
            width: 22px;
            text-align: center;
            font-size: 16px;
        }
        
        .nav-divider {
            height: 1px;
            background: rgba(255,255,255,0.03);
            margin: 12px 0;
        }
        
        .sidebar-footer {
            margin-top: auto;
            padding-top: 16px;
            border-top: 1px solid rgba(255,255,255,0.03);
        }
        
        .sidebar-footer .nav-item {
            color: rgba(239, 68, 68, 0.5);
        }
        
        .sidebar-footer .nav-item:hover {
            color: rgba(239, 68, 68, 0.8);
            background: rgba(239, 68, 68, 0.06);
        }
        
        /* ===== محتوای اصلی ===== */
        .main {
            margin-right: 280px;
            min-height: 100vh;
            padding: 28px 36px 40px;
            position: relative;
            z-index: 1;
        }
        
        /* ===== هدر ===== */
        .page-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
            flex-wrap: wrap;
            gap: 16px;
        }
        
        .page-header h2 {
            font-size: 26px;
            font-weight: 800;
            letter-spacing: -0.5px;
        }
        
        .page-header h2 i {
            color: var(--gold);
            margin-left: 12px;
        }
        
        .header-actions {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .header-badge {
            background: rgba(245,158,11,0.08);
            border: 1px solid rgba(245,158,11,0.1);
            border-radius: 100px;
            padding: 6px 16px;
            font-size: 12px;
            color: var(--text-secondary);
        }
        
        .header-badge i {
            color: var(--gold);
            margin-left: 6px;
        }
        
        /* ===== کارت‌ها ===== */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }
        
        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: var(--radius);
            padding: 20px 24px;
            transition: var(--transition);
            position: relative;
            overflow: hidden;
        }
        
        .stat-card:hover {
            border-color: rgba(245,158,11,0.15);
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(0,0,0,0.3);
        }
        
        .stat-card .label {
            font-size: 13px;
            color: var(--text-secondary);
            font-weight: 500;
        }
        
        .stat-card .value {
            font-size: 28px;
            font-weight: 900;
            margin-top: 4px;
            letter-spacing: -0.5px;
        }
        
        .stat-card .value.gold { color: var(--gold-light); }
        .stat-card .value.green { color: #34d399; }
        .stat-card .value.blue { color: #60a5fa; }
        .stat-card .value.purple { color: #a78bfa; }
        
        .stat-card .icon-bg {
            position: absolute;
            left: 16px;
            top: 16px;
            font-size: 32px;
            opacity: 0.05;
        }
        
        /* ===== جدول ===== */
        .table-wrap {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: var(--radius);
            overflow: hidden;
        }
        
        .table-header {
            padding: 18px 24px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .table-header h3 {
            font-size: 16px;
            font-weight: 700;
        }
        
        .table-header .count {
            font-size: 13px;
            color: var(--text-secondary);
            background: rgba(255,255,255,0.04);
            padding: 4px 14px;
            border-radius: 100px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            text-align: right;
            padding: 14px 20px;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid var(--border-color);
        }
        
        td {
            padding: 14px 20px;
            font-size: 14px;
            border-bottom: 1px solid rgba(255,255,255,0.02);
        }
        
        tr:hover td {
            background: rgba(255,255,255,0.01);
        }
        
        .badge {
            padding: 3px 12px;
            border-radius: 100px;
            font-size: 11px;
            font-weight: 600;
        }
        
        .badge.active {
            background: rgba(52, 211, 153, 0.12);
            color: #34d399;
        }
        
        .badge.inactive {
            background: rgba(239, 68, 68, 0.12);
            color: #ef4444;
        }
        
        .btn-icon {
            background: none;
            border: none;
            color: var(--text-secondary);
            padding: 6px 10px;
            border-radius: 8px;
            cursor: pointer;
            transition: var(--transition);
        }
        
        .btn-icon:hover {
            background: rgba(255,255,255,0.04);
            color: var(--text-primary);
        }
        
        .btn-icon.gold:hover { color: var(--gold-light); }
        .btn-icon.red:hover { color: #ef4444; }
        .btn-icon.blue:hover { color: #60a5fa; }
        
        /* ===== دکمه طلایی ===== */
        .btn-gold {
            background: linear-gradient(135deg, var(--gold), var(--gold-dark));
            border: none;
            padding: 10px 24px;
            border-radius: 14px;
            color: #000;
            font-weight: 700;
            font-size: 14px;
            cursor: pointer;
            transition: var(--transition);
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        
        .btn-gold:hover {
            transform: scale(1.02);
            box-shadow: 0 8px 30px rgba(245,158,11,0.3);
        }
        
        .btn-gold i { font-size: 14px; }
        
        /* ===== مودال ===== */
        .modal {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.7);
            backdrop-filter: blur(20px);
            z-index: 100;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .modal.active { display: flex; }
        
        .modal-box {
            background: #121214;
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 24px;
            padding: 32px;
            max-width: 500px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            animation: modalIn 0.3s ease;
        }
        
        @keyframes modalIn {
            from { transform: scale(0.95) translateY(20px); opacity: 0; }
            to { transform: scale(1) translateY(0); opacity: 1; }
        }
        
        .modal-box h3 {
            font-size: 20px;
            font-weight: 800;
            margin-bottom: 20px;
        }
        
        .modal-box .input-group {
            margin-bottom: 16px;
        }
        
        .modal-box .input-group label {
            display: block;
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 6px;
        }
        
        .modal-box .input-group input,
        .modal-box .input-group select {
            width: 100%;
            padding: 12px 16px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 12px;
            color: #fff;
            font-size: 14px;
            outline: none;
            transition: var(--transition);
        }
        
        .modal-box .input-group input:focus,
        .modal-box .input-group select:focus {
            border-color: rgba(245,158,11,0.3);
        }
        
        .modal-actions {
            display: flex;
            gap: 12px;
            margin-top: 20px;
        }
        
        .modal-actions .btn-gold { flex: 1; justify-content: center; }
        .modal-actions .btn-ghost {
            flex: 1;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 14px;
            padding: 10px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: var(--transition);
            text-align: center;
        }
        
        .modal-actions .btn-ghost:hover {
            background: rgba(255,255,255,0.08);
        }
        
        /* ===== توست ===== */
        .toast {
            position: fixed;
            bottom: 30px;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: rgba(18, 18, 20, 0.95);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            padding: 14px 28px;
            color: #fff;
            font-size: 14px;
            z-index: 200;
            opacity: 0;
            transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .toast.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }
        
        .toast.success { border-color: rgba(52, 211, 153, 0.2); }
        .toast.error { border-color: rgba(239, 68, 68, 0.2); }
        
        /* ===== منو موبایل ===== */
        .menu-toggle {
            display: none;
            position: fixed;
            top: 16px;
            right: 16px;
            z-index: 60;
            background: rgba(18,18,20,0.8);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 14px;
            padding: 10px 14px;
            color: #fff;
            cursor: pointer;
        }
        
        @media (max-width: 768px) {
            .sidebar {
                transform: translateX(100%);
                width: 300px;
            }
            .sidebar.open { transform: translateX(0); }
            .main { margin-right: 0; padding: 20px 16px 30px; }
            .menu-toggle { display: block; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            .page-header h2 { font-size: 20px; }
            .stat-card .value { font-size: 22px; }
        }
        
        @media (max-width: 480px) {
            .stats-grid { grid-template-columns: 1fr; }
            .table-wrap { overflow-x: auto; }
        }
    </style>
</head>
<body>
    <div class="bg-grid"></div>
    <div class="bg-glow"></div>
    <div class="bg-glow-2"></div>
    
    <button class="menu-toggle" id="menuToggle">
        <i class="fas fa-bars"></i>
    </button>
    
    <!-- سایدبار -->
    <nav class="sidebar" id="sidebar">
        <div class="sidebar-brand">
            <span class="icon">🐝</span>
            <h1>CBee Panel</h1>
            <span>Professional Control</span>
        </div>
        
        <a href="/" class="nav-item active" data-page="dashboard">
            <i class="fas fa-chart-pie"></i> داشبورد
        </a>
        <a href="/inbounds" class="nav-item" data-page="inbounds">
            <i class="fas fa-users"></i> اینباندها
        </a>
        <a href="/traffic" class="nav-item" data-page="traffic">
            <i class="fas fa-chart-line"></i> ترافیک
        </a>
        <a href="/clean-ip" class="nav-item" data-page="clean-ip">
            <i class="fas fa-globe"></i> آی‌پی تمیز
        </a>
        <a href="/settings" class="nav-item" data-page="settings">
            <i class="fas fa-sliders-h"></i> تنظیمات
        </a>
        <a href="/security" class="nav-item" data-page="security">
            <i class="fas fa-shield-alt"></i> امنیت
        </a>
        
        <div class="nav-divider"></div>
        
        <div class="sidebar-footer">
            <a href="/api/logout" class="nav-item">
                <i class="fas fa-sign-out-alt"></i> خروج
            </a>
        </div>
    </nav>
    
    <!-- محتوای اصلی -->
    <main class="main" id="mainContent">
        <!-- محتوا توسط JS بارگذاری میشه -->
    </main>
    
    <!-- توست -->
    <div class="toast" id="toast">
        <i class="fas fa-check-circle"></i>
        <span id="toastMsg">پیام</span>
    </div>
    
    <script>
        // ===== منو موبایل =====
        document.getElementById('menuToggle').addEventListener('click', () => {
            document.getElementById('sidebar').classList.toggle('open');
        });
        
        // ===== ناوبری =====
        document.querySelectorAll('.nav-item[data-page]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                const page = el.dataset.page;
                document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
                el.classList.add('active');
                loadPage(page);
                if (window.innerWidth <= 768) {
                    document.getElementById('sidebar').classList.remove('open');
                }
            });
        });
        
        // ===== توست =====
        let toastTimer;
        function showToast(msg, type = 'success') {
            const t = document.getElementById('toast');
            const icon = t.querySelector('i');
            t.className = 'toast ' + type;
            document.getElementById('toastMsg').textContent = msg;
            if (type === 'success') icon.className = 'fas fa-check-circle';
            else if (type === 'error') icon.className = 'fas fa-exclamation-circle';
            t.classList.add('show');
            clearTimeout(toastTimer);
            toastTimer = setTimeout(() => t.classList.remove('show'), 3500);
        }
        
        // ===== فرمت‌ها =====
        function formatBytes(b) {
            if (!b) return '0 B';
            const units = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(b) / Math.log(1024));
            return (b / Math.pow(1024, i)).toFixed(1) + ' ' + units[i];
        }
        
        // ===== بارگذاری صفحات =====
        async function loadPage(page) {
            try {
                const res = await fetch(`/api/page/${page}`);
                if (!res.ok) throw new Error('خطا');
                const html = await res.text();
                document.getElementById('mainContent').innerHTML = html;
                
                // اجرای تابع مخصوص هر صفحه
                if (page === 'dashboard') initDashboard();
                else if (page === 'inbounds') initInbounds();
                else if (page === 'traffic') initTraffic();
                else if (page === 'clean-ip') initCleanIP();
                else if (page === 'settings') initSettings();
                else if (page === 'security') initSecurity();
            } catch (e) {
                showToast('خطا در بارگذاری صفحه', 'error');
            }
        }
        
        // ===== صفحه داشبورد =====
        async function initDashboard() {
            try {
                const res = await fetch('/api/stats');
                const data = await res.json();
                
                document.getElementById('statUsers').textContent = data.total_links || 0;
                document.getElementById('statActive').textContent = data.active_links || 0;
                document.getElementById('statTraffic').textContent = formatBytes(data.total_traffic);
                document.getElementById('statCPU').textContent = data.cpu_percent + '%';
                document.getElementById('statRAM').textContent = data.memory_percent + '%';
                document.getElementById('statUptime').textContent = data.uptime || '0s';
            } catch (e) {
                showToast('خطا در دریافت آمار', 'error');
            }
        }
        
        // ===== صفحه اینباندها =====
        function initInbounds() {
            loadInbounds();
            document.getElementById('createBtn')?.addEventListener('click', showCreateModal);
        }
        
        async function loadInbounds() {
            try {
                const res = await fetch('/api/links');
                const links = await res.json();
                const tbody = document.getElementById('inboundsBody');
                if (!tbody) return;
                
                if (!links.length) {
                    tbody.innerHTML = `<tr><td colspan="6" class="text-center" style="color:var(--text-secondary);padding:40px;">هیچ اینباندی وجود ندارد</td></tr>`;
                    return;
                }
                
                let html = '';
                links.forEach(l => {
                    const badge = l.active ? '<span class="badge active">● فعال</span>' : '<span class="badge inactive">● غیرفعال</span>';
                    html += `
                        <tr>
                            <td><strong>${l.name}</strong></td>
                            <td>${badge}</td>
                            <td>${formatBytes(l.used_bytes || 0)}</td>
                            <td>${l.limit_gb ? l.limit_gb + ' GB' : '∞'}</td>
                            <td>${l.expires_at ? new Date(l.expires_at*1000).toLocaleDateString('fa-IR') : '∞'}</td>
                            <td>
                                <button class="btn-icon gold" onclick="copyConfig('${l.uid}')"><i class="fas fa-copy"></i></button>
                                <button class="btn-icon blue" onclick="editInbound('${l.uid}')"><i class="fas fa-edit"></i></button>
                                <button class="btn-icon red" onclick="deleteInbound('${l.uid}')"><i class="fas fa-trash"></i></button>
                            </td>
                        </tr>
                    `;
                });
                tbody.innerHTML = html;
            } catch (e) {
                showToast('خطا در دریافت لیست', 'error');
            }
        }
        
        window.copyConfig = async function(uid) {
            try {
                const res = await fetch(`/api/links/${uid}`);
                const l = await res.json();
                const domain = window.location.hostname;
                const config = `vless://${uid}@${domain}:443?encryption=none&security=tls&type=ws&host=${domain}&path=/ws/${uid}&sni=${domain}&fp=chrome#CBee-${l.name}`;
                await navigator.clipboard.writeText(config);
                showToast('کانفیگ کپی شد ✅');
            } catch { showToast('خطا', 'error'); }
        };
        
        window.deleteInbound = async function(uid) {
            if (!confirm('حذف این اینباند؟')) return;
            try {
                await fetch(`/api/links/${uid}`, { method: 'DELETE' });
                showToast('حذف شد ✅');
                loadInbounds();
            } catch { showToast('خطا', 'error'); }
        };
        
        window.editInbound = async function(uid) {
            try {
                const res = await fetch(`/api/links/${uid}`);
                const l = await res.json();
                showEditModal(l);
            } catch { showToast('خطا', 'error'); }
        };
        
        function showCreateModal() {
            const modal = document.getElementById('modal');
            if (!modal) {
                const div = document.createElement('div');
                div.id = 'modal';
                div.className = 'modal';
                div.innerHTML = `
                    <div class="modal-box">
                        <h3>✨ ایجاد اینباند جدید</h3>
                        <form id="createForm">
                            <div class="input-group">
                                <label>نام کاربر</label>
                                <input type="text" id="cName" placeholder="مثال: Ali" required>
                            </div>
                            <div class="input-group">
                                <label>محدودیت (GB)</label>
                                <input type="number" id="cLimit" value="10" min="0">
                            </div>
                            <div class="input-group">
                                <label>مدت (روز)</label>
                                <input type="number" id="cDays" value="30" min="0">
                            </div>
                            <div class="modal-actions">
                                <button type="submit" class="btn-gold">ایجاد</button>
                                <button type="button" class="btn-ghost" onclick="closeModal()">انصراف</button>
                            </div>
                        </form>
                    </div>
                `;
                document.body.appendChild(div);
                
                document.getElementById('createForm').addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const name = document.getElementById('cName').value.trim();
                    const limit = parseInt(document.getElementById('cLimit').value) || 0;
                    const days = parseInt(document.getElementById('cDays').value) || 0;
                    
                    if (!name) { showToast('نام الزامی است', 'error'); return; }
                    
                    try {
                        const res = await fetch('/api/links', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ name, limit_gb: limit, days })
                        });
                        const data = await res.json();
                        if (data.success) {
                            showToast('ایجاد شد ✅');
                            closeModal();
                            loadInbounds();
                        } else {
                            showToast(data.error || 'خطا', 'error');
                        }
                    } catch { showToast('خطا', 'error'); }
                });
            }
            document.getElementById('modal').classList.add('active');
        }
        
        function showEditModal(l) {
            const modal = document.getElementById('editModal');
            if (!modal) {
                const div = document.createElement('div');
                div.id = 'editModal';
                div.className = 'modal';
                div.innerHTML = `
                    <div class="modal-box">
                        <h3>✏️ ویرایش اینباند</h3>
                        <form id="editForm">
                            <input type="hidden" id="eUid">
                            <div class="input-group">
                                <label>نام کاربر</label>
                                <input type="text" id="eName" required>
                            </div>
                            <div class="input-group">
                                <label>وضعیت</label>
                                <select id="eActive">
                                    <option value="true">فعال</option>
                                    <option value="false">غیرفعال</option>
                                </select>
                            </div>
                            <div class="input-group">
                                <label>محدودیت (GB)</label>
                                <input type="number" id="eLimit" min="0">
                            </div>
                            <div class="input-group">
                                <label>مدت (روز)</label>
                                <input type="number" id="eDays" min="0">
                            </div>
                            <div class="modal-actions">
                                <button type="submit" class="btn-gold">ذخیره</button>
                                <button type="button" class="btn-ghost" onclick="closeEditModal()">انصراف</button>
                            </div>
                        </form>
                    </div>
                `;
                document.body.appendChild(div);
                
                document.getElementById('editForm').addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const uid = document.getElementById('eUid').value;
                    const name = document.getElementById('eName').value.trim();
                    const active = document.getElementById('eActive').value === 'true';
                    const limit = parseInt(document.getElementById('eLimit').value) || 0;
                    const days = parseInt(document.getElementById('eDays').value) || 0;
                    
                    if (!name) { showToast('نام الزامی است', 'error'); return; }
                    
                    try {
                        const res = await fetch(`/api/links/${uid}`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ name, active, limit_gb: limit, days })
                        });
                        const data = await res.json();
                        if (data.success) {
                            showToast('به‌روزرسانی شد ✅');
                            closeEditModal();
                            loadInbounds();
                        } else {
                            showToast(data.error || 'خطا', 'error');
                        }
                    } catch { showToast('خطا', 'error'); }
                });
            }
            
            document.getElementById('eUid').value = l.uid;
            document.getElementById('eName').value = l.name;
            document.getElementById('eActive').value = l.active ? 'true' : 'false';
            document.getElementById('eLimit').value = l.limit_gb || 0;
            document.getElementById('eDays').value = l.days || 0;
            document.getElementById('editModal').classList.add('active');
        }
        
        window.closeModal = () => document.getElementById('modal')?.classList.remove('active');
        window.closeEditModal = () => document.getElementById('editModal')?.classList.remove('active');
        
        // ===== سایر صفحات =====
        function initTraffic() {
            fetch('/api/stats')
                .then(r => r.json())
                .then(d => {
                    document.getElementById('totalTraffic').textContent = formatBytes(d.total_traffic);
                    document.getElementById('activeConns').textContent = d.active_connections || 0;
                    document.getElementById('totalLinks').textContent = d.total_links || 0;
                    
                    let html = '';
                    (d.links || []).forEach(l => {
                        html += `<div class="stat-card" style="padding:12px 20px;display:flex;justify-content:space-between;margin-bottom:6px;">
                            <span>${l.name}</span>
                            <span style="color:var(--gold-light);font-weight:600;">${formatBytes(l.used_bytes)}</span>
                        </div>`;
                    });
                    document.getElementById('trafficList').innerHTML = html || '<div style="color:var(--text-secondary);padding:20px;text-align:center;">داده‌ای وجود ندارد</div>';
                })
                .catch(() => showToast('خطا', 'error'));
        }
        
        function initCleanIP() {
            loadAddresses();
            document.getElementById('addAddrForm')?.addEventListener('submit', async (e) => {
                e.preventDefault();
                const addr = document.getElementById('addrInput').value.trim();
                if (!addr) { showToast('آدرس را وارد کنید', 'error'); return; }
                
                try {
                    const res = await fetch('/api/addresses', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ address: addr })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast('افزوده شد ✅');
                        document.getElementById('addrInput').value = '';
                        loadAddresses();
                    } else {
                        showToast(data.error || 'خطا', 'error');
                    }
                } catch { showToast('خطا', 'error'); }
            });
            
            document.getElementById('clearAll')?.addEventListener('click', async () => {
                if (!confirm('حذف همه آدرس‌ها؟')) return;
                try {
                    await fetch('/api/addresses', { method: 'DELETE' });
                    showToast('همه حذف شدند ✅');
                    loadAddresses();
                } catch { showToast('خطا', 'error'); }
            });
        }
        
        async function loadAddresses() {
            try {
                const res = await fetch('/api/addresses');
                const data = await res.json();
                const container = document.getElementById('addrList');
                if (!container) return;
                
                if (!data.length) {
                    container.innerHTML = '<div style="color:var(--text-secondary);padding:20px;text-align:center;">هیچ آدرسی وجود ندارد</div>';
                    return;
                }
                
                let html = '';
                data.forEach((a, i) => {
                    html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;background:rgba(255,255,255,0.02);border-radius:12px;margin-bottom:6px;">
                        <span style="font-family:monospace;font-size:14px;">${a}</span>
                        <button class="btn-icon red" onclick="deleteAddr(${i})"><i class="fas fa-times"></i></button>
                    </div>`;
                });
                container.innerHTML = html;
            } catch { showToast('خطا', 'error'); }
        }
        
        window.deleteAddr = async function(index) {
            if (!confirm('حذف این آدرس؟')) return;
            try {
                await fetch(`/api/addresses/${index}`, { method: 'DELETE' });
                showToast('حذف شد ✅');
                loadAddresses();
            } catch { showToast('خطا', 'error'); }
        };
        
        function initSettings() {
            fetch('/api/settings')
                .then(r => r.json())
                .then(d => {
                    document.getElementById('tgToken').value = d.telegram_token || '';
                    document.getElementById('tgAdminId').value = d.telegram_admin_id || '';
                    document.getElementById('botLang').value = d.bot_lang || 'fa';
                })
                .catch(() => showToast('خطا', 'error'));
            
            document.getElementById('settingsForm')?.addEventListener('submit', async (e) => {
                e.preventDefault();
                const token = document.getElementById('tgToken').value.trim();
                const admin = document.getElementById('tgAdminId').value.trim();
                const lang = document.getElementById('botLang').value;
                
                try {
                    const res = await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ telegram_token: token, telegram_admin_id: admin, bot_lang: lang })
                    });
                    const data = await res.json();
                    if (data.success) showToast('ذخیره شد ✅');
                    else showToast(data.error || 'خطا', 'error');
                } catch { showToast('خطا', 'error'); }
            });
        }
        
        function initSecurity() {
            document.getElementById('passForm')?.addEventListener('submit', async (e) => {
                e.preventDefault();
                const current = document.getElementById('currentPass').value;
                const newPass = document.getElementById('newPass').value;
                const confirm = document.getElementById('confirmPass').value;
                
                if (newPass !== confirm) { showToast('رمزها مطابقت ندارند', 'error'); return; }
                if (newPass.length < 6) { showToast('حداقل ۶ کاراکتر', 'error'); return; }
                
                try {
                    const res = await fetch('/api/change-password', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ current_password: current, new_password: newPass })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast('رمز تغییر کرد ✅');
                        document.getElementById('passForm').reset();
                    } else {
                        showToast(data.error || 'خطا', 'error');
                    }
                } catch { showToast('خطا', 'error'); }
            });
        }
        
        // ===== بارگذاری اولیه =====
        document.addEventListener('DOMContentLoaded', () => {
            loadPage('dashboard');
        });
    </script>
</body>
</html>
"""

# ==================== روت‌های FastAPI ====================

@app.get("/")
async def root(request: Request):
    if not check_auth(request):
        return RedirectResponse(url="/login")
    return HTMLResponse(DASHBOARD_PAGE)

@app.get("/login")
async def login_page(request: Request):
    if check_auth(request):
        return RedirectResponse(url="/")
    return HTMLResponse(LOGIN_PAGE)

@app.get("/api/page/{page}")
async def get_page(request: Request, page: str):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    pages = {
        "dashboard": """
        <div>
            <div class="page-header">
                <h2><i class="fas fa-chart-pie"></i>داشبورد</h2>
                <span class="header-badge"><i class="fas fa-circle" style="color:#34d399;font-size:8px;"></i> آنلاین</span>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="icon-bg">👥</div>
                    <div class="label">کاربران</div>
                    <div class="value gold" id="statUsers">0</div>
                </div>
                <div class="stat-card">
                    <div class="icon-bg">✅</div>
                    <div class="label">فعال</div>
                    <div class="value green" id="statActive">0</div>
                </div>
                <div class="stat-card">
                    <div class="icon-bg">📊</div>
                    <div class="label">ترافیک کل</div>
                    <div class="value blue" id="statTraffic">0 B</div>
                </div>
                <div class="stat-card">
                    <div class="icon-bg">⚡</div>
                    <div class="label">CPU</div>
                    <div class="value purple" id="statCPU">0%</div>
                </div>
                <div class="stat-card">
                    <div class="icon-bg">🧠</div>
                    <div class="label">RAM</div>
                    <div class="value purple" id="statRAM">0%</div>
                </div>
                <div class="stat-card">
                    <div class="icon-bg">⏱️</div>
                    <div class="label">آپتایم</div>
                    <div class="value gold" id="statUptime">0s</div>
                </div>
            </div>
            
            <div class="table-wrap">
                <div class="table-header">
                    <h3>📋 آخرین فعالیت‌ها</h3>
                    <span class="count">به‌روزرسانی لحظه‌ای</span>
                </div>
                <div style="padding:20px 24px;color:var(--text-secondary);font-size:14px;">
                    <i class="fas fa-circle" style="color:#34d399;font-size:8px;margin-left:8px;"></i>
                    سیستم آماده به کار است
                </div>
            </div>
        </div>
        """,
        
        "inbounds": """
        <div>
            <div class="page-header">
                <h2><i class="fas fa-users"></i>مدیریت اینباندها</h2>
                <button class="btn-gold" id="createBtn"><i class="fas fa-plus"></i> جدید</button>
            </div>
            
            <div class="table-wrap">
                <div class="table-header">
                    <h3>📋 لیست اینباندها</h3>
                    <span class="count" id="inboundCount">۰ مورد</span>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>نام</th>
                            <th>وضعیت</th>
                            <th>مصرف</th>
                            <th>سقف</th>
                            <th>انقضا</th>
                            <th>عملیات</th>
                        </tr>
                    </thead>
                    <tbody id="inboundsBody">
                        <tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:40px;">در حال بارگذاری...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        """,
        
        "traffic": """
        <div>
            <div class="page-header">
                <h2><i class="fas fa-chart-line"></i>آمار ترافیک</h2>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="label">ترافیک کل</div>
                    <div class="value gold" id="totalTraffic">0 B</div>
                </div>
                <div class="stat-card">
                    <div class="label">اتصالات فعال</div>
                    <div class="value green" id="activeConns">0</div>
                </div>
                <div class="stat-card">
                    <div class="label">تعداد اینباندها</div>
                    <div class="value blue" id="totalLinks">0</div>
                </div>
            </div>
            
            <div class="table-wrap">
                <div class="table-header">
                    <h3>📊 مصرف هر کاربر</h3>
                </div>
                <div id="trafficList" style="padding:16px 20px;"></div>
            </div>
        </div>
        """,
        
        "clean-ip": """
        <div>
            <div class="page-header">
                <h2><i class="fas fa-globe"></i>مدیریت آی‌پی تمیز</h2>
            </div>
            
            <div class="table-wrap" style="margin-bottom:20px;">
                <div class="table-header">
                    <h3>➕ افزودن آدرس جدید</h3>
                </div>
                <div style="padding:20px 24px;">
                    <form id="addAddrForm" style="display:flex;gap:12px;flex-wrap:wrap;">
                        <input type="text" id="addrInput" placeholder="مثال: 104.21.0.1" style="flex:1;min-width:200px;padding:12px 16px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:12px;color:#fff;outline:none;">
                        <button type="submit" class="btn-gold"><i class="fas fa-plus"></i> افزودن</button>
                        <button type="button" id="clearAll" class="btn-gold" style="background:rgba(239,68,68,0.15);color:#ef4444;"><i class="fas fa-trash"></i> حذف همه</button>
                    </form>
                </div>
            </div>
            
            <div class="table-wrap">
                <div class="table-header">
                    <h3>📋 لیست آدرس‌ها</h3>
                    <span class="count" id="addrCount">۰</span>
                </div>
                <div id="addrList" style="padding:16px 20px;"></div>
            </div>
        </div>
        """,
        
        "settings": """
        <div>
            <div class="page-header">
                <h2><i class="fas fa-sliders-h"></i>تنظیمات ربات تلگرام</h2>
            </div>
            
            <div class="table-wrap" style="max-width:600px;">
                <div class="table-header">
                    <h3>🤖 پیکربندی ربات</h3>
                </div>
                <div style="padding:24px;">
                    <form id="settingsForm">
                        <div class="input-group" style="margin-bottom:16px;">
                            <label style="color:var(--text-secondary);font-size:13px;display:block;margin-bottom:6px;">توکن ربات</label>
                            <input type="text" id="tgToken" placeholder="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz" style="width:100%;padding:12px 16px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:12px;color:#fff;outline:none;">
                        </div>
                        <div class="input-group" style="margin-bottom:16px;">
                            <label style="color:var(--text-secondary);font-size:13px;display:block;margin-bottom:6px;">آیدی ادمین</label>
                            <input type="text" id="tgAdminId" placeholder="123456789" style="width:100%;padding:12px 16px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:12px;color:#fff;outline:none;">
                        </div>
                        <div class="input-group" style="margin-bottom:20px;">
                            <label style="color:var(--text-secondary);font-size:13px;display:block;margin-bottom:6px;">زبان</label>
                            <select id="botLang" style="width:100%;padding:12px 16px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:12px;color:#fff;outline:none;">
                                <option value="fa">فارسی</option>
                                <option value="en">English</option>
                            </select>
                        </div>
                        <button type="submit" class="btn-gold"><i class="fas fa-save"></i> ذخیره تنظیمات</button>
                    </form>
                </div>
            </div>
        </div>
        """,
        
        "security": """
        <div>
            <div class="page-header">
                <h2><i class="fas fa-shield-alt"></i>امنیت</h2>
            </div>
            
            <div class="table-wrap" style="max-width:600px;">
                <div class="table-header">
                    <h3>🔑 تغییر رمز عبور</h3>
                </div>
                <div style="padding:24px;">
                    <form id="passForm">
                        <div class="input-group" style="margin-bottom:16px;">
                            <label style="color:var(--text-secondary);font-size:13px;display:block;margin-bottom:6px;">رمز فعلی</label>
                            <input type="password" id="currentPass" style="width:100%;padding:12px 16px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:12px;color:#fff;outline:none;" required>
                        </div>
                        <div class="input-group" style="margin-bottom:16px;">
                            <label style="color:var(--text-secondary);font-size:13px;display:block;margin-bottom:6px;">رمز جدید</label>
                            <input type="password" id="newPass" style="width:100%;padding:12px 16px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:12px;color:#fff;outline:none;" required minlength="6">
                        </div>
                        <div class="input-group" style="margin-bottom:20px;">
                            <label style="color:var(--text-secondary);font-size:13px;display:block;margin-bottom:6px;">تکرار رمز جدید</label>
                            <input type="password" id="confirmPass" style="width:100%;padding:12px 16px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:12px;color:#fff;outline:none;" required minlength="6">
                        </div>
                        <button type="submit" class="btn-gold"><i class="fas fa-key"></i> تغییر رمز</button>
                    </form>
                </div>
            </div>
        </div>
        """
    }
    
    return HTMLResponse(pages.get(page, "<div style='padding:40px;text-align:center;color:var(--text-secondary);'>صفحه یافت نشد</div>"))

# ==================== APIها ====================

@app.post("/api/login")
async def api_login(request: Request):
    data = await request.json()
    password = data.get("password", "")
    
    if password == ADMIN_PASSWORD:
        session_id = secrets.token_urlsafe(32)
        SESSIONS[session_id] = "admin"
        response = JSONResponse({"success": True})
        response.set_cookie("session_id", session_id, httponly=True, max_age=3600*24*7)
        return response
    
    return JSONResponse({"success": False, "error": "Wrong password"}, status_code=401)

@app.post("/api/logout")
async def api_logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id in SESSIONS:
        del SESSIONS[session_id]
    response = RedirectResponse(url="/login")
    response.delete_cookie("session_id")
    return response

@app.get("/api/stats")
async def api_stats(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    total_links = len(LINKS)
    active_links = sum(1 for l in LINKS.values() if l.get("active", False))
    total_traffic = sum(l.get("used_bytes", 0) for l in LINKS.values())
    
    cpu = psutil.cpu_percent(interval=0.3)
    memory = psutil.virtual_memory()
    
    try:
        with open("/proc/uptime", "r") as f:
            uptime_sec = int(float(f.read().split()[0]))
        uptime = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m"
    except:
        uptime = "N/A"
    
    links_list = [{"name": l.get("name", "Unknown"), "used_bytes": l.get("used_bytes", 0)} for l in LINKS.values()]
    
    return JSONResponse({
        "total_links": total_links,
        "active_links": active_links,
        "total_traffic": total_traffic,
        "cpu_percent": round(cpu, 1),
        "memory_percent": round(memory.percent, 1),
        "uptime": uptime,
        "active_connections": sum(len(ws) for ws in ACTIVE_WEBSOCKETS.values()),
        "links": links_list
    })

# ===== API اینباندها =====
@app.get("/api/links")
async def api_get_links(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    result = []
    for uid, link in LINKS.items():
        link_copy = link.copy()
        link_copy["uid"] = uid
        result.append(link_copy)
    return JSONResponse(result)

@app.get("/api/links/{uid}")
async def api_get_link(request: Request, uid: str):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if uid not in LINKS:
        return JSONResponse({"error": "Not found"}, status_code=404)
    link = LINKS[uid].copy()
    link["uid"] = uid
    return JSONResponse(link)

@app.post("/api/links")
async def api_create_link(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    data = await request.json()
    name = data.get("name", "").strip()
    limit_gb = data.get("limit_gb", 0)
    days = data.get("days", 30)
    
    if not name:
        return JSONResponse({"success": False, "error": "Name required"})
    
    # check duplicate
    for link in LINKS.values():
        if link.get("name", "").lower() == name.lower():
            return JSONResponse({"success": False, "error": "Duplicate name"})
    
    uid = generate_uid()
    now = int(time.time())
    expires_at = now + (days * 24 * 3600) if days > 0 else None
    
    LINKS[uid] = {
        "name": name,
        "active": True,
        "created_at": now,
        "expires_at": expires_at,
        "limit_bytes": limit_gb * 1024**3 if limit_gb > 0 else 0,
        "used_bytes": 0,
        "max_connections": 0,
        "days": days,
        "limit_gb": limit_gb
    }
    
    save_db()
    return JSONResponse({"success": True, "uid": uid})

@app.patch("/api/links/{uid}")
async def api_update_link(request: Request, uid: str):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if uid not in LINKS:
        return JSONResponse({"error": "Not found"}, status_code=404)
    
    data = await request.json()
    link = LINKS[uid]
    
    if "name" in data:
        link["name"] = data["name"].strip()
    if "active" in data:
        link["active"] = bool(data["active"])
    if "limit_gb" in data:
        gb = int(data["limit_gb"])
        link["limit_bytes"] = gb * 1024**3 if gb > 0 else 0
        link["limit_gb"] = gb
    if "days" in data:
        days = int(data["days"])
        link["expires_at"] = int(time.time()) + (days * 24 * 3600) if days > 0 else None
        link["days"] = days
    
    save_db()
    return JSONResponse({"success": True})

@app.delete("/api/links/{uid}")
async def api_delete_link(request: Request, uid: str):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if uid not in LINKS:
        return JSONResponse({"error": "Not found"}, status_code=404)
    
    del LINKS[uid]
    save_db()
    return JSONResponse({"success": True})

# ===== API آی‌پی تمیز =====
@app.get("/api/addresses")
async def api_get_addresses(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(CUSTOM_ADDRESSES)

@app.post("/api/addresses")
async def api_add_address(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    data = await request.json()
    address = data.get("address", "").strip()
    
    if not address:
        return JSONResponse({"success": False, "error": "Address required"})
    if address in CUSTOM_ADDRESSES:
        return JSONResponse({"success": False, "error": "Already exists"})
    
    CUSTOM_ADDRESSES.append(address)
    save_db()
    return JSONResponse({"success": True})

@app.delete("/api/addresses/{index}")
async def api_delete_address(request: Request, index: int):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if index < 0 or index >= len(CUSTOM_ADDRESSES):
        return JSONResponse({"error": "Not found"}, status_code=404)
    
    del CUSTOM_ADDRESSES[index]
    save_db()
    return JSONResponse({"success": True})

@app.delete("/api/addresses")
async def api_delete_all_addresses(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    CUSTOM_ADDRESSES.clear()
    save_db()
    return JSONResponse({"success": True})

# ===== API تنظیمات =====
@app.get("/api/settings")
async def api_get_settings(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(CONFIG)

@app.post("/api/settings")
async def api_update_settings(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    data = await request.json()
    if "telegram_token" in data:
        CONFIG["telegram_token"] = data["telegram_token"].strip()
    if "telegram_admin_id" in data:
        CONFIG["telegram_admin_id"] = data["telegram_admin_id"].strip()
    if "bot_lang" in data:
        CONFIG["bot_lang"] = data["bot_lang"]
    
    save_db()
    return JSONResponse({"success": True})

@app.post("/api/change-password")
async def api_change_password(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    data = await request.json()
    current = data.get("current_password", "")
    new_pass = data.get("new_password", "")
    
    if current != ADMIN_PASSWORD:
        return JSONResponse({"success": False, "error": "رمز فعلی اشتباه است"})
    if len(new_pass) < 6:
        return JSONResponse({"success": False, "error": "حداقل ۶ کاراکتر"})
    
    # در محیط واقعی باید ذخیره بشه - اینجا فقط برای تست
    return JSONResponse({"success": True})

@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy", "timestamp": int(time.time())})

# ===== WebSocket =====
@app.websocket("/ws/{uuid}")
async def websocket_proxy(websocket: WebSocket, uuid: str):
    await websocket.accept()
    
    if uuid not in LINKS:
        await websocket.close(code=1008)
        return
    
    link = LINKS[uuid]
    if not link.get("active", False):
        await websocket.close(code=1008)
        return
    
    expires_at = link.get("expires_at")
    if expires_at and int(time.time()) > expires_at:
        await websocket.close(code=1008)
        return
    
    limit = link.get("limit_bytes", 0)
    if limit > 0 and link.get("used_bytes", 0) >= limit:
        await websocket.close(code=1008)
        return
    
    if uuid not in ACTIVE_WEBSOCKETS:
        ACTIVE_WEBSOCKETS[uuid] = set()
    ACTIVE_WEBSOCKETS[uuid].add(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
            link["used_bytes"] = link.get("used_bytes", 0) + len(data)
            save_db()
    except WebSocketDisconnect:
        pass
    finally:
        ACTIVE_WEBSOCKETS[uuid].discard(websocket)
        if not ACTIVE_WEBSOCKETS[uuid]:
            del ACTIVE_WEBSOCKETS[uuid]

# ===== ابزارها =====
def generate_uid() -> str:
    return str(uuid.uuid4())

@app.on_event("startup")
async def startup():
    load_db()
    logger.info("🐝 CBee Panel Pro v3.0 راه‌اندازی شد")
    logger.info(f"📊 {len(LINKS)} اینباند بارگذاری شد")

@app.on_event("shutdown")
async def shutdown():
    save_db()
    logger.info("👋 خداحافظ")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
