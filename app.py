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
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, func
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

dotenv.load_dotenv()

app = Flask(__name__)
TOKEN = os.getenv("TELEGRAM_TOKEN")
SECURITY_CODE = os.getenv("SECURITY_CODE")
CHANNEL_NAME = os.getenv("CHANNEL_NAME")
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
Base = declarative_base()
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True)
    phone = Column(String)
    telegram_tag = Column(String)
    has_ticket = Column(Boolean, default=False)
    on_event = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)

class Registration(Base):
    __tablename__ = 'registrations'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(String)
    phone = Column(String)

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(String)
    phone = Column(String)

Base.metadata.create_all(engine)

bot = Bot(token=TOKEN)

def get_user(user_id):
    session = Session()
    user = session.query(User).filter_by(user_id=str(user_id)).first()
    session.close()
    return user

def update_user(user_id, updates):
    session = Session()
    user = session.query(User).filter_by(user_id=str(user_id)).first()
    if user:
        for key, value in updates.items():
            setattr(user, key, value)
        session.commit()
    session.close()

def setup_dispatcher(dp):
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("promote", promote_user))
    dp.add_handler(CommandHandler("demote", demote_user))
    dp.add_handler(MessageHandler(filters.Filters.contact, handle_contact))
    dp.add_handler(CallbackQueryHandler(check_subscription, pattern="^check_subscription$"))
    dp.add_handler(MessageHandler(filters.Filters.photo, handle_photo))
    dp.add_handler(MessageHandler(filters.Filters.text(["Сколько проверенных билетов", "Сколько регистраций"]), show_ticket_count))
    return dp

def is_admin(user_id):
    user = get_user(user_id)
    return user.is_admin if user else False

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
        keyboard = [[KeyboardButton("Сколько проверенных билетов")], [KeyboardButton("Сколько регистраций")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        update.message.reply_text(
            "Поздравляю ты контролер\n\n"
            "Теперь можешь проверять QR-коды, просто отправляя их фото.\n"
            "Используй кнопки ниже чтобы посмотреть статистику:",
            reply_markup=reply_markup
        )
    else:
        channel_url = f"https://t.me/{CHANNEL_NAME}"
        keyboard = [[ReplyKeyboardRemove()], [InlineKeyboardButton("Проверить", callback_data="check_subscription")]]
        update.message.reply_text(
            f"Подпишись на [канал]({channel_url}), чтобы получить билет",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

def demote_user(update: Update, context: CallbackContext):
    try:
        sender_id = update.effective_user.id
        sender = get_user(sender_id)
        if not sender or not sender.is_admin:
            update.message.reply_text("У вас нет прав для выполнения этой команды")
            return

        if not context.args or len(context.args) < 1:
            update.message.reply_text("Использование: /demote @username")
            return

        target_tag = context.args[0].lstrip('@')
        if not target_tag:
            update.message.reply_text("Укажи телеграм-тег пользователя (например: /demote @username)")
            return

        session = Session()
        target_user = session.query(User).filter(
            func.lower(User.telegram_tag) == func.lower(target_tag)
        ).first()

        if not target_user:
            update.message.reply_text("Пользователь не найден")
            session.close()
            return

        if not target_user.is_admin:
            update.message.reply_text("Этот пользователь не администратор")
            session.close()
            return

        target_user.is_admin = False
        session.commit()
        update.message.reply_text(f"Пользователь @{target_user.telegram_tag} теперь лох")
        
        try:
            context.bot.send_message(
                chat_id=int(target_user.user_id),
                text="Тебя уволили! Отправь /start чтобы обновить функционал."
            )
        except Exception as e:
            pass

    except Exception as e:
        update.message.reply_text("Ошибка выполнения команды")
    finally:
        if 'session' in locals():
            session.close()

def promote_user(update: Update, context: CallbackContext):
    try:
        sender_id = update.effective_user.id
        sender = get_user(sender_id)
        if not sender or not sender.is_admin:
            update.message.reply_text("У вас нет прав для выполнения этой команды")
            return

        if not context.args or len(context.args) < 1:
            update.message.reply_text("Использование: /promote @username")
            return

        target_tag = context.args[0].lstrip('@')
        if not target_tag:
            update.message.reply_text("Укажи телеграм-тег пользователя (например: /promote @username)")
            return

        session = Session()
        target_user = session.query(User).filter(
            func.lower(User.telegram_tag) == func.lower(target_tag)
        ).first()

        if not target_user:
            update.message.reply_text("Пользователь не найден")
            session.close()
            return

        if target_user.is_admin:
            update.message.reply_text("Этот пользователь уже администратор")
            session.close()
            return

        target_user.is_admin = True
        session.commit()
        update.message.reply_text(f"Пользователь @{target_user.telegram_tag} теперь администратор")
        
        try:
            context.bot.send_message(
                chat_id=int(target_user.user_id),
                text="Тебя повысили! Отправь /start чтобы обновить функционал."
            )
        except Exception as e:
            pass

    except Exception as e:
        update.message.reply_text("Ошибка выполнения команды")
    finally:
        if 'session' in locals():
            session.close()

def handle_contact(update: Update, context: CallbackContext):
    user = update.effective_user
    phone = update.message.contact.phone_number
    
    session = Session()
    new_user = User(
        user_id=str(user.id),
        phone=phone,
        telegram_tag=user.username or user.full_name,
        has_ticket=False,
        on_event=False,
        is_admin=False
    )
    session.add(new_user)
    session.commit()
    session.close()
    
    update.message.reply_text(
        "Регистрация успешна!",
        reply_markup=ReplyKeyboardRemove()
    )
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
            user = session.query(User).filter_by(user_id=str(user_id)).first()
            registration = Registration(
                user_id=str(user_id),
                phone=user.phone
            )
            session.add(registration)
            user.has_ticket = True
            session.commit()
            session.close()
        else:
            query.answer(
                "Мы тебя не нашли(, попробуй еще раз", 
                show_alert=True
            )
    except Exception as e:
        query.answer(
            "Мы тебя не нашли(, попробуй еще раз", 
            show_alert=True
        )

def handle_photo(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if not is_admin(user_id):
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

def show_ticket_count(update: Update, context: CallbackContext):
    text = update.message.text
    session = Session()
    if text == "Сколько проверенных билетов":
        count = session.query(Attendance).count()
        noun = "билет"
    else:
        count = session.query(User).count()
        noun = "юзер"
    session.close()
    
    if 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
        noun += "а"
    elif count % 10 != 1 or count % 100 == 11:
        noun += "ов"
    
    update.message.reply_text(f"Всего: {count} {noun}")

@app.post("/webhook")
def webhook():
    dp = Dispatcher(bot=bot, update_queue=None)
    dp = setup_dispatcher(dp)
    
    update = Update.de_json(request.get_json(), bot)
    dp.process_update(update)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=1612)

