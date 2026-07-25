import asyncio
import logging
import os
from typing import Optional

try:
    import telebot
    from telebot.async_telebot import AsyncTeleBot
    TELEBOT_AVAILABLE = True
except ImportError:
    TELEBOT_AVAILABLE = False

from storage.database import get_users, get_inbounds, load_state
from core.protocols import generate_share_link

logger = logging.getLogger("CBee-Telegram")

class TelegramBot:
    def __init__(self):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.admin_id = os.environ.get("TELEGRAM_ADMIN_ID", "")
        self.bot: Optional[AsyncTeleBot] = None
        self.running = False
    
    async def start(self):
        if not self.token or not TELEBOT_AVAILABLE:
            logger.warning("Telegram bot not configured")
            return
        self.bot = AsyncTeleBot(self.token)
        self.running = True
        
        @self.bot.message_handler(commands=['start'])
        async def send_welcome(message):
            await self.bot.reply_to(
                message,
                "🐝 **CBee Panel Bot**\n\n"
                "سلام! به ربات مدیریت پنل خوش آمدید.\n\n"
                "📋 **دستورات موجود:**\n"
                "/status - وضعیت پنل\n"
                "/users - لیست کاربران\n"
                "/inbounds - لیست اینباندها\n"
                "/sub - دریافت لینک اشتراک\n"
                "/help - راهنما\n\n"
                "📢 **کانال:** @CbeeNet"
            )
        
        @self.bot.message_handler(commands=['status'])
        async def send_status(message):
            if str(message.chat.id) != self.admin_id:
                await self.bot.reply_to(message, "⛔ دسترسی غیرمجاز")
                return
            state = await load_state()
            users = state.get("users", [])
            inbounds = state.get("inbounds", [])
            text = (
                f"📊 **وضعیت پنل CBee**\n\n"
                f"👥 **کاربران:** {len(users)}\n"
                f"🔗 **اینباندها:** {len(inbounds)}\n"
                f"📡 **پروتکل‌ها:** {len(set(i.get('protocol') for i in inbounds))}\n"
                f"📢 **کانال:** @CbeeNet"
            )
            await self.bot.reply_to(message, text)
        
        @self.bot.message_handler(commands=['users'])
        async def list_users(message):
            if str(message.chat.id) != self.admin_id:
                await self.bot.reply_to(message, "⛔ دسترسی غیرمجاز")
                return
            users = await get_users()
            if not users:
                await self.bot.reply_to(message, "❌ کاربری وجود ندارد")
                return
            text = "👥 **لیست کاربران:**\n\n"
            for u in users:
                text += f"• {u['username']} (ID: {u['id'][:8]})\n"
            text += f"\n📢 **کانال:** @CbeeNet"
            await self.bot.reply_to(message, text)
        
        @self.bot.message_handler(commands=['inbounds'])
        async def list_inbounds(message):
            if str(message.chat.id) != self.admin_id:
                await self.bot.reply_to(message, "⛔ دسترسی غیرمجاز")
                return
            inbounds = await get_inbounds()
            if not inbounds:
                await self.bot.reply_to(message, "❌ اینباندی وجود ندارد")
                return
            text = "🔗 **لیست اینباندها:**\n\n"
            for i in inbounds:
                status = "✅" if i.get("enabled", True) else "❌"
                text += f"{status} {i['protocol']}:{i['port']} (ID: {i['id'][:8]})\n"
            text += f"\n📢 **کانال:** @CbeeNet"
            await self.bot.reply_to(message, text)
        
        @self.bot.message_handler(commands=['sub'])
        async def get_sub_link(message):
            if str(message.chat.id) != self.admin_id:
                await self.bot.reply_to(message, "⛔ دسترسی غیرمجاز")
                return
            inbounds = await get_inbounds()
            active = [i for i in inbounds if i.get("enabled", True)]
            if not active:
                await self.bot.reply_to(message, "❌ اینباند فعالی وجود ندارد")
                return
            inbound = active[0]
            host = inbound.get("host", "example.com")
            port = inbound.get("port", 443)
            uuid_str = inbound.get("uuid", "")
            path = inbound.get("path", "/")
            protocol = inbound.get("protocol", "vless")
            tls = inbound.get("tls", False)
            link = generate_share_link(protocol, {}, host, port, uuid_str, path, tls)
            await self.bot.reply_to(
                message,
                f"🔗 **لینک اشتراک:**\n`{link}`\n\n📢 **کانال:** @CbeeNet"
            )
        
        @self.bot.message_handler(commands=['help'])
        async def send_help(message):
            await self.bot.reply_to(
                message,
                "📖 **راهنمای ربات CBee Panel**\n\n"
                "/start - شروع\n"
                "/status - وضعیت پنل\n"
                "/users - لیست کاربران\n"
                "/inbounds - لیست اینباندها\n"
                "/sub - دریافت لینک اشتراک\n"
                "/help - این پیام\n\n"
                "📢 **کانال:** @CbeeNet"
            )
        
        try:
            await self.bot.infinity_polling()
        except Exception as e:
            logger.error(f"Telegram bot error: {e}")
    
    async def stop(self):
        self.running = False
        if self.bot:
            await self.bot.close_session()

telegram_bot = TelegramBot()