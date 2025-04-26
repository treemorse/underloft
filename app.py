import os
import csv
import time
import hashlib
from io import BytesIO
from flask import Flask, request, jsonify
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    Dispatcher,
)
from qrcode import QRCode
import cv2
import numpy as np
from PIL import Image
import dotenv


dotenv.load_dotenv()

app = Flask(__name__)
TOKEN = os.getenv("TELEGRAM_TOKEN")
SECURITY_CODE = os.getenv("SECURITY_CODE")
CHANNEL_NAME = os.getenv("CHANNEL_NAME")

USERS_CSV = "users.csv"
REGISTRATIONS_CSV = "registrations.csv"
ATTENDANCE_CSV = "attendance.csv"
STATES_CSV = "states.csv"

for file, headers in [
    (USERS_CSV, ["user_id", "phone", "telegram_tag", "has_ticket", "on_event", "is_admin"]),
    (REGISTRATIONS_CSV, ["timestamp", "user_id", "phone"]),
    (ATTENDANCE_CSV, ["timestamp", "user_id", "phone"]),
    (STATES_CSV, ["user_id", "state"]),
]:
    if not os.path.exists(file):
        with open(file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

def get_user(user_id):
    with open(USERS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["user_id"]) == user_id:
                return row
    return None

def update_user(user_id, updates):
    rows = []
    with open(USERS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["user_id"]) == user_id:
                row.update(updates)
            rows.append(row)
    
    with open(USERS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def set_state(user_id, state):
    states = {}
    with open(STATES_CSV, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            states[int(row[0])] = row[1]
    
    states[user_id] = state
    
    with open(STATES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "state"])
        for uid, st in states.items():
            writer.writerow([uid, st])

def get_state(user_id):
    with open(STATES_CSV, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if int(row[0]) == user_id:
                return row[1]
    return None

def setup_dispatcher(dp):
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.contact, handle_contact))
    dp.add_handler(CallbackQueryHandler(check_subscription, pattern="^check_subscription$"))
    dp.add_handler(CallbackQueryHandler(start_check, pattern="^start_check$"))
    dp.add_handler(CallbackQueryHandler(stop_check, pattern="^stop_check$"))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    return dp

def start(update: Update, context):
    user = update.effective_user
    existing_user = get_user(user.id)
    
    if not existing_user:
        keyboard = [[KeyboardButton("Share Phone", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        update.message.reply_text(
            "Please register with your phone number:",
            reply_markup=reply_markup
        )
        return
    
    if existing_user["is_admin"] == "True":
        keyboard = [[InlineKeyboardButton("Начать проверку", callback_data="start_check")]]
        update.message.reply_text(
            "Поздравляю вы контролер",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        channel_url = f"https://t.me/{CHANNEL_NAME}"
        keyboard = [[InlineKeyboardButton("Проверить", callback_data="check_subscription")]]
        update.message.reply_text(
            f"Подпишись на [канал]({channel_url}), чтобы получить билет",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

def handle_contact(update: Update, context):
    user = update.effective_user
    phone = update.message.contact.phone_number
    
    new_user = {
        "user_id": user.id,
        "phone": phone,
        "telegram_tag": user.username or user.full_name,
        "has_ticket": "False",
        "on_event": "False",
        "is_admin": "False"
    }
    
    with open(USERS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=new_user.keys())
        writer.writerow(new_user)
    
    update.message.reply_text("Регистрация успешна!")
    start(update, context)

def check_subscription(update: Update, context):
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    try:
        member = context.bot.get_chat_member(f"@{CHANNEL_NAME}", user_id)
        if member.status in ["member", "administrator", "creator"]:
            qr = QRCode()
            qr_data = f"{user_id}:{hashlib.sha256(SECURITY_CODE.encode()).hexdigest()}"
            qr.add_data(qr_data)
            qr.make()
            
            img = qr.make_image(fill_color="black", back_color="white")
            bio = BytesIO()
            img.save(bio, "PNG")
            bio.seek(0)
            
            context.bot.send_photo(
                chat_id=user_id,
                photo=bio,
                caption="Это твой билет на тусовку, сохрани, чтобы не потерять"
            )
            
            with open(REGISTRATIONS_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([int(time.time()), user_id, get_user(user_id)["phone"]])
            
            update_user(user_id, {"has_ticket": "True"})
        else:
            query.edit_message_text("Мы тебя не нашли(, попробуй еще раз")
    except Exception as e:
        query.edit_message_text("Мы тебя не нашли(, попробуй еще раз")

async def start_check(update: Update, context):
    query = update.callback_query
    await query.answer()
    set_state(query.from_user.id, "checking")
    keyboard = [[InlineKeyboardButton("Остановить проверку", callback_data="stop_check")]]
    await query.edit_message_text(
        "Режим проверки активирован",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def handle_photo(update: Update, context):
    user_id = update.message.from_user.id
    if get_state(user_id) != "checking":
        return
    
    photo_file = update.message.photo[-1].get_file()
    bio = BytesIO()
    photo_file.download_to_memory(bio)
    bio.seek(0)
    
    try:
        img = Image.open(bio)
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        
        detector = cv2.QRCodeDetector()
        data, points, _ = detector.detectAndDecode(img_cv)
        
        if not data:
            update.message.reply_text("Перефоткай")
            return
        
        if ":" not in data:
            update.message.reply_text("Левый код")
            return
        
        uid, code = data.split(":")
        if code != hashlib.sha256(SECURITY_CODE.encode()).hexdigest():
            update.message.reply_text("Левый код")
            return
        
        with open(ATTENDANCE_CSV, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                if row[1] == uid:
                    update.message.reply_text("Битый код")
                    return
        
        with open(ATTENDANCE_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([int(time.time()), uid, get_user(int(uid))["phone"]])
        
        update.message.reply_text("Этот чист, пропускай")
    except Exception as e:
        update.message.reply_text("Ошибка обработки")

def stop_check(update: Update, context):
    query = update.callback_query
    query.answer()
    
    with open(ATTENDANCE_CSV, "r", encoding="utf-8") as f:
        count = sum(1 for _ in csv.reader(f)) - 1
    
    noun = "билет"
    if 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
        noun = "билета"
    elif count % 10 != 1 or count % 100 == 11:
        noun = "билетов"
    
    keyboard = [[InlineKeyboardButton("Продолжить проверку", callback_data="start_check")]]
    query.edit_message_text(
        f"Ты проверил {count} {noun}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    set_state(query.from_user.id, None)

@app.post("/webhook")
def webhook():
    dp = Dispatcher(None, workers=0)
    dp = setup_dispatcher(dp)
    
    update = Update.de_json(request.get_json(), dp.bot)
    dp.process_update(update)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=1612)