import telebot
import os
import json
import time
import threading
from dotenv import load_dotenv
from telebot import types
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

load_dotenv()

TOKEN = "8601340130:AAHjXHycNv66Hc0xvzNc06HJNRr3l56ytC8"
if not TOKEN:
    raise ValueError("TOKEN не задан!")

bot = telebot.TeleBot(TOKEN)

OWNER_ID = 7925843350

# ---------- DATA ----------
try:
    with open("data.json", "r") as f:
        data = json.load(f)
except:
    data = {
        "credits": {},
        "requests": {},
        "history": {},
        "ratings": {},
        "banned": [],
        "admins": [OWNER_ID],
        "allowed_chat": None
    }

def save():
    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)

ADMINS = data["admins"]

# ---------- CHAT LOCK ----------
def check_chat(message):
    if data["allowed_chat"] is None:
        data["allowed_chat"] = message.chat.id
        save()

    return message.chat.id == data["allowed_chat"]

# ---------- LEVEL ----------
def get_rating(user):
    return data["ratings"].get(user, 10)

def change_rating(user, d):
    r = get_rating(user) + d
    data["ratings"][user] = max(0, min(10, r))

def get_level(user):
    return "VIP" if get_rating(user) >= 8 else "обычный"

def get_limit(user):
    return 25_000_000 if get_level(user) == "VIP" else 5_000_000

# ---------- HISTORY ----------
def add_history(user, action, amount=0, rp=0):
    if user not in data["history"]:
        data["history"][user] = []

    data["history"][user].append({
        "action": action,
        "amount": amount,
        "rp": rp,
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    })

# ---------- PDF ----------
def create_pdf(user, username, history):
    file = f"statement_{user}.pdf"
    c = canvas.Canvas(file, pagesize=A4)

    y = 800
    c.drawString(50, y, "🏦 BANK STATEMENT")
    y -= 30
    c.drawString(50, y, f"User: @{username}")
    y -= 30

    for h in history[-20:]:
        line = f"{h['time']} | {h['action']} | {h['amount']} | {h['rp']}RP"
        c.drawString(50, y, line[:100])
        y -= 20

    c.save()
    return file

# ---------- START ----------
@bot.message_handler(commands=['start'])
def start(message):
    if not check_chat(message):
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📄 Выписка", callback_data="statement"))

    bot.send_message(message.chat.id,
        "🏦 Банк запущен",
        reply_markup=markup
    )

# ---------- CREDIT ----------
@bot.message_handler(commands=['credit'])
def credit(message):
    if not check_chat(message):
        return

    user = str(message.from_user.id)

    if user in data["banned"]:
        bot.reply_to(message, "🚫 Вы заблокированы")
        return

    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Пример: /credit 1000000 7РП")
        return

    amount = int(args[1])
    rp = int(args[2].replace("рп", ""))

    if amount > get_limit(user):
        bot.reply_to(message, f"❌ Лимит {get_limit(user)}")
        return

    data["requests"][user] = {
        "amount": amount,
        "rp": rp,
        "username": message.from_user.username or "no_name",
        "status": "pending"
    }
    save()

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅", callback_data=f"ap_{user}"),
        types.InlineKeyboardButton("❌", callback_data=f"dn_{user}")
    )

    for a in ADMINS:
        bot.send_message(a,
            f"📩 {get_level(user)}\n"
            f"👤 @{message.from_user.username}\n"
            f"💰 {amount}\n"
            f"📊 {rp}RP",
            reply_markup=markup
        )

# ---------- CALLBACK ----------
@bot.callback_query_handler(func=lambda call: True)
def cb(call):
    if call.message.chat.id != data["allowed_chat"]:
        return

    if call.data.startswith("ap_"):
        approve(call.data.split("_")[1], call)

    if call.data.startswith("dn_"):
        deny(call.data.split("_")[1], call)

    if call.data == "statement":
        user = str(call.from_user.id)
        hist = data["history"].get(user, [])
        file = create_pdf(user, call.from_user.username or "no", hist)

        with open(file, "rb") as f:
            bot.send_document(call.message.chat.id, f)

# ---------- APPROVE ----------
def approve(user, call=None):
    r = data["requests"].get(user)
    if not r:
        return

    level = get_level(user)
    percent = 0.05 if level == "VIP" else 0.10

    total = int(r["amount"] * (1 + percent))
    payment = total // r["rp"]

    data["credits"][user] = {
        "total": total,
        "payment": payment,
        "rp_left": r["rp"],
        "last": time.time()
    }

    add_history(user, "APPROVED", r["amount"], r["rp"])
    change_rating(user, +1)

    del data["requests"][user]
    save()

    bot.send_message(user,
        f"🏦 ОДОБРЕНО\n"
        f"⭐ {level}\n"
        f"💰 {total}\n"
        f"📊 {payment}/RP"
    )

# ---------- DENY ----------
def deny(user, call=None):
    r = data["requests"].get(user)
    if not r:
        return

    add_history(user, "DENIED", r["amount"], r["rp"])
    change_rating(user, -1)

    del data["requests"][user]
    save()

    bot.send_message(user, "❌ ОТКАЗ")

# ---------- AUTO SYSTEM ----------
def auto():
    while True:
        time.sleep(60)

        for user, c in list(data["credits"].items()):

            c["total"] -= c["payment"]
            c["rp_left"] -= 1

            add_history(user, "PAY", c["payment"], 0)

            if c["rp_left"] <= 0:
                change_rating(user, -1)
                del data["credits"][user]
                continue

            if c["rp_left"] in [3,2,1]:
                bot.send_message(user,
                    f"⚠️ Осталось RP: {c['rp_left']}\n💰 Долг: {c['total']}"
                )

        save()

threading.Thread(target=auto, daemon=True).start()

# ---------- MY CREDIT ----------
@bot.message_handler(commands=['mycredit'])
def mycredit(message):
    if not check_chat(message):
        return

    user = str(message.from_user.id)
    c = data["credits"].get(user)

    if not c:
        bot.reply_to(message, "Нет кредита")
        return

    bot.reply_to(message,
        f"💰 {c['total']}\n"
        f"📊 {c['payment']}\n"
        f"⭐ {get_level(user)}\n"
        f"⭐ {get_rating(user)}/10"
    )

# ---------- PAY ----------
@bot.message_handler(commands=['pay'])
def pay(message):
    if not check_chat(message):
        return

    user = str(message.from_user.id)
    args = message.text.split()

    if user not in data["credits"]:
        return

    amount = int(args[1])
    data["credits"][user]["total"] -= amount
    save()

# ---------- ADMIN LIST ----------
@bot.message_handler(commands=['credits'])
def allc(message):
    if message.from_user.id not in ADMINS:
        return

    markup = types.InlineKeyboardMarkup()

    text = "🏦 CREDITS:\n"

    for u, c in data["credits"].items():
        markup.add(types.InlineKeyboardButton(
            f"🗑 {u}",
            callback_data=f"del_{u}"
        ))
        text += f"{u} | {c['total']}\n"

    bot.send_message(message.chat.id, text, reply_markup=markup)

# ---------- DELETE CREDIT ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith("del_"))
def delc(call):
    if call.from_user.id not in ADMINS:
        return

    u = call.data.split("_")[1]

    if u in data["credits"]:
        del data["credits"][u]
        save()

    bot.send_message(u, "❌ Кредит удалён")
    bot.answer_callback_query(call.id, "Удалено")

# ---------- BAN ----------
@bot.message_handler(commands=['ban'])
def ban(message):
    if message.from_user.id not in ADMINS:
        return

    u = message.text.split()[1]
    data["banned"].append(u)
    save()

bot.polling()
