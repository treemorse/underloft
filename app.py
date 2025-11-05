import os
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
import dotenv
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime


dotenv.load_dotenv()


app = Flask(__name__)
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_NAME = os.getenv("CHANNEL_NAME")
DATABASE_URL = os.getenv("DATABASE_URL")
WELCOME_IMAGE_PATH = "img/free_shot.png"  # Path to your welcome image


engine = create_engine(DATABASE_URL)
Base = declarative_base()
Session = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True)
    phone = Column(String)
    telegram_tag = Column(String, nullable=True)
    is_registered = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    is_promoter = Column(Boolean, default=False)
    promoter = Column(String, nullable=True)


class Registration(Base):
    __tablename__ = 'registrations'
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
    dp.add_handler(MessageHandler(filters.Filters.text(["Сколько регистраций"]), show_registration_count))
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
    
    # If user exists
    if existing_user:
        # Update promoter if provided and user doesn't have one yet
        if promoter_tag and not existing_user.promoter:
            update_user(user.id, {'promoter': promoter_tag})
        
        buttons = []
        if existing_user.is_admin:
            buttons += [[KeyboardButton("Сколько регистраций")]]

        if existing_user.is_promoter:
            buttons += [[KeyboardButton("Мои приглашенные")]]

        if buttons:
            reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
            update.message.reply_text("Добро пожаловать! Используйте кнопки ниже:", reply_markup=reply_markup)
        else:
            # User already registered
            if existing_user.is_registered:
                update.message.reply_text("Вы уже зарегистрированы! До встречи на тусовке!")
            else:
                # Check subscription
                channel_url = f"https://t.me/{CHANNEL_NAME}"
                keyboard = [[InlineKeyboardButton("Проверить", callback_data="check_subscription")]]
                update.message.reply_text(
                    f"Подпишись на [канал]({channel_url}), чтобы зарегистрироваться",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        return
    
    # For new users
    keyboard = [[KeyboardButton("Поделиться Номером", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    session = Session()
    new_user = User(
        user_id=str(user.id),
        telegram_tag=user.username if user.username else None,
        is_registered=False,
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


def show_invited_stats(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user or not user.is_promoter:
        update.message.reply_text("Ты не промоутер")
        return

    session = Session()
    total_invited = session.query(User).filter_by(promoter=user.telegram_tag).count()
    registered = session.query(User).filter_by(promoter=user.telegram_tag, is_registered=True).count()
    session.close()

    update.message.reply_text(f"Ты пригласил: {total_invited}\nЗарегистрировались: {registered}")


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
        except Exception:
            pass

    except Exception:
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
        except Exception:
            pass

    except Exception:
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
            is_registered=False,
            is_admin=False,
            is_promoter=False,
            promoter=None
        )
        session.add(new_user)
        session.commit()
    session.close()
    
    update.message.reply_text(
        "Номер сохранен! Теперь проверим подписку...",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Check subscription after contact
    channel_url = f"https://t.me/{CHANNEL_NAME}"
    keyboard = [[InlineKeyboardButton("Проверить", callback_data="check_subscription")]]
    update.message.reply_text(
        f"Подпишись на [канал]({channel_url}), чтобы завершить регистрацию",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def check_subscription(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    user = get_user(user_id)
    
    if not user:
        query.edit_message_text("Ошибка: пользователь не найден. Отправьте /start")
        return
    
    try:
        member = bot.get_chat_member(f"@{CHANNEL_NAME}", user_id)
        if member.status in ["member", "administrator", "creator"]:
            # User is subscribed, complete registration
            session = Session()
            db_user = session.query(User).filter_by(user_id=str(user_id)).first()
            
            if db_user and not db_user.is_registered:
                db_user.is_registered = True
                session.commit()
                
                # Add to registrations table
                registration = Registration(
                    user_id=str(user_id),
                    phone=db_user.phone
                )
                session.add(registration)
                session.commit()
            
            session.close()
            
            # Send welcome message
            query.edit_message_text("Отлично! Регистрация завершена 🎉")
            
            # Send welcome image with message
            try:
                with open(WELCOME_IMAGE_PATH, 'rb') as photo:
                    bot.send_photo(
                        chat_id=user_id,
                        photo=photo,
                        caption="Поздравляем! Ты получаешь бесплатный шот на предстоящем мероприятии! 🍹\n\nДо встречи на тусовке! Команда UNDR"
                    )
            except FileNotFoundError:
                bot.send_message(
                    chat_id=user_id,
                    text="Поздравляем! Ты получаешь бесплатный шот на предстоящем мероприятии! 🍹\n\nДо встречи на тусовке! Команда UNDR"
                )
            except Exception as e:
                bot.send_message(
                    chat_id=user_id,
                    text="Поздравляем! Ты получаешь бесплатный шот на предстоящем мероприятии! 🍹\n\nДо встречи на тусовке! Команда UNDR"
                )
        else:
            query.answer(
                "Мы тебя не нашли(, попробуй еще раз", 
                show_alert=True
            )
    except Exception:
        query.answer(
            "Мы тебя не нашли(, попробуй еще раз", 
            show_alert=True
        )


def show_registration_count(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
        
    session = Session()
    count = session.query(Registration).count()
    session.close()
    
    noun = "регистраци"
    if count % 10 == 1 and count % 100 != 11:
        noun += "я"
    elif 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
        noun += "и"
    else:
        noun += "й"
    
    update.message.reply_text(f"Всего: {count} {noun}")


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
