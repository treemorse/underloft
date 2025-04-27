import os
import logging
import hashlib
from io import BytesIO
from flask import Flask, request, jsonify
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
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

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
    user_id = Column(String, unique=True)  # Changed to String
    phone = Column(String)
    telegram_tag = Column(String)
    has_ticket = Column(Boolean, default=False)
    on_event = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)

class Registration(Base):
    __tablename__ = 'registrations'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(String)  # Changed to String
    phone = Column(String)

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(String)  # Changed to String
    phone = Column(String)

Base.metadata.create_all(engine)

bot = Bot(token=TOKEN)

def get_user(user_id: int):
    session = Session()
    user = session.query(User).filter_by(user_id=str(user_id)).first()
    session.close()
    return user

def is_admin(user_id: int):
    user = get_user(user_id)
    return user.is_admin if user else False

def setup_dispatcher(dp):
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    dp.add_handler(CallbackQueryHandler(check_subscription, pattern="^check_subscription$"))
    dp.add_handler(MessageHandler(filters.PHOTO & filters.User(user_id=is_admin), handle_photo))
    dp.add_handler(MessageHandler(filters.Text("Сколько билетов было проверено"), show_ticket_count))
    return dp

def start(update: Update, context: CallbackContext):
    try:
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
            keyboard = [[KeyboardButton("Сколько билетов было проверено")]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            update.message.reply_text(
                "Поздравляю ты контролер\n\n"
                "Теперь можешь проверять QR-коды, просто отправляя их фото.\n"
                "Используй кнопку ниже чтобы посмотреть статистику:",
                reply_markup=reply_markup
            )
        else:
            channel_url = f"https://t.me/{CHANNEL_NAME}"
            keyboard = [[InlineKeyboardButton("Проверить", callback_data="check_subscription")]]
            update.message.reply_text(
                f"Подпишись на [канал]({channel_url}), чтобы получить билет",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Start error: {str(e)}")
        update.message.reply_text("Произошла ошибка, попробуйте позже")

def handle_contact(update: Update, context: CallbackContext):
    session = None
    try:
        user = update.effective_user
        phone = update.message.contact.phone_number
        
        if get_user(user.id):
            update.message.reply_text(
                "Вы уже зарегистрированы!",
                reply_markup=ReplyKeyboardRemove()
            )
            return start(update, context)
        
        if not phone.startswith('+') or len(phone) < 8:
            update.message.reply_text(
                "Неверный формат номера телефона",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        session = Session()
        new_user = User(
            user_id=str(user.id),  # Store as string
            phone=phone,
            telegram_tag=user.username or user.full_name,
            has_ticket=False,
            on_event=False,
            is_admin=False
        )
        session.add(new_user)
        session.commit()
        logger.info(f"New user: {user.id}")

        update.message.reply_text(
            "Регистрация успешна!",
            reply_markup=ReplyKeyboardRemove()
        )
        return start(update, context)

    except Exception as e:
        logger.error(f"Registration failed: {str(e)}")
        if session:
            session.rollback()
        update.message.reply_text(
            "Ошибка регистрации. Пожалуйста, попробуйте еще раз",
            reply_markup=ReplyKeyboardRemove()
        )
    finally:
        if session:
            session.close()

def check_subscription(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        
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
            user = session.query(User).filter_by(user_id=str(user_id)).first()
            registration = Registration(
                user_id=str(user_id),
                phone=user.phone
            )
            session.add(registration)
            user.has_ticket = True
            session.commit()
        else:
            query.answer("Мы тебя не нашли(, попробуй еще раз", show_alert=True)
    except Exception as e:
        logger.error(f"Subscription check failed: {str(e)}")
        query.answer("Ошибка проверки подписки", show_alert=True)
    finally:
        if 'session' in locals():
            session.close()

def handle_photo(update: Update, context: CallbackContext):
    session = None
    try:
        user_id = update.message.from_user.id
        if not is_admin(user_id):
            return

        photo_file = bot.get_file(update.message.photo[-1].file_id)
        bio = BytesIO()
        photo_file.download(out=bio)
        bio.seek(0)
        
        img = Image.open(bio)
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        
        detector = cv2.QRCodeDetector()
        data, points, _ = detector.detectAndDecode(img_cv)
        
        if not data:
            return update.message.reply_text("Перефоткай")
        
        if ":" not in data:
            return update.message.reply_text("Левый код")
        
        uid, code = data.split(":")
        if code != hashlib.sha256(SECURITY_CODE.encode()).hexdigest():
            return update.message.reply_text("Левый код")

        session = Session()
        if session.query(Attendance).filter_by(user_id=uid).first():
            return update.message.reply_text("Битый код")
            
        user = session.query(User).filter_by(user_id=uid).first()
        if not user:
            return update.message.reply_text("Левый код")

        session.add(Attendance(user_id=uid, phone=user.phone))
        session.commit()
        update.message.reply_text("Этот чист, пропускай")
        
    except Exception as e:
        logger.error(f"QR processing error: {str(e)}")
        update.message.reply_text("Ошибка обработки QR-кода")
    finally:
        if session:
            session.close()

def show_ticket_count(update: Update, context: CallbackContext):
    try:
        session = Session()
        count = session.query(Attendance).count()
        
        noun = "билет"
        if 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
            noun = "билета"
        elif count % 10 != 1 or count % 100 == 11:
            noun = "билетов"
            
        update.message.reply_text(f"Всего проверено: {count} {noun}")
    except Exception as e:
        logger.error(f"Ticket count error: {str(e)}")
        update.message.reply_text("Ошибка получения статистики")
    finally:
        session.close()

@app.post("/webhook")
def webhook():
    dp = Dispatcher(bot=bot, update_queue=None)
    dp = setup_dispatcher(dp)
    update = Update.de_json(request.get_json(), bot)
    dp.process_update(update)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=1612)