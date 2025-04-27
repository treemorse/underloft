import os
import hashlib
from io import BytesIO
from flask import Flask, request, jsonify
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Bot
)
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    Dispatcher,
    CallbackContext
)
from qrcode import QRCode
import cv2
import numpy as np
from PIL import Image
import dotenv
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

dotenv.load_dotenv()

app = Flask(__name__)
TOKEN = os.getenv("TELEGRAM_TOKEN")
SECURITY_CODE = os.getenv("SECURITY_CODE")
CHANNEL_NAME = os.getenv("CHANNEL_NAME")
DATABASE_URL = os.getenv("DATABASE_URL")

# Database setup
engine = create_engine(DATABASE_URL)
Base = declarative_base()
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    phone = Column(String)
    telegram_tag = Column(String)
    has_ticket = Column(Boolean, default=False)
    on_event = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)

class Registration(Base):
    __tablename__ = 'registrations'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer)
    phone = Column(String)

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer)
    phone = Column(String)

class State(Base):
    __tablename__ = 'states'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    state = Column(String)

# Create tables if they don't exist
Base.metadata.create_all(engine)

bot = Bot(token=TOKEN)

def get_user(user_id):
    session = Session()
    user = session.query(User).filter_by(user_id=user_id).first()
    session.close()
    return user

def update_user(user_id, updates):
    session = Session()
    user = session.query(User).filter_by(user_id=user_id).first()
    if user:
        for key, value in updates.items():
            setattr(user, key, value)
        session.commit()
    session.close()

def set_state(user_id, state):
    session = Session()
    existing = session.query(State).filter_by(user_id=user_id).first()
    if existing:
        existing.state = state
    else:
        new_state = State(user_id=user_id, state=state)
        session.add(new_state)
    session.commit()
    session.close()

def get_state(user_id):
    session = Session()
    state = session.query(State).filter_by(user_id=user_id).first()
    session.close()
    return state.state if state else None

def setup_dispatcher(dp):
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(filters.Filters.contact, handle_contact))
    dp.add_handler(CallbackQueryHandler(check_subscription, pattern="^check_subscription$"))
    dp.add_handler(CallbackQueryHandler(start_check, pattern="^start_check$"))
    dp.add_handler(CallbackQueryHandler(stop_check, pattern="^stop_check$"))
    dp.add_handler(MessageHandler(filters.Filters.photo, handle_photo))
    return dp

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    existing_user = get_user(user.id)
    
    if not existing_user:
        keyboard = [[KeyboardButton("Поделиться Номером", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        update.message.reply_text(
            "Регистрация:",
            reply_markup=reply_markup
        )
        return
    
    if existing_user.is_admin:
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

def handle_contact(update: Update, context: CallbackContext):
    user = update.effective_user
    phone = update.message.contact.phone_number
    
    session = Session()
    new_user = User(
        user_id=user.id,
        phone=phone,
        telegram_tag=user.username or user.full_name,
        has_ticket=False,
        on_event=False,
        is_admin=False
    )
    session.add(new_user)
    session.commit()
    session.close()
    
    update.message.reply_text("Регистрация успешна!")
    start(update, context)

def check_subscription(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    try:
        member = bot.get_chat_member(f"@{CHANNEL_NAME}", user_id)
        if member.status in ["member", "administrator", "creator"]:
            qr = QRCode()
            qr_data = f"{user_id}:{hashlib.sha256(SECURITY_CODE.encode()).hexdigest()}"
            qr.add_data(qr_data)
            qr.make()
            
            img = qr.make_image(fill_color="black", back_color="white")
            bio = BytesIO()
            img.save(bio, "PNG")
            bio.seek(0)
            
            bot.send_photo(
                chat_id=user_id,
                photo=bio,
                caption="Это твой билет на тусовку, сохрани, чтобы не потерять"
            )
            
            session = Session()
            user = session.query(User).filter_by(user_id=user_id).first()
            registration = Registration(
                user_id=user_id,
                phone=user.phone
            )
            session.add(registration)
            user.has_ticket = True
            session.commit()
            session.close()
        else:
            query.answer(
                text="Мы тебя не нашли(, попробуй еще раз", 
                show_alert=True
            )
    except Exception as e:
        query.answer(
            text="Мы тебя не нашли(, попробуй еще раз", 
            show_alert=True
        )

def start_check(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    set_state(query.from_user.id, "checking")
    keyboard = [[InlineKeyboardButton("Остановить проверку", callback_data="stop_check")]]
    query.edit_message_text(
        "Режим проверки активирован",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def handle_photo(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if get_state(user_id) != "checking":
        return
    
    try:
        photo_file = bot.get_file(update.message.photo[-1].file_id)
        bio = BytesIO()
        photo_file.download(out=bio)
        bio.seek(0)
        
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
        
        session = Session()
        exists = session.query(Attendance).filter_by(user_id=uid).first()
        if exists:
            update.message.reply_text("Битый код")
            session.close()
            return
        
        user = session.query(User).filter_by(user_id=uid).first()
        if not user:
            update.message.reply_text("Левый код")
            session.close()
            return
        
        attendance = Attendance(
            user_id=uid,
            phone=user.phone
        )
        session.add(attendance)
        session.commit()
        session.close()
        
        update.message.reply_text("Этот чист, пропускай")
    except Exception as e:
        update.message.reply_text(f"Ошибка обработки: {str(e)}")

def stop_check(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    session = Session()
    count = session.query(Attendance).count()
    session.close()
    
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
    dp = Dispatcher(bot=bot, update_queue=None)
    dp = setup_dispatcher(dp)
    
    update = Update.de_json(request.get_json(), bot)
    dp.process_update(update)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=1612)