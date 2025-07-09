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
from PIL import Image, ImageDraw, ImageFont, ImageOps
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
    telegram_tag = Column(String, nullable=True)
    has_ticket = Column(Boolean, default=False)
    on_event = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    is_promoter = Column(Boolean, default=False)
    promoter = Column(String, nullable=True)

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
    dp.add_handler(CommandHandler("make_promoter", make_promoter))
    dp.add_handler(MessageHandler(filters.Filters.contact, handle_contact))
    dp.add_handler(CallbackQueryHandler(check_subscription, pattern="^check_subscription$"))
    dp.add_handler(MessageHandler(filters.Filters.photo, handle_photo))
    dp.add_handler(MessageHandler(filters.Filters.text(["Сколько проверенных билетов", "Сколько регистраций"]), show_ticket_count))
    dp.add_handler(MessageHandler(filters.Filters.text(["Мои приглашенные"]), show_invited_stats))
    return dp

def is_admin(user_id):
    user = get_user(user_id)
    return user.is_admin if user else False

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    existing_user = get_user(user.id)

    promoter_tag = None
    if context.args:
        promoter_tag = context.args[0].lstrip('@')
    
    if not existing_user:
        keyboard = [[KeyboardButton("Поделиться Номером", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

        session = Session()
        new_user = User(
            user_id=str(user.id),
            telegram_tag=user.username if user.username else None,
            has_ticket=False,
            on_event=False,
            is_admin=False,
            is_promoter=False,
            promoter=promoter_tag
        )
        session.add(new_user)
        session.commit()
        session.close()

        update.message.reply_text(
            "Регистрация:",
            reply_markup=reply_markup
        )
        return
    
    buttons = []
    if existing_user.is_admin:
        buttons += [[KeyboardButton("Сколько проверенных билетов")], [KeyboardButton("Сколько регистраций")]]

    if existing_user.is_promoter:
        buttons += [[KeyboardButton("Мои приглашенные")]]

    if buttons:
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        update.message.reply_text("Добро пожаловать! Используйте кнопки ниже:", reply_markup=reply_markup)
    else:
        channel_url = f"https://t.me/{CHANNEL_NAME}"
        keyboard = [[InlineKeyboardButton("Проверить", callback_data="check_subscription")]]
        update.message.reply_text(
            f"Подпишись на [канал]({channel_url}), чтобы получить билет",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

def show_invited_stats(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user or not user.is_promoter:
        update.message.reply_text("Ты не промоутер")
        return

    session = Session()
    total_invited = session.query(User).filter_by(promoter=user.telegram_tag).count()
    attended = session.query(User).join(Attendance, User.user_id == Attendance.user_id).filter(
        User.promoter == user.telegram_tag
    ).count()
    session.close()

    update.message.reply_text(f"Ты пригласил: {total_invited}\nНа событии были: {attended}")


def make_promoter(update: Update, context: CallbackContext):
    try:
        sender_id = update.effective_user.id
        sender = get_user(sender_id)
        if not sender or not sender.is_admin:
            update.message.reply_text("У вас нет прав для выполнения этой команды")
            return

        if not context.args or len(context.args) < 1:
            update.message.reply_text("Использование: /make_promoter @username")
            return

        target_tag = context.args[0].lstrip('@')
        session = Session()
        target_user = session.query(User).filter(
            func.lower(User.telegram_tag) == func.lower(target_tag)
        ).first()

        if not target_user:
            update.message.reply_text("Пользователь не найден")
            session.close()
            return

        if target_user.is_promoter:
            update.message.reply_text("Этот пользователь уже промоутер")
            session.close()
            return

        target_user.is_promoter = True
        session.commit()
        update.message.reply_text(f"Пользователь @{target_user.telegram_tag} теперь промоутер")

        try:
            context.bot.send_message(
                chat_id=int(target_user.user_id),
                text="Ты стал промоутером! Используй ссылку:\n"
                     f"https://t.me/{context.bot.username}?start={target_user.telegram_tag}"
            )
        except Exception:
            pass
    except Exception:
        update.message.reply_text("Ошибка выполнения команды")
    finally:
        if 'session' in locals():
            session.close()


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
        update.message.reply_text(f"Пользователь @{target_user.telegram_tag} больше не админ")
        
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
    existing_user = session.query(User).filter_by(user_id=str(user.id)).first()
    if existing_user:
        existing_user.phone = phone
        session.commit()
    else:
        new_user = User(
            user_id=str(user.id),
            phone=phone,
            telegram_tag=user.username if user.username else None,
            has_ticket=False,
            on_event=False,
            is_admin=False,
            is_promoter=False,
            promoter=None
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

            base_qr = qr.make_image(fill_color="black", back_color="white")
            qr_img = base_qr.convert("RGB")
            telegram_tag = query.from_user.username
            ticket_img = generate_ticket_image(telegram_tag, qr_img)
            bio = BytesIO()
            ticket_img.save(bio, "PNG")
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

def generate_ticket_image(telegram_tag: str, qr_img: Image.Image):
    try:
        ticket = Image.open("img/ticket.png")
    except FileNotFoundError:
        ticket = Image.new('RGB', (1080, 1920), (255, 255, 255))
    
    draw = ImageDraw.Draw(ticket)
    
    tag_text = f"@{telegram_tag}" if telegram_tag else ""
    try:
        font = ImageFont.truetype("fonts/tag.ttf", 70)
    except IOError:
        font = ImageFont.load_default()
    
    text_width = draw.textlength(tag_text, font=font)
    draw.text(
        ((1080 - text_width) // 2, 940),
        tag_text,
        fill="white",
        font=font,
        stroke_width=2,
        stroke_fill="black"
    )

    qr_size = 780
    qr_img = qr_img.resize((qr_size, qr_size))
    box = (20, 20, 760, 760)
    qr_img_final = qr_img.crop(box)
    qr_position = ((1130 - qr_size) // 2, 1075)
    
    ticket.paste(qr_img_final, qr_position)
    
    return ticket

@app.route('/health', methods=['GET'])
def health_check():
     return jsonify({"status": "ok"}), 200

@app.post("/webhook")
def webhook():
    dp = Dispatcher(bot=bot, update_queue=None)
    dp = setup_dispatcher(dp)
    
    update = Update.de_json(request.get_json(), bot)
    dp.process_update(update)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=1612)

