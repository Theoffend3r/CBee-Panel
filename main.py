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
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import httpx
import websockets
from typing import Dict, List, Optional, Any
import threading
import logging

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ تنظیمات اولیه ============
app = FastAPI(title="CBee Panel", version="2.0.0")

# تنظیمات امنیتی
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
PORT = int(os.getenv("PORT", 8000))

# دیتابیس درون‌حافظه
DB_FILE = "panel_db.json"
LINKS: Dict[str, Dict] = {}
CUSTOM_ADDRESSES: List[str] = []
CONFIG = {
    "telegram_token": "",
    "telegram_admin_id": "",
    "bot_lang": "fa"
}
SESSIONS: Dict[str, str] = {}  # session_id -> username
ACTIVE_WEBSOCKETS: Dict[str, set] = {}
NOTIFIED_UIDS: set = set()
BOT_POLLING_TASK: Optional[asyncio.Task] = None
TELEGRAM_BOT = None

# ============ توابع دیتابیس ============
def load_db():
    """بارگذاری دیتابیس از فایل"""
    global LINKS, CUSTOM_ADDRESSES, CONFIG
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                LINKS = data.get("links", {})
                CUSTOM_ADDRESSES = data.get("addresses", [])
                CONFIG.update(data.get("config", {}))
                logger.info(f"✅ دیتابیس بارگذاری شد: {len(LINKS)} کاربر")
        except Exception as e:
            logger.error(f"❌ خطا در بارگذاری دیتابیس: {e}")
    else:
        # دیتابیس پیش‌فرض
        LINKS = {}
        CUSTOM_ADDRESSES = []
        CONFIG = {"telegram_token": "", "telegram_admin_id": "", "bot_lang": "fa"}
        save_db()

def save_db():
    """ذخیره دیتابیس در فایل"""
    try:
        data = {
            "links": LINKS,
            "addresses": CUSTOM_ADDRESSES,
            "config": CONFIG
        }
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"❌ خطا در ذخیره دیتابیس: {e}")
        return False

# ============ توابع کمکی ============
def hash_password(password: str) -> str:
    """هش کردن رمز عبور"""
    return hashlib.sha256((password + SECRET_KEY).encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """تایید رمز عبور"""
    return hash_password(password) == hashed

def generate_uid() -> str:
    """تولید UUID جدید"""
    return str(uuid.uuid4())

def get_domain() -> str:
    """دریافت دامنه از درخواست"""
    # در محیط واقعی از request استفاده می‌شود
    return "cbee-panel.onrender.com"

def get_client_ip(request: Request) -> str:
    """دریافت IP کلاینت"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def check_auth(request: Request) -> bool:
    """بررسی احراز هویت"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in SESSIONS:
        return False
    return True

def get_current_user(request: Request) -> Optional[str]:
    """دریافت کاربر فعلی"""
    session_id = request.cookies.get("session_id")
    if session_id and session_id in SESSIONS:
        return SESSIONS[session_id]
    return None

def generate_vless_config(uid: str, name: str, domain: str) -> str:
    """تولید کانفیگ VLESS"""
    # استفاده از آدرس‌های تمیز
    if CUSTOM_ADDRESSES:
        domain = CUSTOM_ADDRESSES[0]
    
    return f"vless://{uid}@{domain}:443?encryption=none&security=tls&type=ws&host={domain}&path=/ws/{uid}&sni={domain}&fp=chrome&alpn=http/1.1#CBee-{name}"

def get_subscription(uid: str) -> str:
    """تولید لینک اشتراک"""
    if uid not in LINKS:
        return ""
    link = LINKS[uid]
    domain = get_domain()
    if CUSTOM_ADDRESSES:
        domain = CUSTOM_ADDRESSES[0]
    
    config = generate_vless_config(uid, link["name"], domain)
    # تبدیل به Base64
    import base64
    return base64.b64encode(config.encode()).decode()

# ============ صفحه HTML اصلی (تم زنبوری) ============
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🐝 CBee Panel</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700;900&display=swap');
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Vazirmatn', sans-serif;
            background: #0a0a0a;
            color: #e5e5e5;
            min-height: 100vh;
            overflow-x: hidden;
        }
        
        :root {
            --bee-gold: #f59e0b;
            --bee-gold-light: #fbbf24;
            --bee-gold-dark: #b45309;
            --bee-dark: #0a0a0a;
            --bee-card: rgba(255, 255, 255, 0.05);
            --bee-border: rgba(245, 158, 11, 0.3);
            --bee-shadow: 0 8px 32px rgba(245, 158, 11, 0.1);
        }
        
        /* پس‌زمینه شش‌ضلعی */
        .hex-bg {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
            pointer-events: none;
            opacity: 0.05;
            background-image: 
                linear-gradient(30deg, var(--bee-gold) 12%, transparent 12.5%, transparent 87%, var(--bee-gold) 87.5%),
                linear-gradient(150deg, var(--bee-gold) 12%, transparent 12.5%, transparent 87%, var(--bee-gold) 87.5%),
                linear-gradient(30deg, var(--bee-gold) 12%, transparent 12.5%, transparent 87%, var(--bee-gold) 87.5%),
                linear-gradient(150deg, var(--bee-gold) 12%, transparent 12.5%, transparent 87%, var(--bee-gold) 87.5%);
            background-size: 80px 140px;
            background-position: 0 0, 0 0, 40px 70px, 40px 70px;
        }
        
        /* کارت‌های شیشه‌ای */
        .glass-card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border: 1px solid rgba(245, 158, 11, 0.15);
            border-radius: 20px;
            padding: 24px;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
        }
        
        .glass-card::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle at 30% 50%, rgba(245, 158, 11, 0.03), transparent 70%);
            opacity: 0;
            transition: opacity 0.6s;
            pointer-events: none;
        }
        
        .glass-card:hover::before {
            opacity: 1;
        }
        
        .glass-card:hover {
            transform: translateY(-4px);
            border-color: rgba(245, 158, 11, 0.4);
            box-shadow: 0 12px 40px rgba(245, 158, 11, 0.15);
        }
        
        /* دکمه زنبوری */
        .btn-bee {
            background: linear-gradient(135deg, var(--bee-gold), var(--bee-gold-dark));
            color: #000;
            font-weight: 700;
            padding: 10px 24px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 20px rgba(245, 158, 11, 0.3);
            position: relative;
            overflow: hidden;
        }
        
        .btn-bee::after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.2), transparent 60%);
            opacity: 0;
            transition: opacity 0.4s;
        }
        
        .btn-bee:hover::after {
            opacity: 1;
        }
        
        .btn-bee:hover {
            transform: scale(1.05) translateY(-2px);
            box-shadow: 0 8px 30px rgba(245, 158, 11, 0.5);
        }
        
        .btn-bee:active {
            transform: scale(0.95);
        }
        
        /* آیکن زنبور متحرک */
        .bee-icon {
            display: inline-block;
            animation: buzz 3s infinite ease-in-out;
        }
        
        @keyframes buzz {
            0%, 100% { transform: translateY(0) rotate(0deg) scale(1); }
            25% { transform: translateY(-5px) rotate(5deg) scale(1.05); }
            50% { transform: translateY(0) rotate(-3deg) scale(0.95); }
            75% { transform: translateY(-3px) rotate(3deg) scale(1.02); }
        }
        
        /* نوار اسکرول */
        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #1a1a1a;
        }
        ::-webkit-scrollbar-thumb {
            background: var(--bee-gold);
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--bee-gold-light);
        }
        
        /* انیمیشن شمارنده */
        .counter {
            font-size: 2.5rem;
            font-weight: 900;
            background: linear-gradient(135deg, var(--bee-gold-light), var(--bee-gold));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        /* سایدبار */
        .sidebar {
            background: rgba(10, 10, 10, 0.95);
            backdrop-filter: blur(20px);
            border-left: 1px solid rgba(245, 158, 11, 0.1);
            width: 280px;
            height: 100vh;
            position: fixed;
            right: 0;
            top: 0;
            z-index: 50;
            padding: 24px 16px;
            transform: translateX(0);
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            overflow-y: auto;
        }
        
        .sidebar.closed {
            transform: translateX(100%);
        }
        
        .sidebar-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            border-radius: 12px;
            color: #a0a0a0;
            transition: all 0.3s;
            cursor: pointer;
            text-decoration: none;
        }
        
        .sidebar-item:hover, .sidebar-item.active {
            background: rgba(245, 158, 11, 0.1);
            color: var(--bee-gold-light);
        }
        
        .sidebar-item i {
            width: 24px;
            text-align: center;
        }
        
        .menu-toggle {
            position: fixed;
            top: 16px;
            right: 16px;
            z-index: 51;
            background: rgba(245, 158, 11, 0.2);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(245, 158, 11, 0.3);
            border-radius: 12px;
            padding: 10px 14px;
            color: var(--bee-gold);
            cursor: pointer;
            transition: all 0.3s;
            display: none;
        }
        
        .menu-toggle:hover {
            background: rgba(245, 158, 11, 0.3);
        }
        
        @media (max-width: 768px) {
            .sidebar {
                width: 100%;
                transform: translateX(100%);
            }
            .sidebar.open {
                transform: translateX(0);
            }
            .menu-toggle {
                display: block;
            }
        }
        
        /* ورودی‌ها */
        .form-input {
            width: 100%;
            padding: 12px 16px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            color: #e5e5e5;
            transition: all 0.3s;
            outline: none;
        }
        
        .form-input:focus {
            border-color: var(--bee-gold);
            box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.1);
        }
        
        .form-input::placeholder {
            color: #666;
        }
        
        .form-label {
            display: block;
            margin-bottom: 6px;
            color: #a0a0a0;
            font-size: 0.9rem;
        }
        
        /* تگ‌ها */
        .badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 700;
        }
        
        .badge-active {
            background: rgba(34, 197, 94, 0.2);
            color: #22c55e;
        }
        
        .badge-inactive {
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
        }
        
        /* مودال */
        .modal {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            backdrop-filter: blur(10px);
            z-index: 100;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .modal.active {
            display: flex;
        }
        
        .modal-content {
            background: #1a1a1a;
            border: 1px solid rgba(245, 158, 11, 0.2);
            border-radius: 24px;
            padding: 32px;
            max-width: 500px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            animation: slideUp 0.3s ease;
        }
        
        @keyframes slideUp {
            from { transform: translateY(20px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        
        /* جدول */
        .table-container {
            overflow-x: auto;
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            text-align: right;
            padding: 12px 16px;
            background: rgba(255, 255, 255, 0.03);
            color: #a0a0a0;
            font-weight: 700;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }
        
        td {
            padding: 12px 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
        }
        
        tr:hover td {
            background: rgba(245, 158, 11, 0.03);
        }
        
        /* صفحه لاگین */
        .login-container {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            z-index: 1;
            padding: 20px;
        }
        
        .login-box {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(245, 158, 11, 0.2);
            border-radius: 32px;
            padding: 48px;
            width: 100%;
            max-width: 420px;
            text-align: center;
        }
        
        .login-title {
            font-size: 2rem;
            font-weight: 900;
            background: linear-gradient(135deg, var(--bee-gold-light), var(--bee-gold));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }
        
        .login-subtitle {
            color: #a0a0a0;
            margin-bottom: 32px;
        }
        
        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 200;
            background: #1a1a1a;
            border: 1px solid rgba(245, 158, 11, 0.3);
            border-radius: 16px;
            padding: 16px 24px;
            color: #e5e5e5;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }
        
        .toast.success { border-color: #22c55e; }
        .toast.error { border-color: #ef4444; }
    </style>
</head>
<body>
    <div class="hex-bg"></div>
    
    <!-- Toast Notification -->
    <div id="toast" class="toast">
        <i id="toastIcon" class="fas fa-check-circle text-green-500"></i>
        <span id="toastMessage">پیام</span>
    </div>
    
    <!-- Menu Toggle (Mobile) -->
    <button class="menu-toggle" id="menuToggle">
        <i class="fas fa-bars fa-lg"></i>
    </button>
    
    <!-- Sidebar -->
    <nav class="sidebar" id="sidebar">
        <div class="text-center mb-8">
            <div class="bee-icon text-5xl mb-2">🐝</div>
            <h1 class="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-amber-400 to-amber-600">CBee Panel</h1>
            <p class="text-xs text-gray-500 mt-1">v2.0.0 • Professional</p>
        </div>
        
        <div class="space-y-1">
            <a href="/" class="sidebar-item active" data-page="dashboard">
                <i class="fas fa-chart-pie"></i> داشبورد
            </a>
            <a href="/inbounds" class="sidebar-item" data-page="inbounds">
                <i class="fas fa-users"></i> اینباندها
            </a>
            <a href="/traffic" class="sidebar-item" data-page="traffic">
                <i class="fas fa-chart-line"></i> ترافیک
            </a>
            <a href="/clean-ip" class="sidebar-item" data-page="clean-ip">
                <i class="fas fa-network-wired"></i> آی‌پی تمیز
            </a>
            <a href="/settings" class="sidebar-item" data-page="settings">
                <i class="fas fa-cog"></i> تنظیمات
            </a>
            <a href="/security" class="sidebar-item" data-page="security">
                <i class="fas fa-shield-alt"></i> امنیت
            </a>
        </div>
        
        <div class="mt-auto pt-4 border-t border-gray-800">
            <a href="/api/logout" class="sidebar-item text-red-400 hover:bg-red-500/10">
                <i class="fas fa-sign-out-alt"></i> خروج
            </a>
        </div>
    </nav>
    
    <!-- Main Content -->
    <div class="main-content" style="margin-right: 280px; min-height: 100vh; position: relative; z-index: 1; padding: 24px;">
        <div class="max-w-7xl mx-auto" id="pageContent">
            <!-- Content will be loaded here -->
        </div>
    </div>
    
    <script>
        // ============ تنظیمات اولیه ============
        const API_BASE = '';
        let currentPage = 'dashboard';
        let toastTimeout = null;
        
        // ============ توابع کمکی ============
        function showToast(message, type = 'success') {
            const toast = document.getElementById('toast');
            const toastMessage = document.getElementById('toastMessage');
            const toastIcon = document.getElementById('toastIcon');
            
            toast.className = 'toast';
            if (type === 'success') {
                toast.classList.add('success');
                toastIcon.className = 'fas fa-check-circle text-green-500';
            } else if (type === 'error') {
                toast.classList.add('error');
                toastIcon.className = 'fas fa-exclamation-circle text-red-500';
            } else {
                toastIcon.className = 'fas fa-info-circle text-blue-500';
            }
            
            toastMessage.textContent = message;
            toast.classList.add('show');
            
            if (toastTimeout) clearTimeout(toastTimeout);
            toastTimeout = setTimeout(() => {
                toast.classList.remove('show');
            }, 4000);
        }
        
        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
        
        function formatDate(timestamp) {
            if (!timestamp) return 'نامحدود';
            const d = new Date(timestamp);
            return d.toLocaleDateString('fa-IR') + ' ' + d.toLocaleTimeString('fa-IR', {hour: '2-digit', minute:'2-digit'});
        }
        
        function getStatusBadge(active) {
            return active ? 
                '<span class="badge badge-active"><i class="fas fa-circle text-xs mr-1"></i> فعال</span>' :
                '<span class="badge badge-inactive"><i class="fas fa-circle text-xs mr-1"></i> غیرفعال</span>';
        }
        
        // ============ بارگذاری صفحات ============
        async function loadPage(page, data = null) {
            currentPage = page;
            
            // به‌روزرسانی سایدبار
            document.querySelectorAll('.sidebar-item').forEach(el => el.classList.remove('active'));
            document.querySelector(`.sidebar-item[data-page="${page}"]`)?.classList.add('active');
            
            try {
                const response = await fetch(`/api/page/${page}`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                
                if (!response.ok) {
                    if (response.status === 401) {
                        window.location.href = '/login';
                        return;
                    }
                    throw new Error('خطا در بارگذاری صفحه');
                }
                
                const html = await response.text();
                document.getElementById('pageContent').innerHTML = html;
                
                // اجرای اسکریپت‌های مخصوص صفحه
                if (page === 'dashboard') initDashboard();
                else if (page === 'inbounds') initInbounds();
                else if (page === 'clean-ip') initCleanIP();
                else if (page === 'settings') initSettings();
                else if (page === 'security') initSecurity();
                else if (page === 'traffic') initTraffic();
                
                // بستن سایدبار در موبایل
                if (window.innerWidth <= 768) {
                    document.getElementById('sidebar').classList.remove('open');
                }
            } catch (error) {
                console.error('Error loading page:', error);
                showToast('خطا در بارگذاری صفحه', 'error');
            }
        }
        
        // ============ مدیریت سایدبار ============
        document.getElementById('menuToggle')?.addEventListener('click', () => {
            document.getElementById('sidebar').classList.toggle('open');
        });
        
        document.querySelectorAll('.sidebar-item').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                const page = el.dataset.page;
                if (page) loadPage(page);
            });
        });
        
        // ============ صفحه داشبورد ============
        async function initDashboard() {
            try {
                const response = await fetch('/api/stats');
                if (!response.ok) throw new Error('خطا در دریافت آمار');
                const stats = await response.json();
                
                // به‌روزرسانی کارت‌ها
                document.getElementById('statUsers').textContent = stats.total_links || 0;
                document.getElementById('statActive').textContent = stats.active_links || 0;
                document.getElementById('statTraffic').textContent = formatBytes(stats.total_traffic || 0);
                document.getElementById('statCPU').textContent = stats.cpu_percent || 0;
                document.getElementById('statMemory').textContent = stats.memory_percent || 0;
                document.getElementById('statUptime').textContent = stats.uptime || '0s';
                
                // آپدیت نمودار (اگر وجود داشته باشد)
                if (typeof Chart !== 'undefined' && stats.hourly_data) {
                    const ctx = document.getElementById('trafficChart')?.getContext('2d');
                    if (ctx) {
                        new Chart(ctx, {
                            type: 'line',
                            data: {
                                labels: stats.hourly_data.map(d => d.hour),
                                datasets: [{
                                    label: 'ترافیک (MB)',
                                    data: stats.hourly_data.map(d => d.traffic),
                                    borderColor: '#f59e0b',
                                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                                    fill: true,
                                    tension: 0.4
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: {
                                        labels: { color: '#e5e5e5' }
                                    }
                                },
                                scales: {
                                    x: {
                                        ticks: { color: '#a0a0a0' }
                                    },
                                    y: {
                                        ticks: { color: '#a0a0a0' }
                                    }
                                }
                            }
                        });
                    }
                }
            } catch (error) {
                console.error('Dashboard error:', error);
            }
        }
        
        // ============ صفحه اینباندها ============
        function initInbounds() {
            // بارگذاری لیست اینباندها
            loadInboundsList();
            
            // دکمه ایجاد اینباند
            document.getElementById('createInboundBtn')?.addEventListener('click', () => {
                showCreateInboundModal();
            });
        }
        
        async function loadInboundsList() {
            try {
                const response = await fetch('/api/links');
                if (!response.ok) throw new Error('خطا در دریافت لیست');
                const links = await response.json();
                
                const tbody = document.getElementById('inboundsTableBody');
                if (!tbody) return;
                
                if (!links || links.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-gray-500 py-8">هیچ اینباندی وجود ندارد</td></tr>`;
                    return;
                }
                
                let html = '';
                links.forEach(link => {
                    html += `
                        <tr>
                            <td><span class="font-bold">${link.name}</span></td>
                            <td>${getStatusBadge(link.active)}</td>
                            <td>${formatBytes(link.used_bytes || 0)}</td>
                            <td>${link.limit_gb ? formatBytes(link.limit_gb * 1024**3) : 'نامحدود'}</td>
                            <td>${formatDate(link.expires_at)}</td>
                            <td>
                                <button onclick="copyConfig('${link.uid}')" class="text-amber-400 hover:text-amber-300 mx-1" title="کپی کانفیگ">
                                    <i class="fas fa-copy"></i>
                                </button>
                                <button onclick="showQR('${link.uid}')" class="text-amber-400 hover:text-amber-300 mx-1" title="QR Code">
                                    <i class="fas fa-qrcode"></i>
                                </button>
                                <button onclick="editInbound('${link.uid}')" class="text-blue-400 hover:text-blue-300 mx-1" title="ویرایش">
                                    <i class="fas fa-edit"></i>
                                </button>
                                <button onclick="deleteInbound('${link.uid}')" class="text-red-400 hover:text-red-300 mx-1" title="حذف">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    `;
                });
                
                tbody.innerHTML = html;
            } catch (error) {
                console.error('Error loading inbounds:', error);
                showToast('خطا در دریافت لیست اینباندها', 'error');
            }
        }
        
        window.copyConfig = function(uid) {
            fetch(`/api/links/${uid}`)
                .then(r => r.json())
                .then(link => {
                    const domain = document.querySelector('meta[name="domain"]')?.content || 'cbee-panel.onrender.com';
                    const config = `vless://${uid}@${domain}:443?encryption=none&security=tls&type=ws&host=${domain}&path=/ws/${uid}&sni=${domain}&fp=chrome&alpn=http/1.1#CBee-${link.name}`;
                    navigator.clipboard.writeText(config).then(() => {
                        showToast('کانفیگ کپی شد ✅');
                    }).catch(() => {
                        // Fallback
                        const textarea = document.createElement('textarea');
                        textarea.value = config;
                        document.body.appendChild(textarea);
                        textarea.select();
                        document.execCommand('copy');
                        document.body.removeChild(textarea);
                        showToast('کانفیگ کپی شد ✅');
                    });
                })
                .catch(() => showToast('خطا در دریافت کانفیگ', 'error'));
        };
        
        window.showQR = function(uid) {
            // ایجاد مودال QR
            const modal = document.getElementById('qrModal');
            if (!modal) {
                const div = document.createElement('div');
                div.id = 'qrModal';
                div.className = 'modal';
                div.innerHTML = `
                    <div class="modal-content text-center">
                        <h3 class="text-xl font-bold mb-4">QR Code</h3>
                        <div id="qrCodeContainer" class="flex justify-center my-4"></div>
                        <button onclick="closeModal('qrModal')" class="btn-bee mt-4">بستن</button>
                    </div>
                `;
                document.body.appendChild(div);
            }
            
            // ساخت QR با استفاده از API
            const domain = document.querySelector('meta[name="domain"]')?.content || 'cbee-panel.onrender.com';
            const config = `vless://${uid}@${domain}:443?encryption=none&security=tls&type=ws&host=${domain}&path=/ws/${uid}&sni=${domain}&fp=chrome&alpn=http/1.1#CBee-${uid}`;
            const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(config)}`;
            document.getElementById('qrCodeContainer').innerHTML = `<img src="${qrUrl}" alt="QR Code" class="rounded-lg">`;
            document.getElementById('qrModal').classList.add('active');
        };
        
        window.deleteInbound = function(uid) {
            if (!confirm('آیا از حذف این اینباند مطمئن هستید؟')) return;
            
            fetch(`/api/links/${uid}`, { method: 'DELETE' })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        showToast('اینباند حذف شد ✅');
                        loadInboundsList();
                    } else {
                        showToast(data.error || 'خطا در حذف', 'error');
                    }
                })
                .catch(() => showToast('خطا در حذف', 'error'));
        };
        
        window.editInbound = function(uid) {
            // بارگذاری داده‌های اینباند
            fetch(`/api/links/${uid}`)
                .then(r => r.json())
                .then(link => {
                    showEditInboundModal(link);
                })
                .catch(() => showToast('خطا در دریافت اطلاعات', 'error'));
        };
        
        function showCreateInboundModal() {
            const modal = document.getElementById('inboundModal');
            if (!modal) {
                const div = document.createElement('div');
                div.id = 'inboundModal';
                div.className = 'modal';
                div.innerHTML = `
                    <div class="modal-content">
                        <h3 class="text-xl font-bold mb-4">ایجاد اینباند جدید</h3>
                        <form id="inboundForm" class="space-y-4">
                            <div>
                                <label class="form-label">نام کاربر</label>
                                <input type="text" id="inboundName" class="form-input" placeholder="مثال: Ali" required>
                            </div>
                            <div>
                                <label class="form-label">محدودیت حجم (GB)</label>
                                <input type="number" id="inboundLimit" class="form-input" value="10" min="0">
                                <small class="text-gray-500">0 = نامحدود</small>
                            </div>
                            <div>
                                <label class="form-label">مدت اعتبار (روز)</label>
                                <input type="number" id="inboundDays" class="form-input" value="30" min="0">
                                <small class="text-gray-500">0 = بدون انقضا</small>
                            </div>
                            <div class="flex gap-3 mt-4">
                                <button type="submit" class="btn-bee flex-1">ایجاد</button>
                                <button type="button" onclick="closeModal('inboundModal')" class="flex-1 bg-gray-700 hover:bg-gray-600 text-white rounded-lg px-4 py-2 transition">انصراف</button>
                            </div>
                        </form>
                    </div>
                `;
                document.body.appendChild(div);
                
                document.getElementById('inboundForm').addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const name = document.getElementById('inboundName').value.trim();
                    const limit = parseInt(document.getElementById('inboundLimit').value) || 0;
                    const days = parseInt(document.getElementById('inboundDays').value) || 0;
                    
                    if (!name) {
                        showToast('لطفاً نام کاربر را وارد کنید', 'error');
                        return;
                    }
                    
                    try {
                        const response = await fetch('/api/links', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ name, limit_gb: limit, days })
                        });
                        const data = await response.json();
                        
                        if (data.success) {
                            showToast('اینباند ایجاد شد ✅');
                            closeModal('inboundModal');
                            loadInboundsList();
                        } else {
                            showToast(data.error || 'خطا در ایجاد', 'error');
                        }
                    } catch (error) {
                        showToast('خطا در ارتباط با سرور', 'error');
                    }
                });
            }
            
            document.getElementById('inboundModal').classList.add('active');
        }
        
        function showEditInboundModal(link) {
            const modal = document.getElementById('editInboundModal');
            if (!modal) {
                const div = document.createElement('div');
                div.id = 'editInboundModal';
                div.className = 'modal';
                div.innerHTML = `
                    <div class="modal-content">
                        <h3 class="text-xl font-bold mb-4">ویرایش اینباند</h3>
                        <form id="editInboundForm" class="space-y-4">
                            <div>
                                <label class="form-label">نام کاربر</label>
                                <input type="text" id="editName" class="form-input" required>
                            </div>
                            <div>
                                <label class="form-label">وضعیت</label>
                                <select id="editActive" class="form-input">
                                    <option value="true">فعال</option>
                                    <option value="false">غیرفعال</option>
                                </select>
                            </div>
                            <div>
                                <label class="form-label">محدودیت حجم (GB)</label>
                                <input type="number" id="editLimit" class="form-input" min="0">
                                <small class="text-gray-500">0 = نامحدود</small>
                            </div>
                            <div>
                                <label class="form-label">مدت اعتبار (روز)</label>
                                <input type="number" id="editDays" class="form-input" min="0">
                                <small class="text-gray-500">0 = بدون انقضا</small>
                            </div>
                            <div class="flex gap-3 mt-4">
                                <button type="submit" class="btn-bee flex-1">ذخیره</button>
                                <button type="button" onclick="closeModal('editInboundModal')" class="flex-1 bg-gray-700 hover:bg-gray-600 text-white rounded-lg px-4 py-2 transition">انصراف</button>
                            </div>
                        </form>
                    </div>
                `;
                document.body.appendChild(div);
                
                document.getElementById('editInboundForm').addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const uid = document.getElementById('editUid').value;
                    const name = document.getElementById('editName').value.trim();
                    const active = document.getElementById('editActive').value === 'true';
                    const limit = parseInt(document.getElementById('editLimit').value) || 0;
                    const days = parseInt(document.getElementById('editDays').value) || 0;
                    
                    if (!name) {
                        showToast('لطفاً نام کاربر را وارد کنید', 'error');
                        return;
                    }
                    
                    try {
                        const response = await fetch(`/api/links/${uid}`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ name, active, limit_gb: limit, days })
                        });
                        const data = await response.json();
                        
                        if (data.success) {
                            showToast('اینباند به‌روزرسانی شد ✅');
                            closeModal('editInboundModal');
                            loadInboundsList();
                        } else {
                            showToast(data.error || 'خطا در به‌روزرسانی', 'error');
                        }
                    } catch (error) {
                        showToast('خطا در ارتباط با سرور', 'error');
                    }
                });
            }
            
            document.getElementById('editUid').value = link.uid;
            document.getElementById('editName').value = link.name;
            document.getElementById('editActive').value = link.active ? 'true' : 'false';
            document.getElementById('editLimit').value = link.limit_gb || 0;
            document.getElementById('editDays').value = link.days || 0;
            document.getElementById('editInboundModal').classList.add('active');
        }
        
        window.closeModal = function(id) {
            document.getElementById(id)?.classList.remove('active');
        };
        
        // ============ صفحه آی‌پی تمیز ============
        function initCleanIP() {
            loadAddresses();
            
            document.getElementById('addAddressForm')?.addEventListener('submit', async (e) => {
                e.preventDefault();
                const address = document.getElementById('addressInput').value.trim();
                if (!address) {
                    showToast('لطفاً آدرس را وارد کنید', 'error');
                    return;
                }
                
                try {
                    const response = await fetch('/api/addresses', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ address })
                    });
                    const data = await response.json();
                    
                    if (data.success) {
                        showToast('آدرس اضافه شد ✅');
                        document.getElementById('addressInput').value = '';
                        loadAddresses();
                    } else {
                        showToast(data.error || 'خطا در افزودن', 'error');
                    }
                } catch (error) {
                    showToast('خطا در ارتباط با سرور', 'error');
                }
            });
            
            document.getElementById('clearAllAddresses')?.addEventListener('click', async () => {
                if (!confirm('آیا از حذف تمام آدرس‌ها مطمئن هستید؟')) return;
                
                try {
                    const response = await fetch('/api/addresses', { method: 'DELETE' });
                    const data = await response.json();
                    
                    if (data.success) {
                        showToast('همه آدرس‌ها حذف شدند ✅');
                        loadAddresses();
                    } else {
                        showToast(data.error || 'خطا در حذف', 'error');
                    }
                } catch (error) {
                    showToast('خطا در ارتباط با سرور', 'error');
                }
            });
        }
        
        async function loadAddresses() {
            try {
                const response = await fetch('/api/addresses');
                if (!response.ok) throw new Error('خطا در دریافت لیست');
                const addresses = await response.json();
                
                const container = document.getElementById('addressesList');
                if (!container) return;
                
                if (!addresses || addresses.length === 0) {
                    container.innerHTML = '<div class="text-center text-gray-500 py-8">هیچ آدرسی وجود ندارد</div>';
                    return;
                }
                
                let html = '<div class="space-y-2">';
                addresses.forEach((addr, index) => {
                    html += `
                        <div class="flex items-center justify-between bg-gray-800/30 rounded-lg px-4 py-3">
                            <span class="font-mono text-sm">${addr}</span>
                            <button onclick="deleteAddress(${index})" class="text-red-400 hover:text-red-300 transition">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                    `;
                });
                html += '</div>';
                container.innerHTML = html;
            } catch (error) {
                console.error('Error loading addresses:', error);
                showToast('خطا در دریافت لیست آدرس‌ها', 'error');
            }
        }
        
        window.deleteAddress = function(index) {
            if (!confirm('آیا از حذف این آدرس مطمئن هستید؟')) return;
            
            fetch(`/api/addresses/${index}`, { method: 'DELETE' })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        showToast('آدرس حذف شد ✅');
                        loadAddresses();
                    } else {
                        showToast(data.error || 'خطا در حذف', 'error');
                    }
                })
                .catch(() => showToast('خطا در حذف', 'error'));
        };
        
        // ============ صفحه تنظیمات ============
        function initSettings() {
            // بارگذاری تنظیمات فعلی
            fetch('/api/settings')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('tgToken').value = data.telegram_token || '';
                    document.getElementById('tgAdminId').value = data.telegram_admin_id || '';
                    document.getElementById('botLang').value = data.bot_lang || 'fa';
                })
                .catch(() => showToast('خطا در دریافت تنظیمات', 'error'));
            
            document.getElementById('settingsForm')?.addEventListener('submit', async (e) => {
                e.preventDefault();
                const token = document.getElementById('tgToken').value.trim();
                const adminId = document.getElementById('tgAdminId').value.trim();
                const lang = document.getElementById('botLang').value;
                
                try {
                    const response = await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ telegram_token: token, telegram_admin_id: adminId, bot_lang: lang })
                    });
                    const data = await response.json();
                    
                    if (data.success) {
                        showToast('تنظیمات ذخیره شد ✅');
                    } else {
                        showToast(data.error || 'خطا در ذخیره', 'error');
                    }
                } catch (error) {
                    showToast('خطا در ارتباط با سرور', 'error');
                }
            });
        }
        
        // ============ صفحه امنیت ============
        function initSecurity() {
            document.getElementById('changePasswordForm')?.addEventListener('submit', async (e) => {
                e.preventDefault();
                const current = document.getElementById('currentPassword').value;
                const newPass = document.getElementById('newPassword').value;
                const confirm = document.getElementById('confirmPassword').value;
                
                if (newPass !== confirm) {
                    showToast('رمزهای جدید مطابقت ندارند', 'error');
                    return;
                }
                
                if (newPass.length < 6) {
                    showToast('رمز عبور باید حداقل ۶ کاراکتر باشد', 'error');
                    return;
                }
                
                try {
                    const response = await fetch('/api/change-password', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ current_password: current, new_password: newPass })
                    });
                    const data = await response.json();
                    
                    if (data.success) {
                        showToast('رمز عبور با موفقیت تغییر کرد ✅');
                        document.getElementById('changePasswordForm').reset();
                    } else {
                        showToast(data.error || 'خطا در تغییر رمز', 'error');
                    }
                } catch (error) {
                    showToast('خطا در ارتباط با سرور', 'error');
                }
            });
        }
        
        // ============ صفحه ترافیک ============
        function initTraffic() {
            // بارگذاری آمار ترافیک
            fetch('/api/stats')
                .then(r => r.json())
                .then(stats => {
                    document.getElementById('totalTraffic').textContent = formatBytes(stats.total_traffic || 0);
                    document.getElementById('activeConnections').textContent = stats.active_connections || 0;
                    document.getElementById('totalInbounds').textContent = stats.total_links || 0;
                    
                    // نمایش لیست کاربران با مصرف
                    if (stats.links) {
                        let html = '';
                        stats.links.forEach(link => {
                            html += `
                                <div class="flex items-center justify-between glass-card mb-2">
                                    <span class="font-bold">${link.name}</span>
                                    <span>${formatBytes(link.used_bytes || 0)}</span>
                                </div>
                            `;
                        });
                        document.getElementById('trafficList').innerHTML = html || '<div class="text-center text-gray-500">هیچ داده‌ای وجود ندارد</div>';
                    }
                })
                .catch(() => showToast('خطا در دریافت آمار', 'error'));
        }
        
        // ============ بارگذاری اولیه ============
        document.addEventListener('DOMContentLoaded', () => {
            // تشخیص صفحه فعلی از URL
            const path = window.location.pathname;
            if (path === '/login') return;
            
            let page = 'dashboard';
            if (path.includes('/inbounds')) page = 'inbounds';
            else if (path.includes('/traffic')) page = 'traffic';
            else if (path.includes('/clean-ip')) page = 'clean-ip';
            else if (path.includes('/settings')) page = 'settings';
            else if (path.includes('/security')) page = 'security';
            
            loadPage(page);
        });
        
        // ============ بستن مودال با کلیک خارج ============
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                e.target.classList.remove('active');
            }
        });
    </script>
    
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</body>
</html>
"""

# ============ روت‌های FastAPI ============

@app.get("/")
async def root(request: Request):
    """صفحه اصلی"""
    if not check_auth(request):
        return RedirectResponse(url="/login")
    return HTMLResponse(HTML_TEMPLATE)

@app.get("/login")
async def login_page(request: Request):
    """صفحه ورود"""
    if check_auth(request):
        return RedirectResponse(url="/")
    
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="fa" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🐝 ورود | CBee Panel</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700;900&display=swap');
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Vazirmatn', sans-serif;
                background: #0a0a0a;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
                position: relative;
                overflow: hidden;
            }
            .hex-bg {
                position: fixed;
                top: 0; left: 0; width: 100%; height: 100%;
                opacity: 0.05;
                background-image: 
                    linear-gradient(30deg, #f59e0b 12%, transparent 12.5%, transparent 87%, #f59e0b 87.5%),
                    linear-gradient(150deg, #f59e0b 12%, transparent 12.5%, transparent 87%, #f59e0b 87.5%),
                    linear-gradient(30deg, #f59e0b 12%, transparent 12.5%, transparent 87%, #f59e0b 87.5%),
                    linear-gradient(150deg, #f59e0b 12%, transparent 12.5%, transparent 87%, #f59e0b 87.5%);
                background-size: 80px 140px;
                background-position: 0 0, 0 0, 40px 70px, 40px 70px;
                z-index: 0;
            }
            .login-box {
                background: rgba(255, 255, 255, 0.05);
                backdrop-filter: blur(20px);
                border: 1px solid rgba(245, 158, 11, 0.2);
                border-radius: 32px;
                padding: 48px;
                width: 100%;
                max-width: 420px;
                text-align: center;
                position: relative;
                z-index: 1;
                animation: slideUp 0.6s ease;
            }
            @keyframes slideUp {
                from { transform: translateY(30px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
            .bee-icon {
                font-size: 4rem;
                display: inline-block;
                animation: buzz 3s infinite ease-in-out;
                margin-bottom: 12px;
            }
            @keyframes buzz {
                0%, 100% { transform: translateY(0) rotate(0deg) scale(1); }
                25% { transform: translateY(-5px) rotate(5deg) scale(1.05); }
                50% { transform: translateY(0) rotate(-3deg) scale(0.95); }
                75% { transform: translateY(-3px) rotate(3deg) scale(1.02); }
            }
            .login-title {
                font-size: 2rem;
                font-weight: 900;
                background: linear-gradient(135deg, #fbbf24, #f59e0b);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                margin-bottom: 8px;
            }
            .login-subtitle { color: #a0a0a0; margin-bottom: 32px; }
            .form-input {
                width: 100%;
                padding: 14px 18px;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 14px;
                color: #e5e5e5;
                transition: all 0.3s;
                outline: none;
                font-size: 1rem;
            }
            .form-input:focus {
                border-color: #f59e0b;
                box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.1);
            }
            .form-input::placeholder { color: #666; }
            .btn-bee {
                width: 100%;
                background: linear-gradient(135deg, #f59e0b, #b45309);
                color: #000;
                font-weight: 700;
                padding: 14px;
                border: none;
                border-radius: 14px;
                cursor: pointer;
                transition: all 0.3s ease;
                box-shadow: 0 4px 20px rgba(245, 158, 11, 0.3);
                font-size: 1rem;
            }
            .btn-bee:hover {
                transform: scale(1.02);
                box-shadow: 0 8px 30px rgba(245, 158, 11, 0.5);
            }
            .btn-bee:active { transform: scale(0.98); }
            .toast {
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 200;
                background: #1a1a1a;
                border: 1px solid rgba(245, 158, 11, 0.3);
                border-radius: 16px;
                padding: 16px 24px;
                color: #e5e5e5;
                box-shadow: 0 8px 32px rgba(0,0,0,0.5);
                transform: translateY(100px);
                opacity: 0;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                align-items: center;
                gap: 12px;
            }
            .toast.show { transform: translateY(0); opacity: 1; }
            .toast.error { border-color: #ef4444; }
        </style>
    </head>
    <body>
        <div class="hex-bg"></div>
        
        <div class="login-box">
            <div class="bee-icon">🐝</div>
            <h1 class="login-title">CBee Panel</h1>
            <p class="login-subtitle">ورود به پنل مدیریت</p>
            
            <form id="loginForm" class="space-y-4">
                <div>
                    <input type="password" id="password" class="form-input" placeholder="رمز عبور" required autofocus>
                </div>
                <button type="submit" class="btn-bee">
                    <i class="fas fa-sign-in-alt ml-2"></i> ورود
                </button>
            </form>
            
            <p class="text-xs text-gray-600 mt-6">نسخه 2.0.0 • طراحی حرفه‌ای</p>
        </div>
        
        <div id="toast" class="toast error">
            <i class="fas fa-exclamation-circle"></i>
            <span id="toastMessage">خطا</span>
        </div>
        
        <script>
            document.getElementById('loginForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const password = document.getElementById('password').value;
                
                try {
                    const response = await fetch('/api/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ password })
                    });
                    const data = await response.json();
                    
                    if (data.success) {
                        window.location.href = '/';
                    } else {
                        showToast('رمز عبور اشتباه است');
                        document.getElementById('password').value = '';
                        document.getElementById('password').focus();
                    }
                } catch (error) {
                    showToast('خطا در ارتباط با سرور');
                }
            });
            
            function showToast(message) {
                const toast = document.getElementById('toast');
                const toastMessage = document.getElementById('toastMessage');
                toastMessage.textContent = message;
                toast.classList.add('show');
                setTimeout(() => toast.classList.remove('show'), 3000);
            }
            
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') document.getElementById('loginForm').dispatchEvent(new Event('submit'));
            });
        </script>
    </body>
    </html>
    """)

@app.get("/api/page/{page}")
async def get_page(request: Request, page: str):
    """API برای بارگذاری صفحات (AJAX)"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    pages = {
        "dashboard": """
        <div class="space-y-6">
            <div class="flex items-center justify-between">
                <h2 class="text-2xl font-bold"><i class="fas fa-chart-pie text-amber-400 ml-2"></i>داشبورد</h2>
                <span class="text-sm text-gray-500">به‌روزرسانی لحظه‌ای</span>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div class="glass-card">
                    <div class="flex items-center justify-between">
                        <span class="text-gray-400">کاربران</span>
                        <i class="fas fa-users text-amber-400 text-2xl"></i>
                    </div>
                    <div class="counter text-3xl font-black mt-2" id="statUsers">0</div>
                </div>
                <div class="glass-card">
                    <div class="flex items-center justify-between">
                        <span class="text-gray-400">فعال</span>
                        <i class="fas fa-check-circle text-green-400 text-2xl"></i>
                    </div>
                    <div class="counter text-3xl font-black mt-2" id="statActive">0</div>
                </div>
                <div class="glass-card">
                    <div class="flex items-center justify-between">
                        <span class="text-gray-400">ترافیک کل</span>
                        <i class="fas fa-chart-bar text-amber-400 text-2xl"></i>
                    </div>
                    <div class="counter text-3xl font-black mt-2" id="statTraffic">0 B</div>
                </div>
                <div class="glass-card">
                    <div class="flex items-center justify-between">
                        <span class="text-gray-400">سیستم</span>
                        <i class="fas fa-microchip text-amber-400 text-2xl"></i>
                    </div>
                    <div class="flex gap-4 mt-2">
                        <div><span class="text-gray-500 text-sm">CPU</span><br><span id="statCPU" class="font-bold">0%</span></div>
                        <div><span class="text-gray-500 text-sm">RAM</span><br><span id="statMemory" class="font-bold">0%</span></div>
                        <div><span class="text-gray-500 text-sm">آپتایم</span><br><span id="statUptime" class="font-bold">0s</span></div>
                    </div>
                </div>
            </div>
            
            <div class="glass-card">
                <h3 class="text-lg font-bold mb-4"><i class="fas fa-chart-line text-amber-400 ml-2"></i>نمودار ترافیک ساعتی</h3>
                <div style="height: 300px;">
                    <canvas id="trafficChart"></canvas>
                </div>
            </div>
        </div>
        """,
        
        "inbounds": """
        <div class="space-y-6">
            <div class="flex items-center justify-between flex-wrap gap-3">
                <h2 class="text-2xl font-bold"><i class="fas fa-users text-amber-400 ml-2"></i>مدیریت اینباندها</h2>
                <button id="createInboundBtn" class="btn-bee">
                    <i class="fas fa-plus ml-2"></i> ایجاد اینباند جدید
                </button>
            </div>
            
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>نام</th>
                            <th>وضعیت</th>
                            <th>مصرف</th>
                            <th>سقف حجم</th>
                            <th>انقضا</th>
                            <th>عملیات</th>
                        </tr>
                    </thead>
                    <tbody id="inboundsTableBody">
                        <tr><td colspan="6" class="text-center text-gray-500 py-8">در حال بارگذاری...</td></tr>
                    </tbody>
                </table>
            </div>
            
            <input type="hidden" id="editUid">
        </div>
        """,
        
        "traffic": """
        <div class="space-y-6">
            <h2 class="text-2xl font-bold"><i class="fas fa-chart-line text-amber-400 ml-2"></i>آمار ترافیک</h2>
            
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div class="glass-card">
                    <div class="text-gray-400">ترافیک کل</div>
                    <div class="text-2xl font-bold text-amber-400" id="totalTraffic">0 B</div>
                </div>
                <div class="glass-card">
                    <div class="text-gray-400">اتصالات فعال</div>
                    <div class="text-2xl font-bold text-green-400" id="activeConnections">0</div>
                </div>
                <div class="glass-card">
                    <div class="text-gray-400">تعداد اینباندها</div>
                    <div class="text-2xl font-bold text-blue-400" id="totalInbounds">0</div>
                </div>
            </div>
            
            <div class="glass-card">
                <h3 class="text-lg font-bold mb-4">مصرف هر کاربر</h3>
                <div id="trafficList" class="space-y-2"></div>
            </div>
        </div>
        """,
        
        "clean-ip": """
        <div class="space-y-6">
            <h2 class="text-2xl font-bold"><i class="fas fa-network-wired text-amber-400 ml-2"></i>مدیریت آی‌پی تمیز</h2>
            
            <div class="glass-card">
                <h3 class="text-lg font-bold mb-4">افزودن آدرس جدید</h3>
                <form id="addAddressForm" class="flex gap-3 flex-wrap">
                    <input type="text" id="addressInput" class="form-input flex-1 min-w-[200px]" placeholder="مثال: 104.21.0.1 یا example.com" required>
                    <button type="submit" class="btn-bee"><i class="fas fa-plus ml-2"></i>افزودن</button>
                    <button type="button" id="clearAllAddresses" class="bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg px-4 py-2 transition">
                        <i class="fas fa-trash ml-2"></i>حذف همه
                    </button>
                </form>
            </div>
            
            <div class="glass-card">
                <h3 class="text-lg font-bold mb-4">لیست آدرس‌ها</h3>
                <div id="addressesList" class="space-y-2"></div>
            </div>
        </div>
        """,
        
        "settings": """
        <div class="space-y-6">
            <h2 class="text-2xl font-bold"><i class="fas fa-cog text-amber-400 ml-2"></i>تنظیمات ربات تلگرام</h2>
            
            <div class="glass-card max-w-2xl">
                <form id="settingsForm" class="space-y-4">
                    <div>
                        <label class="form-label">توکن ربات تلگرام</label>
                        <input type="text" id="tgToken" class="form-input" placeholder="مثال: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz">
                        <small class="text-gray-500">دریافت از @BotFather</small>
                    </div>
                    <div>
                        <label class="form-label">آیدی عددی ادمین</label>
                        <input type="text" id="tgAdminId" class="form-input" placeholder="مثال: 123456789">
                        <small class="text-gray-500">دریافت از @userinfobot</small>
                    </div>
                    <div>
                        <label class="form-label">زبان ربات</label>
                        <select id="botLang" class="form-input">
                            <option value="fa">فارسی</option>
                            <option value="en">English</option>
                        </select>
                    </div>
                    <button type="submit" class="btn-bee"><i class="fas fa-save ml-2"></i>ذخیره تنظیمات</button>
                </form>
            </div>
        </div>
        """,
        
        "security": """
        <div class="space-y-6">
            <h2 class="text-2xl font-bold"><i class="fas fa-shield-alt text-amber-400 ml-2"></i>امنیت</h2>
            
            <div class="glass-card max-w-2xl">
                <h3 class="text-lg font-bold mb-4">تغییر رمز عبور</h3>
                <form id="changePasswordForm" class="space-y-4">
                    <div>
                        <label class="form-label">رمز فعلی</label>
                        <input type="password" id="currentPassword" class="form-input" required>
                    </div>
                    <div>
                        <label class="form-label">رمز جدید</label>
                        <input type="password" id="newPassword" class="form-input" required minlength="6">
                    </div>
                    <div>
                        <label class="form-label">تکرار رمز جدید</label>
                        <input type="password" id="confirmPassword" class="form-input" required minlength="6">
                    </div>
                    <button type="submit" class="btn-bee"><i class="fas fa-key ml-2"></i>تغییر رمز</button>
                </form>
            </div>
        </div>
        """
    }
    
    return HTMLResponse(pages.get(page, "<div class='text-center text-gray-500 py-8'>صفحه یافت نشد</div>"))

# ============ API Routes ============

@app.post("/api/login")
async def api_login(request: Request):
    """ورود به پنل"""
    data = await request.json()
    password = data.get("password", "")
    
    if verify_password(password, hash_password(ADMIN_PASSWORD)):
        session_id = secrets.token_urlsafe(32)
        SESSIONS[session_id] = "admin"
        
        response = JSONResponse({"success": True})
        response.set_cookie("session_id", session_id, httponly=True, max_age=3600*24*7)
        return response
    
    return JSONResponse({"success": False, "error": "رمز عبور اشتباه است"}, status_code=401)

@app.post("/api/logout")
async def api_logout(request: Request):
    """خروج از پنل"""
    session_id = request.cookies.get("session_id")
    if session_id and session_id in SESSIONS:
        del SESSIONS[session_id]
    
    response = RedirectResponse(url="/login")
    response.delete_cookie("session_id")
    return response

@app.get("/api/me")
async def api_me(request: Request):
    """بررسی وضعیت احراز هویت"""
    if check_auth(request):
        return JSONResponse({"authenticated": True, "user": get_current_user(request)})
    return JSONResponse({"authenticated": False}, status_code=401)

@app.post("/api/change-password")
async def api_change_password(request: Request):
    """تغییر رمز عبور"""
    if not check_auth(request):
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    data = await request.json()
    current = data.get("current_password", "")
    new_pass = data.get("new_password", "")
    
    if not verify_password(current, hash_password(ADMIN_PASSWORD)):
        return JSONResponse({"success": False, "error": "رمز فعلی اشتباه است"})
    
    if len(new_pass) < 6:
        return JSONResponse({"success": False, "error": "رمز جدید باید حداقل ۶ کاراکتر باشد"})
    
    # در محیط واقعی باید رمز را در env یا دیتابیس ذخیره کرد
    # اینجا فقط برای نمایش است
    return JSONResponse({"success": True})

# ============ API اینباندها ============

@app.get("/api/links")
async def api_get_links(request: Request):
    """دریافت لیست تمام اینباندها"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    links_list = []
    for uid, link in LINKS.items():
        link_copy = link.copy()
        link_copy["uid"] = uid
        links_list.append(link_copy)
    
    return JSONResponse(links_list)

@app.get("/api/links/{uid}")
async def api_get_link(request: Request, uid: str):
    """دریافت اطلاعات یک اینباند"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    if uid not in LINKS:
        return JSONResponse({"error": "اینباند یافت نشد"}, status_code=404)
    
    link = LINKS[uid].copy()
    link["uid"] = uid
    return JSONResponse(link)

@app.post("/api/links")
async def api_create_link(request: Request):
    """ایجاد اینباند جدید"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    data = await request.json()
    name = data.get("name", "").strip()
    limit_gb = data.get("limit_gb", 0)
    days = data.get("days", 30)
    
    if not name:
        return JSONResponse({"success": False, "error": "نام کاربر الزامی است"})
    
    # بررسی تکراری نبودن نام
    for link in LINKS.values():
        if link["name"].lower() == name.lower():
            return JSONResponse({"success": False, "error": "این نام قبلاً استفاده شده است"})
    
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
    """به‌روزرسانی اینباند"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    if uid not in LINKS:
        return JSONResponse({"error": "اینباند یافت نشد"}, status_code=404)
    
    data = await request.json()
    link = LINKS[uid]
    
    if "name" in data:
        link["name"] = data["name"].strip()
    if "active" in data:
        link["active"] = bool(data["active"])
    if "limit_gb" in data:
        limit_gb = int(data["limit_gb"])
        link["limit_bytes"] = limit_gb * 1024**3 if limit_gb > 0 else 0
        link["limit_gb"] = limit_gb
    if "days" in data:
        days = int(data["days"])
        if days > 0:
            link["expires_at"] = int(time.time()) + (days * 24 * 3600)
        else:
            link["expires_at"] = None
        link["days"] = days
    if "reset_usage" in data and data["reset_usage"]:
        link["used_bytes"] = 0
    
    save_db()
    return JSONResponse({"success": True})

@app.delete("/api/links/{uid}")
async def api_delete_link(request: Request, uid: str):
    """حذف اینباند"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    if uid not in LINKS:
        return JSONResponse({"error": "اینباند یافت نشد"}, status_code=404)
    
    del LINKS[uid]
    save_db()
    return JSONResponse({"success": True})

# ============ API آی‌پی تمیز ============

@app.get("/api/addresses")
async def api_get_addresses(request: Request):
    """دریافت لیست آدرس‌های تمیز"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    return JSONResponse(CUSTOM_ADDRESSES)

@app.post("/api/addresses")
async def api_add_address(request: Request):
    """افزودن آدرس تمیز"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    data = await request.json()
    address = data.get("address", "").strip()
    
    if not address:
        return JSONResponse({"success": False, "error": "آدرس الزامی است"})
    
    if address in CUSTOM_ADDRESSES:
        return JSONResponse({"success": False, "error": "این آدرس قبلاً اضافه شده است"})
    
    CUSTOM_ADDRESSES.append(address)
    save_db()
    return JSONResponse({"success": True})

@app.delete("/api/addresses/{index}")
async def api_delete_address(request: Request, index: int):
    """حذف یک آدرس تمیز"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    if index < 0 or index >= len(CUSTOM_ADDRESSES):
        return JSONResponse({"error": "آدرس یافت نشد"}, status_code=404)
    
    del CUSTOM_ADDRESSES[index]
    save_db()
    return JSONResponse({"success": True})

@app.delete("/api/addresses")
async def api_delete_all_addresses(request: Request):
    """حذف همه آدرس‌های تمیز"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    CUSTOM_ADDRESSES.clear()
    save_db()
    return JSONResponse({"success": True})

# ============ API تنظیمات ============

@app.get("/api/settings")
async def api_get_settings(request: Request):
    """دریافت تنظیمات"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    return JSONResponse({
        "telegram_token": CONFIG.get("telegram_token", ""),
        "telegram_admin_id": CONFIG.get("telegram_admin_id", ""),
        "bot_lang": CONFIG.get("bot_lang", "fa")
    })

@app.post("/api/settings")
async def api_update_settings(request: Request):
    """به‌روزرسانی تنظیمات"""
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
    
    # راه‌اندازی مجدد ربات (در این نمونه فقط لاگ می‌کنیم)
    logger.info("✅ تنظیمات ربات تلگرام به‌روزرسانی شد")
    
    return JSONResponse({"success": True})

# ============ API آمار ============

@app.get("/api/stats")
async def api_stats(request: Request):
    """دریافت آمار سرور"""
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    total_links = len(LINKS)
    active_links = sum(1 for l in LINKS.values() if l.get("active", False))
    total_traffic = sum(l.get("used_bytes", 0) for l in LINKS.values())
    
    # آمار سیستم
    cpu_percent = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory()
    
    # آپتایم
    with open("/proc/uptime", "r") as f:
        uptime_seconds = int(float(f.read().split()[0]))
    uptime = f"{uptime_seconds // 3600}h {(uptime_seconds % 3600) // 60}m"
    
    # داده‌های ساعتی (نمونه)
    hourly_data = []
    for i in range(12):
        hour = f"{i:02d}:00"
        hourly_data.append({
            "hour": hour,
            "traffic": round(total_traffic * (0.5 + 0.5 * (i / 12)), 0) / (1024**2)
        })
    
    links_list = []
    for uid, link in LINKS.items():
        links_list.append({
            "uid": uid,
            "name": link.get("name", "Unknown"),
            "used_bytes": link.get("used_bytes", 0)
        })
    
    return JSONResponse({
        "total_links": total_links,
        "active_links": active_links,
        "total_traffic": total_traffic,
        "cpu_percent": round(cpu_percent, 1),
        "memory_percent": round(memory.percent, 1),
        "uptime": uptime,
        "active_connections": sum(len(ws) for ws in ACTIVE_WEBSOCKETS.values()),
        "hourly_data": hourly_data,
        "links": links_list
    })

@app.get("/health")
async def health():
    """بررسی سلامت سرور"""
    return JSONResponse({"status": "healthy", "timestamp": int(time.time())})

# ============ WebSocket برای لاگ‌ها ============

@app.websocket("/ws/live-logs")
async def websocket_logs(websocket: WebSocket):
    """استریم لاگ زنده"""
    await websocket.accept()
    try:
        # ارسال لاگ‌های نمونه
        for i in range(5):
            await websocket.send_text(json.dumps({
                "time": datetime.now().isoformat(),
                "level": "info",
                "message": f"لاگ نمونه #{i+1} - اتصال برقرار شد"
            }))
            await asyncio.sleep(0.5)
        
        # حلقه اصلی
        while True:
            await asyncio.sleep(1)
            await websocket.send_text(json.dumps({
                "time": datetime.now().isoformat(),
                "level": "debug",
                "message": f"پینگ زنده - {int(time.time())}"
            }))
    except WebSocketDisconnect:
        logger.info("WebSocket لاگ قطع شد")

# ============ WebSocket پراکسی VLESS ============

@app.websocket("/ws/{uuid}")
async def websocket_proxy(websocket: WebSocket, uuid: str):
    """پروکسی WebSocket برای VLESS"""
    await websocket.accept()
    
    # بررسی وجود اینباند
    if uuid not in LINKS:
        await websocket.close(code=1008, reason="Invalid UUID")
        return
    
    link = LINKS[uuid]
    
    # بررسی فعال بودن
    if not link.get("active", False):
        await websocket.close(code=1008, reason="Inbound is disabled")
        return
    
    # بررسی انقضا
    expires_at = link.get("expires_at")
    if expires_at and int(time.time()) > expires_at:
        await websocket.close(code=1008, reason="Inbound expired")
        return
    
    # بررسی محدودیت حجم
    limit_bytes = link.get("limit_bytes", 0)
    if limit_bytes > 0 and link.get("used_bytes", 0) >= limit_bytes:
        await websocket.close(code=1008, reason="Quota exceeded")
        return
    
    # اضافه کردن به اتصالات فعال
    if uuid not in ACTIVE_WEBSOCKETS:
        ACTIVE_WEBSOCKETS[uuid] = set()
    ACTIVE_WEBSOCKETS[uuid].add(websocket)
    
    try:
        # اینجا باید پروکسی واقعی به سرور هدف پیاده‌سازی شود
        # برای نمونه فقط اکو می‌کنیم
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
            
            # به‌روزرسانی مصرف (نمونه)
            link["used_bytes"] = link.get("used_bytes", 0) + len(data)
            save_db()
            
    except WebSocketDisconnect:
        pass
    finally:
        if uuid in ACTIVE_WEBSOCKETS:
            ACTIVE_WEBSOCKETS[uuid].discard(websocket)
            if not ACTIVE_WEBSOCKETS[uuid]:
                del ACTIVE_WEBSOCKETS[uuid]

# ============ WebSocket پشتیبان برای لاگ‌ها ============

@app.websocket("/ws/live-logs")
async def websocket_live_logs(websocket: WebSocket):
    """ارسال لاگ‌های زنده"""
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(json.dumps({
                "time": datetime.now().isoformat(),
                "level": "info",
                "message": f"سیستم فعال است - {int(time.time())}"
            }))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass

# ============ Subscription ============

@app.get("/sub/{uid}")
async def get_subscription(uid: str):
    """دریافت لینک اشتراک"""
    if uid not in LINKS:
        raise HTTPException(status_code=404, detail="Inbound not found")
    
    domain = get_domain()
    if CUSTOM_ADDRESSES:
        domain = CUSTOM_ADDRESSES[0]
    
    link = LINKS[uid]
    config = generate_vless_config(uid, link["name"], domain)
    
    import base64
    encoded = base64.b64encode(config.encode()).decode()
    return Response(content=encoded, media_type="text/plain")

# ============ اجرای برنامه ============

@app.on_event("startup")
async def startup_event():
    """رویداد استارت برنامه"""
    load_db()
    logger.info("🐝 CBee Panel v2.0.0 راه‌اندازی شد")
    logger.info(f"📊 {len(LINKS)} اینباند بارگذاری شد")
    logger.info(f"🌐 آدرس: http://localhost:{PORT}")

@app.on_event("shutdown")
async def shutdown_event():
    """رویداد توقف برنامه"""
    save_db()
    logger.info("👋 CBee Panel متوقف شد")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
