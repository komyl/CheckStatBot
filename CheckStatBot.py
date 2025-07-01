import logging
import json
import os
from datetime import datetime
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes, ChatMemberHandler
from telegram.constants import ParseMode
import asyncio

# Constants
BOT_TOKEN = "Your-Token"  # your telegram bot api token
ADMIN_ID = "Your-User-Id" # your user id
CHANNEL_USERNAME = "@Your-Channel" # your channel id
CHANNEL_ID = -"Your-Channel-iD" # your channel id number

# Conversation states
(WAITING_PHONE, WAITING_NAME, WAITING_CARD, WAITING_SHEBA,
 WAITING_BANK, EDIT_MENU, EDIT_PHONE, EDIT_NAME, EDIT_CARD,
 EDIT_SHEBA, EDIT_BANK, SUPPORT_MESSAGE, ADMIN_BROADCAST,
 ADMIN_ADD_LINK, ADMIN_REMOVE_LINK, ADMIN_ADD_ADMIN,
 ADMIN_REMOVE_ADMIN,
 ADMIN_SUPPORT_REPLY_STATE,
 ADMIN_AWAITING_SETTLEMENT_RECEIPT_STATE
 ) = range(19)

# Database directory
DB_DIR = "bot_database"
DB_FILE = os.path.join(DB_DIR, "main_data.json")

# Initialize database
def init_db():
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)

    if not os.path.exists(DB_FILE):
        db = {
            "users": {}, "groups": {}, "unique_members": {}, "codes": {},
            "settlements": {}, "support_tickets": {}, "admins": [ADMIN_ID],
            "promotional_links": [f"https://t.me/{CHANNEL_USERNAME[1:]}"],
            "next_code_id": 1, "next_ticket_id": 1
        }
        save_db(db)
        # Add initial admin user and codes if DB was just created
        db = load_db() # Reload to work with the saved empty structure
        admin_user_id_str = str(ADMIN_ID)
        if admin_user_id_str not in db["users"]:
            db["users"][admin_user_id_str] = {
                "user_id": ADMIN_ID, "registered": True, "points": 0,
                "codes": [], "name": "Admin User",
                "registration_date": datetime.now().isoformat()
            }

        current_admin_points = db["users"][admin_user_id_str].get("points", 0)
        points_to_add_for_codes = 0
        for i in range(1, 21): # Add 20 sample codes for admin
            code_id = db["next_code_id"]
            db["next_code_id"] += 1
            db["codes"][str(code_id)] = {
                "user_id": ADMIN_ID, "date": datetime.now().isoformat(), "settled": False
            }
            db["users"][admin_user_id_str].setdefault("codes", []).append(code_id)
            points_to_add_for_codes += 100
        db["users"][admin_user_id_str]["points"] = current_admin_points + points_to_add_for_codes
        save_db(db)
        logging.info(f"Initialized new database with admin user and 20 test codes ({points_to_add_for_codes} points).")
    return load_db()


def load_db():
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.warning(f"Database file {DB_FILE} not found. Initializing a new one.")
        if not os.path.exists(DB_DIR): os.makedirs(DB_DIR)
        empty_db = {
            "users": {}, "groups": {}, "unique_members": {}, "codes": {},
            "settlements": {}, "support_tickets": {}, "admins": [ADMIN_ID],
            "promotional_links": [f"https://t.me/{CHANNEL_USERNAME[1:]}"],
            "next_code_id": 1, "next_ticket_id": 1
        }
        save_db(empty_db) # Save the minimal structure first
        return init_db() # Then call init_db to populate admin if it's truly new
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {DB_FILE}. File might be corrupted. Creating a backup and starting fresh.")
        backup_file = f"{DB_FILE}_corrupted_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
        if os.path.exists(DB_FILE): os.rename(DB_FILE, backup_file)
        logging.info(f"Corrupted DB backed up to {backup_file}")
        if not os.path.exists(DB_DIR): os.makedirs(DB_DIR)
        return init_db() # Re-initialize

def save_db(db_content):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(db_content, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed to save database to {DB_FILE}: {e}", exc_info=True)

# Keyboard layouts
def get_main_keyboard():
    keyboard = [
        ["امتیازات من 🏆", "کد های من 🎫"],
        ["تسویه حساب 💰", "ارتباط با پشتیبانی 📞"],
        ["ویرایش اطلاعات ✏️", "راهنما ❓"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    keyboard = [
        ["آمار کلی 📊", "خروجی اکسل اعضا 📄"],
        ["مدیریت درخواست های تسویه 💳", "مدیریت درخواست های پشتیبانی 📮"],
        ["مدیریت لینک های تبلیغاتی 🔗", "ارسال پیام همگانی 📢"],
        ["مدیریت ادمین ها 👨‍💼", "برگشت به منو کاربران 🔙"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_edit_keyboard():
    keyboard = [
        ["ویرایش شماره تماس 📱", "ویرایش نام و نام خانوادگی 👤"],
        ["ویرایش شماره کارت 💳", "ویرایش شماره شبا 🏦"],
        ["ویرایش نام بانک 🏛️", "بازگشت به منو اصلی 🔙"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- Group Management ---
async def unified_bot_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.my_chat_member:
        return

    chat = update.my_chat_member.chat
    if chat.type not in ['group', 'supergroup']:
        return

    group_id_str = str(chat.id)
    group_title = chat.title if chat.title else f"گروه بدون عنوان ({group_id_str})" # Handle missing title
    new_status = update.my_chat_member.new_chat_member.status
    old_chat_member_obj = update.my_chat_member.old_chat_member
    old_status = old_chat_member_obj.status if old_chat_member_obj else "absent"

    db = load_db()
    admins_to_notify = db.get("admins", [])

    if "groups" not in db or not isinstance(db.get("groups"), dict):
        db["groups"] = {}

    group_existed_in_db = group_id_str in db["groups"]
    # Preserve members if group already existed, otherwise initialize empty
    existing_members = db.get("groups", {}).get(group_id_str, {}).get("members", [])

    if new_status in ['administrator', 'creator']:
        if not group_existed_in_db or db["groups"].get(group_id_str, {}).get("title") != group_title:
            db["groups"][group_id_str] = {"title": group_title, "members": existing_members}
            save_db(db)
            logging.info(f"unified_bot_status_handler: Bot is now admin in '{group_title}' ({group_id_str}). Title updated/Group added to db.")
        else:
            if "members" not in db["groups"][group_id_str]:
                 db["groups"][group_id_str]["members"] = existing_members
                 save_db(db)
            logging.info(f"unified_bot_status_handler: Bot confirmed as admin in '{group_title}' ({group_id_str}). No changes to title needed.")

        message_to_admins = f"✅ ربات در گروه زیر ادمین شد (یا وضعیت ادمین بودن آن تایید شد):\nنام: {group_title}\nآیدی: {group_id_str}"
        if old_status in ['member', 'absent', 'left', 'kicked', None] or not group_existed_in_db:
             for admin_id_val in admins_to_notify:
                try:
                    await context.bot.send_message(admin_id_val, message_to_admins)
                except Exception as e:
                    logging.warning(f"unified_bot_status_handler: Failed to notify admin {admin_id_val} about admin promotion: {e}")

    elif new_status == 'member':
        if group_existed_in_db:
            del db["groups"][group_id_str]
            save_db(db)
            logging.info(f"unified_bot_status_handler: Bot is now a non-admin member in '{group_title}' ({group_id_str}). Removed from admin-groups db.")
            message_to_admins = f"⚠️ ربات در گروه زیر دیگر ادمین نیست (یا به عضو عادی تنزل یافته):\nنام: {group_title}"
            for admin_id_val in admins_to_notify:
                try:
                    await context.bot.send_message(admin_id_val, message_to_admins)
                except Exception as e:
                    logging.warning(f"unified_bot_status_handler: Failed to notify admin {admin_id_val} about demotion: {e}")

        if old_status in ['absent', 'left', 'kicked', None]:
            logging.info(f"unified_bot_status_handler: Bot added as a member to group '{group_title}' ({group_id_str}).")
            try:
                await context.bot.send_message(
                    int(group_id_str),
                    "ربات با موفقیت به گروه اضافه شد. برای فعال شدن قابلیت امتیازدهی و سایر امکانات، لطفاً ربات را ادمین کنید."
                )
            except Exception as e:
                logging.warning(f"unified_bot_status_handler: Could not send 'promote me' message to {group_title}: {e}")

    elif new_status in ['left', 'kicked']:
        if group_existed_in_db:
            del db["groups"][group_id_str]
            save_db(db)
            logging.info(f"unified_bot_status_handler: Bot was removed/left from '{group_title}' ({group_id_str}). Removed from db.")
            message_to_admins = f"❌ ربات از گروه زیر حذف شد یا اخراج گردید:\nنام: {group_title}"
            for admin_id_val in admins_to_notify:
                try:
                    await context.bot.send_message(admin_id_val, message_to_admins)
                except Exception as e:
                    logging.warning(f"unified_bot_status_handler: Failed to notify admin {admin_id_val} about removal: {e}")

async def update_groups_list_simplified(context_or_bot):
    db_snapshot = load_db()
    
    bot_instance = context_or_bot
    logging.info(f"update_groups_list_simplified: Using bot ID {bot_instance.id}.")

    if "groups" not in db_snapshot or not isinstance(db_snapshot.get("groups"), dict):
        logging.warning("update_groups_list_simplified: 'groups' key missing or not a dict, initializing.")
        db_snapshot["groups"] = {}
        save_db(db_snapshot)

    current_groups_in_db = db_snapshot["groups"]
    if not current_groups_in_db:
        logging.info("update_groups_list_simplified: No groups found in DB to process.")
        return 0

    titles_changed = False
    groups_processed_count = 0

    for group_id_str in list(current_groups_in_db.keys()):
        groups_processed_count += 1
        original_group_data = current_groups_in_db.get(group_id_str)
        if not original_group_data:
            logging.error(f"update_groups_list_simplified: Group ID {group_id_str} was in keys but data is missing. Skipping.")
            continue

        current_title_in_db = original_group_data.get("title", group_id_str)
        new_title = current_title_in_db

        try:
            group_id_int = int(group_id_str)
            chat_info = await bot_instance.get_chat(group_id_int) 
            new_title = chat_info.title if chat_info.title else f"گروه بدون عنوان ({group_id_str})"

            if current_title_in_db != new_title:
                logging.info(f"update_groups_list_simplified: Title for group {group_id_str} changed from '{current_title_in_db}' to '{new_title}'. Updating.")
                current_groups_in_db[group_id_str]["title"] = new_title
                titles_changed = True
            else:
                logging.info(f"update_groups_list_simplified: Title for group '{new_title}' ({group_id_str}) is current.")

        except Exception as e:
            logging.error(f"update_groups_list_simplified: Error processing group '{current_title_in_db}' ({group_id_str}): {e}. Group will remain in DB as per new logic.", exc_info=False)

    if titles_changed:
        logging.info("update_groups_list_simplified: Saving DB due to title changes.")
        save_db(db_snapshot)
    else:
        logging.info("update_groups_list_simplified: No title changes detected, DB not saved by this function.")

    final_group_count = len(current_groups_in_db)
    logging.info(f"update_groups_list_simplified: Finished. {groups_processed_count} groups processed. {final_group_count} groups currently in DB.")
    return final_group_count


async def post_startup_group_check(application: Application):
    try:
        await asyncio.sleep(10)
        logging.info("Running initial group data update after startup...")
        active_groups_count = await update_groups_list_simplified(application.bot)
        logging.info(f"Initial group data update complete: {active_groups_count} groups in DB processed.")
    except Exception as e:
        logging.error(f"Error during post_startup_group_check: {e}", exc_info=True)

async def periodic_group_check(context: ContextTypes.DEFAULT_TYPE):
    try:
        logging.info("Running periodic group data update...")
        group_count = await update_groups_list_simplified(context.bot)
        logging.info(f"Periodic group data update: {group_count} groups in DB processed.")
    except Exception as e:
        logging.error(f"Error in periodic group check: {e}", exc_info=True)

# --- End of Group Management ---

async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ['left', 'kicked']
    except Exception as e:
        logging.error(f"Error checking channel membership for user {user_id} in channel {CHANNEL_ID}: {e}")
        return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return

    user_id = update.effective_user.id
    db = load_db()

    if not await check_channel_membership(update, context):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("✅ عضو شدم", callback_data="check_membership")]
        ])
        await update.message.reply_text(
            f"🔔 برای استفاده از ربات، ابتدا باید در کانال زیر عضو شوید:\n{CHANNEL_USERNAME}",
            reply_markup=keyboard
        )
        return

    user_id_str = str(user_id)
    if user_id_str in db.get("users", {}) and db["users"][user_id_str].get("registered", False):
        await update.message.reply_text(
            "خوش آمدید! 🌟\nاز منوی زیر گزینه مورد نظر خود را انتخاب کنید:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("ارسال شماره تماس 📱", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )

    guide_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("راهنمای ارسال شماره", callback_data="phone_guide")],
        [InlineKeyboardButton("ارسال دستی شماره", callback_data="manual_phone_entry")]
    ])

    await update.message.reply_text(
        "برای ثبت نام، لطفا شماره تماس خود را با استفاده از دکمه زیر ارسال کنید:",
        reply_markup=keyboard
    )
    await update.message.reply_text(
        "اگر دکمه 'ارسال شماره تماس' را مشاهده نمی‌کنید یا با مشکل مواجه شدید، می‌توانید از گزینه‌های زیر استفاده کنید یا شماره خود را به صورت دستی تایپ و ارسال کنید (مثال: +989123456789):",
        reply_markup=guide_button
    )
    return WAITING_PHONE

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    user_id_str = str(user_id)

    phone_number = ""
    if update.message.contact:
        phone_number = update.message.contact.phone_number
        if not phone_number.startswith('+'):
            # Assuming non-plus numbers from request_contact are local to IR
            if phone_number.startswith('0'):
                 phone_number = '+98' + phone_number[1:]
            elif len(phone_number) == 10 and phone_number.startswith('9'): # e.g. 9123456789
                 phone_number = '+98' + phone_number
            else: # If it's just numbers without 0, assume it's local part of +98
                 phone_number = '+98' + phone_number
    else:
        phone_number = update.message.text.strip()
        if phone_number.startswith('00'):
            phone_number = '+' + phone_number[2:]
        elif phone_number.startswith('09') and not phone_number.startswith('+'): # e.g. 09123456789
            phone_number = '+98' + phone_number[1:]
        elif phone_number.isdigit() and len(phone_number) == 10 and phone_number.startswith('9'): # e.g. 9123456789 (without leading 0)
            phone_number = '+98' + phone_number

        is_valid_phone, _ = validate_phone(phone_number)
        if not is_valid_phone:
            await update.message.reply_text("❌ شماره تماس معتبر نیست. لطفا با کد کشور (مثال: +989123456789) یا فرمت صحیح ارسال کنید:")
            # Determine if this is registration or edit to return to correct state
            if context.user_data.get('current_edit_field') == 'phone':
                return EDIT_PHONE
            return WAITING_PHONE


    if user_id_str not in db["users"]: db["users"][user_id_str] = {}
    db["users"][user_id_str]["phone"] = phone_number
    db["users"][user_id_str]["user_id"] = user_id
    db["users"][user_id_str]["username"] = update.effective_user.username or "ندارد"
    save_db(db)

    # Check if this is part of edit flow or registration flow
    if context.user_data.get('current_edit_field') == 'phone':
        await update.message.reply_text("✅ شماره تماس شما با موفقیت بروزرسانی شد.", reply_markup=get_edit_keyboard())
        context.user_data.pop('current_edit_field', None)
        return EDIT_MENU # Return to edit menu
    else: # Registration flow
        await update.message.reply_text(
            "✅ شماره تماس ثبت شد.\n\nلطفا نام و نام خانوادگی خود را ارسال کنید:",
            reply_markup=ReplyKeyboardMarkup([["انصراف از ثبت نام ❌"]], resize_keyboard=True, one_time_keyboard=True)
        )
        return WAITING_NAME


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id_str = str(update.effective_user.id)
    db = load_db()

    if update.message.text == "انصراف از ثبت نام ❌":
        if user_id_str in db["users"] and not db["users"][user_id_str].get("registered"):
            db["users"].pop(user_id_str, None)
            save_db(db)
            await update.message.reply_text("❌ ثبت نام لغو شد. برای شروع مجدد /start را بزنید.", reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        else:
            await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    name = update.message.text.strip()
    if not name or len(name) < 3 or any(char.isdigit() for char in name):
        await update.message.reply_text("❌ نام و نام خانوادگی معتبر نیست (باید حداقل 3 حرف و بدون عدد باشد). لطفا دوباره ارسال کنید:")
        return WAITING_NAME

    db["users"][user_id_str]["name"] = name
    save_db(db)
    await update.message.reply_text(
        "✅ نام ثبت شد.\n\nلطفا شماره کارت خود را ارسال کنید (16 رقم بدون فاصله یا خط تیره):"
    )
    return WAITING_CARD

async def handle_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id_str = str(update.effective_user.id)
    db = load_db()

    if update.message.text == "انصراف از ثبت نام ❌":
        if user_id_str in db["users"] and not db["users"][user_id_str].get("registered"):
            db["users"].pop(user_id_str, None); save_db(db)
            await update.message.reply_text("❌ ثبت نام لغو شد. برای شروع مجدد /start را بزنید.", reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        else:
            await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    card = update.message.text.replace(" ", "").replace("-", "")
    if not card.isdigit() or len(card) != 16:
        await update.message.reply_text("❌ شماره کارت باید 16 رقم و فقط شامل اعداد باشد. لطفا دوباره امتحان کنید:")
        return WAITING_CARD

    db["users"][user_id_str]["card"] = card
    save_db(db)
    await update.message.reply_text(
        "✅ شماره کارت ثبت شد.\n\nلطفا شماره شبا خود را ارسال کنید (24 رقم عددی، بدون IR اولیه):"
    )
    return WAITING_SHEBA

async def handle_sheba(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id_str = str(update.effective_user.id)
    db = load_db()

    if update.message.text == "انصراف از ثبت نام ❌":
        if user_id_str in db["users"] and not db["users"][user_id_str].get("registered"):
            db["users"].pop(user_id_str, None); save_db(db)
            await update.message.reply_text("❌ ثبت نام لغو شد. برای شروع مجدد /start را بزنید.", reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        else:
            await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    sheba = update.message.text.replace(" ", "").upper().replace("IR", "")
    if not sheba.isdigit() or len(sheba) != 24:
        await update.message.reply_text("❌ شماره شبا باید 24 رقم عددی باشد (بدون IR). لطفا دوباره امتحان کنید:")
        return WAITING_SHEBA

    db["users"][user_id_str]["sheba"] = sheba
    save_db(db)
    await update.message.reply_text(
        "✅ شماره شبا ثبت شد.\n\nلطفا نام بانک خود را ارسال کنید (مثال: ملی، ملت، پاسارگاد):"
    )
    return WAITING_BANK

async def handle_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id_str = str(update.effective_user.id)
    db = load_db()

    if update.message.text == "انصراف از ثبت نام ❌":
        if user_id_str in db["users"] and not db["users"][user_id_str].get("registered"):
            db["users"].pop(user_id_str, None); save_db(db)
            await update.message.reply_text("❌ ثبت نام لغو شد. برای شروع مجدد /start را بزنید.", reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
        else:
            await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    bank = update.message.text.strip()
    if not bank or len(bank) < 2 or any(char.isdigit() for char in bank):
        await update.message.reply_text("❌ نام بانک معتبر نیست (باید حداقل 2 حرف و بدون عدد باشد). لطفا دوباره ارسال کنید:")
        return WAITING_BANK

    db["users"][user_id_str]["bank"] = bank
    db["users"][user_id_str]["registered"] = True
    db["users"][user_id_str].setdefault("points", 0)
    db["users"][user_id_str].setdefault("codes", [])
    db["users"][user_id_str].setdefault("registration_date", datetime.now().isoformat())
    save_db(db)

    await update.message.reply_text(
        """
✅ ثبت نام شما با موفقیت تکمیل شد!
اکنون می‌توانید با اضافه کردن مخاطبین خود به گروه
@Your_Channel_iD
به راحتی در منزل کسب درآمد کنید.
برای اطلاعات بیشتر حتماً بخش راهنمای ربات را مطالعه کنید.

⚠️ **مهم:** اطلاعات وارد شده، به خصوص شماره کارت و شبا، باید متعلق به شخص شما باشد. در صورت مغایرت، تسویه حساب انجام نخواهد شد.

اکنون می‌توانید از امکانات ربات استفاده کنید:
""",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

# --- Menu Handlers ---
async def show_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    user_id_str = str(update.effective_user.id)
    db = load_db()
    user_data = db.get("users", {}).get(user_id_str)
    if not user_data or not user_data.get("registered"):
        await update.message.reply_text("❌ شما هنوز ثبت نام نکرده‌اید! لطفا ابتدا /start را بزنید.")
        return

    points = user_data.get("points", 0)
    codes_count = len(user_data.get("codes", []))
    text = f"🏆 امتیازات فعلی شما: {points} امتیاز\n"
    text += f"🎫 تعداد کدهای جایزه دریافتی شما: {codes_count} عدد\n\n"
    text += "💡 راهنما: به ازای هر عضوی که توسط شما به گروه‌های تحت پوشش ربات اضافه شود (و آن عضو برای اولین بار وارد سیستم شود)، ۱ امتیاز دریافت می‌کنید. هر ۱۰۰ امتیاز به طور خودکار به یک کد جایزه تبدیل می‌شود."
    await update.message.reply_text(text)

async def show_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    user_id_str = str(update.effective_user.id)
    db = load_db()
    user_data = db.get("users", {}).get(user_id_str)
    if not user_data or not user_data.get("registered"):
        await update.message.reply_text("❌ شما هنوز ثبت نام نکرده‌اید! لطفا ابتدا /start را بزنید.")
        return

    user_codes_ids = user_data.get("codes", [])
    if not user_codes_ids:
        await update.message.reply_text("❌ شما هنوز هیچ کد جایزه‌ای دریافت نکرده‌اید.")
        return

    text = "🎫 لیست کدهای جایزه شما:\n\n"
    all_codes_db = db.get("codes", {})
    for code_id in user_codes_ids:
        code_info = all_codes_db.get(str(code_id))
        if code_info:
            status_emoji = "✅" if code_info.get("settled") else "⏳"
            status_text = "تسویه شده" if code_info.get("settled") else "در انتظار تسویه"
            try:
                date_obj = datetime.fromisoformat(code_info.get("date", ""))
                date_formatted = date_obj.strftime('%Y/%m/%d')
            except:
                date_formatted = "تاریخ نامشخص"
            text += f"کد: `{code_id}` - وضعیت: {status_emoji} {status_text} - تاریخ دریافت: {date_formatted}\n"
        else:
            text += f"کد: `{code_id}` - اطلاعات این کد یافت نشد (ممکن است خطایی رخ داده باشد).\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def settlement_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    user_id_str = str(update.effective_user.id)
    db = load_db()
    user_data = db.get("users", {}).get(user_id_str)
    if not user_data or not user_data.get("registered"):
        await update.message.reply_text("❌ شما هنوز ثبت نام نکرده‌اید! لطفا ابتدا /start را بزنید.")
        return

    user_codes_ids = user_data.get("codes", [])
    all_codes_db = db.get("codes", {})
    unsettled_codes = []
    for code_id in user_codes_ids:
        code_info = all_codes_db.get(str(code_id))
        if code_info and not code_info.get("settled"):
            is_pending = False
            for settlement_data in db.get("settlements", {}).values():
                if str(settlement_data.get("code_id")) == str(code_id) and \
                   str(settlement_data.get("user_id")) == user_id_str and \
                   settlement_data.get("status") == "pending":
                    is_pending = True
                    break
            if not is_pending:
                unsettled_codes.append(code_id)

    if not unsettled_codes:
        await update.message.reply_text("❌ شما در حال حاضر هیچ کد جایزه تسویه نشده و بدون درخواست فعال ندارید.")
        return

    keyboard = []
    for code_id in unsettled_codes:
        keyboard.append([InlineKeyboardButton(f"درخواست تسویه برای کد {code_id}", callback_data=f"settle_{code_id}")])
    keyboard.append([InlineKeyboardButton("انصراف و بازگشت", callback_data="cancel_settlement_selection")])

    await update.message.reply_text(
        "لطفا کد جایزه‌ای که می‌خواهید برای آن درخواست تسویه ثبت کنید را از لیست زیر انتخاب نمایید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    user_id_str = str(update.effective_user.id)
    db = load_db()
    if user_id_str not in db.get("users", {}) or not db["users"][user_id_str].get("registered", False):
        await update.message.reply_text("❌ برای استفاده از این بخش، ابتدا باید از طریق /start ثبت نام کنید.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    keyboard = ReplyKeyboardMarkup([
        ["ایجاد درخواست پشتیبانی جدید 📮"],
        ["بازگشت به منو اصلی 🔙"]
    ], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("بخش پشتیبانی و ارتباط با ادمین:", reply_markup=keyboard)

async def create_support_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "لطفا پیام خود را به طور کامل برای تیم پشتیبانی ارسال کنید:",
        reply_markup=ReplyKeyboardMarkup([["انصراف از ارسال پیام 🔙"]], resize_keyboard=True, one_time_keyboard=True)
    )
    return SUPPORT_MESSAGE

async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "انصراف از ارسال پیام 🔙":
        await update.message.reply_text("ارسال پیام به پشتیبانی لغو شد. بازگشت به منو اصلی.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    user_id = update.effective_user.id
    db = load_db()

    ticket_id = db.get("next_ticket_id", 1)
    db["next_ticket_id"] = ticket_id + 1

    db.setdefault("support_tickets", {})[str(ticket_id)] = {
        "user_id": user_id,
        "message": update.message.text,
        "date": datetime.now().isoformat(),
        "status": "open",
        "response": None,
        "response_date": None,
        "responded_by": None
    }
    save_db(db)

    await update.message.reply_text(
        f"✅ درخواست پشتیبانی شما با شماره پیگیری `{ticket_id}` با موفقیت ثبت شد.\n"
        "تیم پشتیبانی در اسرع وقت پیام شما را بررسی و پاسخ خواهد داد. از شکیبایی شما سپاسگزاریم.",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

    admins_to_notify = db.get("admins", [])
    user_info = db.get("users", {}).get(str(user_id), {})
    user_name_display = user_info.get('name', f"کاربر ناشناس")
    user_tg_username = user_info.get('username', 'ندارد')
    notification_text = (
        f"🔔 **درخواست پشتیبانی جدید دریافت شد!** 🔔\n\n"
        f"شماره تیکت: `{ticket_id}`\n"
        f"از طرف: {user_name_display} (ID: `{user_id}`)\n"
        f"یوزرنیم تلگرام: @{user_tg_username}\n"
        f"پیام کاربر:\n---<br>{update.message.text[:500]}{'...' if len(update.message.text) > 500 else ''}<br>---\n\n"
        f"برای پاسخگویی، به پنل ادمین، بخش مدیریت درخواست‌های پشتیبانی مراجعه کنید."
    ).replace("<br>", "\n")


    for admin_id_val in admins_to_notify:
        try:
            await context.bot.send_message(admin_id_val, notification_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logging.warning(f"Failed to notify admin {admin_id_val} about new support ticket {ticket_id}: {e}")

    return ConversationHandler.END

async def edit_menu_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    user_id_str = str(update.effective_user.id)
    db = load_db()
    if user_id_str not in db.get("users", {}) or not db["users"][user_id_str].get("registered", False):
        await update.message.reply_text("❌ برای استفاده از این بخش، ابتدا باید از طریق /start ثبت نام کنید.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    await update.message.reply_text("کدام یک از اطلاعات خود را می‌خواهید ویرایش کنید؟", reply_markup=get_edit_keyboard())
    return EDIT_MENU

async def handle_edit_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    reply_cancel_keyboard = ReplyKeyboardMarkup([["انصراف از ویرایش 🔙"]], resize_keyboard=True, one_time_keyboard=True)
    next_state = None
    prompt_message = ""
    custom_keyboard = None # Edit phone number keyboard
    context.user_data['current_edit_field'] = None

    if text == "ویرایش شماره تماس 📱":
        prompt_message = "لطفا شماره تماس جدید خود را با استفاده از دکمه زیر ارسال کنید یا به صورت دستی (با کد کشور) وارد نمایید:"
        #Custom keyboard for phone number
        custom_keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("ارسال شماره تماس جدید📱", request_contact=True)],
            ["انصراف از ویرایش 🔙"]
        ], resize_keyboard=True, one_time_keyboard=True)
        next_state = EDIT_PHONE
        context.user_data['current_edit_field'] = 'phone'
    elif text == "ویرایش نام و نام خانوادگی 👤":
        prompt_message = "لطفا نام و نام خانوادگی جدید خود را ارسال کنید:"
        next_state = EDIT_NAME; context.user_data['current_edit_field'] = 'name'
        custom_keyboard = reply_cancel_keyboard 
    elif text == "ویرایش شماره کارت 💳":
        prompt_message = "لطفا شماره کارت جدید خود را ارسال کنید (16 رقم):"
        next_state = EDIT_CARD; context.user_data['current_edit_field'] = 'card'
        custom_keyboard = reply_cancel_keyboard
    elif text == "ویرایش شماره شبا 🏦":
        prompt_message = "لطفا شماره شبا جدید خود را ارسال کنید (24 رقم عددی، بدون IR):"
        next_state = EDIT_SHEBA; context.user_data['current_edit_field'] = 'sheba'
        custom_keyboard = reply_cancel_keyboard
    elif text == "ویرایش نام بانک 🏛️":
        prompt_message = "لطفا نام بانک جدید خود را ارسال کنید:"
        next_state = EDIT_BANK; context.user_data['current_edit_field'] = 'bank'
        custom_keyboard = reply_cancel_keyboard
    elif text == "بازگشت به منو اصلی 🔙":
        await update.message.reply_text("بازگشت به منو اصلی.", reply_markup=get_main_keyboard())
        context.user_data.pop('current_edit_field', None)
        return ConversationHandler.END
    else:
        await update.message.reply_text("گزینه انتخاب شده معتبر نیست. لطفا از دکمه‌های زیر استفاده کنید.", reply_markup=get_edit_keyboard())
        return EDIT_MENU

    if prompt_message and next_state:
        final_keyboard = custom_keyboard if custom_keyboard else reply_cancel_keyboard
        await update.message.reply_text(prompt_message, reply_markup=final_keyboard)
        return next_state
    return EDIT_MENU


async def generic_edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, field_name: str, validation_func, error_message: str, success_message: str, next_conv_state):
    if update.message.text == "انصراف از ویرایش 🔙":
        await update.message.reply_text(f"ویرایش {field_name} لغو شد.", reply_markup=get_edit_keyboard())
        context.user_data.pop('current_edit_field', None)
        return EDIT_MENU

    user_id_str = str(update.effective_user.id)
    db = load_db()
    new_value = update.message.text.strip()

    is_valid, processed_value = validation_func(new_value)

    if not is_valid:
        await update.message.reply_text(error_message)
        return next_conv_state # Stay in the current editing state

    current_field = context.user_data.get('current_edit_field')
    if not current_field: # Should not happen if logic is correct
        logging.error(f"generic_edit_handler: current_edit_field is missing in user_data for user {user_id_str}")
        await update.message.reply_text("خطای داخلی رخ داده است. لطفا دوباره امتحان کنید.", reply_markup=get_edit_keyboard())
        return EDIT_MENU

    db["users"][user_id_str][current_field] = processed_value
    save_db(db)
    await update.message.reply_text(success_message, reply_markup=get_edit_keyboard())
    context.user_data.pop('current_edit_field', None)
    return EDIT_MENU

def validate_phone(value):
    original_value = value
    if value.startswith('00'): value = '+' + value[2:]
    elif value.startswith('09') and not value.startswith('+'): value = '+98' + value[1:]
    elif value.isdigit() and len(value) == 10 and value.startswith('9'): value = '+98' + value # e.g. 9123456789

    # Basic validation: starts with +, contains only digits after +, length between 10 and 15 (e.g. +989123456789 is 13)
    if not value.startswith('+') or not value[1:].isdigit() or not (10 <= len(value) <= 15) :
        return False, original_value
    return True, value

def validate_name(value): return (bool(value) and len(value) >= 3 and not any(char.isdigit() for char in value)), value
def validate_card(value): value = value.replace(" ", "").replace("-", ""); return (value.isdigit() and len(value) == 16), value
def validate_sheba(value): value = value.replace(" ", "").upper().replace("IR", ""); return (value.isdigit() and len(value) == 24), value
def validate_bank(value): return (bool(value) and len(value) >= 2 and not any(char.isdigit() for char in value)), value


async def handle_edit_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This function will now be called by handle_phone if 'current_edit_field' is 'phone'
    return await generic_edit_handler(update, context, "شماره تماس", validate_phone,
                                      "❌ شماره تماس معتبر نیست. باید با کد کشور شروع شود (مثال: +989123456789) و فقط شامل اعداد باشد.",
                                      "✅ شماره تماس شما با موفقیت بروزرسانی شد.", EDIT_PHONE)


async def handle_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await generic_edit_handler(update, context, "نام و نام خانوادگی", validate_name,
                                      "❌ نام وارد شده معتبر نیست (باید حداقل 3 حرف و بدون عدد باشد).",
                                      "✅ نام و نام خانوادگی شما با موفقیت بروزرسانی شد.", EDIT_NAME)

async def handle_edit_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await generic_edit_handler(update, context, "شماره کارت", validate_card,
                                      "❌ شماره کارت باید 16 رقم و فقط شامل اعداد باشد.",
                                      "✅ شماره کارت شما با موفقیت بروزرسانی شد.", EDIT_CARD)

async def handle_edit_sheba(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await generic_edit_handler(update, context, "شماره شبا", validate_sheba,
                                      "❌ شماره شبا باید 24 رقم عددی باشد (بدون IR).",
                                      "✅ شماره شبا شما با موفقیت بروزرسانی شد.", EDIT_SHEBA)

async def handle_edit_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await generic_edit_handler(update, context, "نام بانک", validate_bank,
                                      "❌ نام بانک وارد شده معتبر نیست (باید حداقل 2 حرف و بدون عدد باشد).",
                                      "✅ نام بانک شما با موفقیت بروزرسانی شد.", EDIT_BANK)


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    help_text = """
📚 **راهنمای جامع ربات** 📚

سلام! به ربات اختصاصی مجموعه داریوش خوش آمدید. در اینجا نحوه کار با ربات و کسب درآمد از طریق دریافت امتیاز توضیح داده شده است:

📝 **۱. ثبت نام اولیه:**
   - برای شروع، دستور /start را ارسال کنید.
   - ربات از شما می‌خواهد در کانال اطلاع‌رسانی (@Your-Channel-Id) عضو شوید. پس از عضویت، دکمه "✅ عضو شدم" را بزنید.
   - سپس، اطلاعات خواسته شده: شماره تماس، نام و نام خانوادگی، شماره کارت، شماره شبا و نام بانک را به درستی وارد کنید. از آنجایی که تمامی جوایز در مجموعه ما به صورت نقدی است، وارد کردن این اطلاعات برای واریز جوایز ضروری است.

🎯 **۲. نحوه کسب امتیاز:**
   - پس از عضویت در @Your-Channel-Id و ثبت نام در ربات، شروع به عضو کردن مخاطبین خود به گروه کنید.
   - به ازای هر عضو جدیدی که توسط شما به @Your-Channel-Id اضافه می‌شود، ۱ امتیاز به شما تعلق می‌گیرد.
   - افراد متوجه اینکه چه کسی آن‌ها را به گروه اضافه کرده نخواهند شد، پس با خیال راحت مخاطبین خود را اضافه کنید و کسب درآمد کنید.
   - هر کاربر جدید تنها یک بار در کل سیستم ربات شمارش می‌شود. یعنی اگر کاربری قبلاً توسط شما یا فرد دیگری به یکی از گروه‌هایی که ربات در آن حضور دارد اضافه شده باشد، اضافه کردن مجدد او (حتی به گروهی دیگر) امتیازی نخواهد داشت.
   - این سیستم به منظور جلوگیری از تقلب پیاده‌سازی شده، پس حتماً دقت کنید که مخاطبین را فقط و فقط در گروه @Your-Channel-Id عضو کنید تا امتیاز آن شخص را دریافت کنید.

🏆 **۳. امتیازات من:**
   - با انتخاب گزینه "امتیازات من 🏆" از منوی اصلی، می‌توانید تعداد کل امتیازات کسب شده و تعداد کدهای جایزه فعال خود را مشاهده کنید.

🎫 ۴. کدهای جایزه:
   - به ازای هر ۱۰۰ امتیاز، یک کد جایزه به طور خودکار برای شما صادر می‌شود.
   - هر یک کد جایزه معادل ۱۰۰ هزار تومان وجه نقد است.
   - با انتخاب "کدهای من 🎫"، لیست کدهای جایزه خود به همراه وضعیت آنها (تسویه شده / در انتظار تسویه) را مشاهده می‌کنید.

💰 ۵. تسویه حساب:
   - از منوی "تسویه حساب 💰"، می‌توانید کدهای جایزه‌ای که هنوز تسویه نشده‌اند و درخواست تسویه فعالی برای آنها ثبت نکرده‌اید را انتخاب کنید.
   - پس از انتخاب کد، درخواست شما برای بخش مالی ارسال می‌شود.
   - تیم پشتیبانی در بخش مالی پس از بررسی کد شما، مبلغ را به حساب شما واریز می‌کند و فیش واریزی را در سیستم ثبت کرده و از طریق ربات برای شما ارسال می‌کند.
   - توجه: در صورتی که اطلاعات وارد شده توسط شما با کارت بانکی مغایرت داشته باشد، درخواست تسویه حساب شما رد و کد جایزه شما ابطال می‌شود.

✏️ ۶. ویرایش اطلاعات:
   - از گزینه "ویرایش اطلاعات ✏️" می‌توانید اطلاعات ثبت‌نامی خود را (شماره تماس، نام، کارت، شبا، بانک) تغییر دهید. دقت در صحت این اطلاعات برای تسویه حساب بسیار مهم است.

📞 ۷. ارتباط با پشتیبانی:
   - در صورت داشتن هرگونه سوال، مشکل یا پیشنهاد، از طریق "ارتباط با پشتیبانی 📞" یک تیکت جدید ایجاد کنید.
   - پیام شما به تیم پشتیبانی ربات ارسال شده و پس از بررسی، پاسخ از طریق همین ربات به شما اطلاع داده خواهد شد.

🌟 نکات مهم:
   - عضویت در کانال @Your-Channel-Id برای استفاده از ربات و دریافت اطلاعیه‌ها الزامی است.
   - امنیت اطلاعات کاربران برای ما در اولویت قرار دارد. داده‌های شما با استفاده از پروتکل‌های استاندارد و روش‌های رمزنگاری پیشرفته محافظت می‌شوند تا از دسترسی غیرمجاز جلوگیری شده و محرمانگی آنها حفظ گردد.
   - اطلاعات بانکی شما محرمانه تلقی شده و فقط برای امور تسویه حساب استفاده خواهد شد.
   - قوانین مربوط به میزان امتیازدهی و ارزش کدهای جایزه ممکن است توسط ادمین تغییر کند. اطلاعیه‌ها از طریق کانال تلگرامی و ربات اعلام خواهد شد.

موفق باشید و امتیازهای زیادی کسب کنید! 🎉
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# --- Admin Panel ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []):
        await update.message.reply_text("❌ شما دسترسی ادمین ندارید!")
        return

    await update.message.reply_text("⏳ در حال به‌روزرسانی اطلاعات گروه‌ها... این عملیات ممکن است چند لحظه طول بکشد.")
    try:
        await update_groups_list_simplified(context.bot)
        await update.message.reply_text("🔧 پنل مدیریت ربات:", reply_markup=get_admin_keyboard())
    except Exception as e:
        logging.error(f"Error during admin panel group update: {e}", exc_info=True)
        await update.message.reply_text(f"خطا در به‌روزرسانی اطلاعات گروه: {e}. لطفاً لاگ‌ها را بررسی کنید.", reply_markup=get_admin_keyboard())


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []):
        await update.message.reply_text("❌ شما دسترسی ادمین ندارید!")
        return

    await update.message.reply_text("⏳ در حال جمع‌آوری و به‌روزرسانی آمار...")
    await update_groups_list_simplified(context.bot)
    db = load_db()

    total_users_interacted = len(db.get("users", {}))
    registered_users = sum(1 for u_data in db.get("users", {}).values() if u_data.get("registered"))
    total_codes = len(db.get("codes", {}))
    pending_settlements = sum(1 for s_data in db.get("settlements", {}).values() if s_data.get("status") == "pending")
    open_tickets = sum(1 for t_data in db.get("support_tickets", {}).values() if t_data.get("status") == "open")
    active_groups_in_db = len(db.get("groups", {}))

    text = f"""
📊 **آمار کلی ربات:**

👤 تعداد کل کاربرانی که با ربات تعامل داشته‌اند (استارت زده‌اند): {total_users_interacted}
✅ کاربران با ثبت نام تکمیل شده: {registered_users}
👥 تعداد اعضای منحصر به فرد اضافه شده به گروه‌ها (توسط همه): {len(db.get("unique_members", {}))}
🏢 تعداد گروه‌هایی که ربات حداقل یکبار در آنها ادمین شده و هنوز خارج نشده: {active_groups_in_db}
🎫 کل کدهای جایزه صادر شده: {total_codes}
💳 درخواست‌های تسویه در انتظار تایید ادمین: {pending_settlements}
📮 تیکت‌های پشتیبانی باز و در انتظار پاسخ: {open_tickets}
🔗 تعداد لینک‌های تبلیغاتی ثبت شده: {len(db.get("promotional_links", []))}
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def export_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []):
        await update.message.reply_text("❌ شما دسترسی ادمین ندارید!")
        return

    await update.message.reply_text("⏳ در حال آماده‌سازی فایل اکسل کاربران ثبت‌نام شده...")
    users_data = []
    for user_id_str_val, user_data in db.get("users", {}).items():
        if user_data.get("registered"):
            reg_date_iso = user_data.get("registration_date", "")
            try:
                reg_date_formatted = datetime.fromisoformat(reg_date_iso).strftime('%Y-%m-%d %H:%M:%S') if reg_date_iso else "نامشخص"
            except ValueError:
                reg_date_formatted = reg_date_iso

            users_data.append({
                "شناسه کاربری تلگرام": user_id_str_val,
                "نام کاربری تلگرام": user_data.get("username", "ندارد"),
                "نام و نام خانوادگی": user_data.get("name", "ثبت نشده"),
                "شماره تماس": user_data.get("phone", "ثبت نشده"),
                "شماره کارت": user_data.get("card", "ثبت نشده"),
                "شماره شبا (بدون IR)": user_data.get("sheba", "ثبت نشده"),
                "نام بانک": user_data.get("bank", "ثبت نشده"),
                "امتیازات": user_data.get("points", 0),
                "تعداد کدهای دریافتی": len(user_data.get("codes", [])),
                "تاریخ ثبت نام": reg_date_formatted
            })

    if not users_data:
        await update.message.reply_text("❌ هیچ کاربر ثبت‌نام شده‌ای برای خروجی یافت نشد.")
        return

    df = pd.DataFrame(users_data)
    file_name = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    try:
        df.to_excel(file_name, index=False, engine='openpyxl')
        with open(file_name, 'rb') as f:
            await update.message.reply_document(f, caption="📄 فایل اکسل اطلاعات کاربران ثبت‌نام شده.")
    except Exception as e:
        logging.error(f"Error creating or sending Excel file: {e}", exc_info=True)
        await update.message.reply_text(f"❌ خطایی در ایجاد یا ارسال فایل اکسل رخ داد: {e}")
    finally:
        if os.path.exists(file_name):
            try:
                os.remove(file_name)
            except Exception as e_remove:
                logging.error(f"Error removing temporary Excel file {file_name}: {e_remove}")


async def manage_settlements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return
    keyboard = ReplyKeyboardMarkup([
        ["مشاهده درخواست‌های تسویه فعال 📋"],
        ["برگشت به منو ادمین 🔙"]
    ], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("بخش مدیریت درخواست‌های تسویه حساب:", reply_markup=keyboard)

async def show_active_settlements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return

    pending_settlements = []
    for settle_id, settlement_data in db.get("settlements", {}).items():
        if settlement_data.get("status") == "pending":
            pending_settlements.append((settle_id, settlement_data))

    if not pending_settlements:
        await update.message.reply_text("❌ در حال حاضر هیچ درخواست تسویه فعالی برای بررسی وجود ندارد.")
        return

    inline_keyboard = []
    for settle_id, settlement_data in pending_settlements:
        user_info = db.get("users", {}).get(str(settlement_data.get("user_id")), {})
        user_name = user_info.get('name', f"کاربر {settlement_data.get('user_id')}")
        code_id = settlement_data.get('code_id', 'N/A')
        try:
            req_date = datetime.fromisoformat(settlement_data.get("date", "")).strftime('%y/%m/%d')
        except:
            req_date = ""
        button_text = f"کد {code_id} - {user_name} ({req_date})"
        inline_keyboard.append([InlineKeyboardButton(button_text, callback_data=f"admin_settle_{settle_id}")])

    if not inline_keyboard:
         await update.message.reply_text("❌ مشکلی در آماده‌سازی لیست درخواست‌ها پیش آمد.")
         return

    await update.message.reply_text(
        "لیست درخواست‌های تسویه در انتظار تایید (برای پردازش، روی یکی از موارد زیر کلیک کنید):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard)
    )

async def manage_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return
    keyboard = ReplyKeyboardMarkup([
        ["مشاهده تیکت‌های پشتیبانی باز 📋"],
        ["برگشت به منو ادمین 🔙"]
    ], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("بخش مدیریت درخواست‌های پشتیبانی کاربران:", reply_markup=keyboard)

async def show_active_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return

    open_tickets = []
    for ticket_id, ticket_data in db.get("support_tickets", {}).items():
        if ticket_data.get("status") == "open":
            open_tickets.append((ticket_id, ticket_data))
    open_tickets.sort(key=lambda x: x[1].get("date", ""), reverse=True)

    if not open_tickets:
        await update.message.reply_text("✅ در حال حاضر هیچ تیکت پشتیبانی بازی برای پاسخگویی وجود ندارد.")
        return

    inline_keyboard = []
    for ticket_id, ticket_data in open_tickets:
        user_info = db.get("users", {}).get(str(ticket_data.get("user_id")), {})
        user_name = user_info.get("name", f"کاربر {ticket_data.get('user_id')}")
        try:
            ticket_date = datetime.fromisoformat(ticket_data.get("date", "")).strftime('%y/%m/%d %H:%M')
        except:
            ticket_date = ""
        button_text = f"تیکت {ticket_id} - {user_name} ({ticket_date})"
        inline_keyboard.append([InlineKeyboardButton(button_text, callback_data=f"admin_ticket_{ticket_id}")])

    if not inline_keyboard:
        await update.message.reply_text("❌ مشکلی در آماده‌سازی لیست تیکت‌ها پیش آمد.")
        return

    await update.message.reply_text(
        "لیست تیکت‌های پشتیبانی باز (برای مشاهده و پاسخ، روی یکی از موارد زیر کلیک کنید):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard)
    )


async def manage_promotional_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return
    keyboard = ReplyKeyboardMarkup([
        ["لیست لینک‌های تبلیغاتی 📋", "افزودن لینک جدید ➕"],
        ["حذف لینک ❌", "برگشت به منو ادمین 🔙"]
    ], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("بخش مدیریت لینک‌های تبلیغاتی تعریف شده برای ربات:", reply_markup=keyboard)

async def list_promotional_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return

    promo_links = db.get("promotional_links", [])
    if not promo_links:
        await update.message.reply_text("❌ در حال حاضر هیچ لینک تبلیغاتی در سیستم ثبت نشده است.")
        return

    text = "📋 لیست لینک‌های تبلیغاتی فعال که ربات به آنها اشاره می‌کند:\n\n"
    for i, link in enumerate(promo_links, 1):
        text += f"{i}. {link}\n"
    await update.message.reply_text(text)

async def add_promotional_link_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return
    keyboard = ReplyKeyboardMarkup([["انصراف و بازگشت به مدیریت لینک‌ها 🔙"]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "لطفا لینک کامل کانال یا گروه مورد نظر را ارسال کنید (مثال: https://t.me/mychannelid) یا فقط آیدی با @ (مثال: @mychannelid):",
        reply_markup=keyboard
    )
    return ADMIN_ADD_LINK

async def handle_add_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "انصراف و بازگشت به مدیریت لینک‌ها 🔙":
        await manage_promotional_links(update, context)
        return ConversationHandler.END

    db = load_db()
    link_input = update.message.text.strip()
    full_link = ""

    if link_input.startswith("@"):
        if len(link_input) > 1:
            full_link = f"https://t.me/{link_input[1:]}"
        else:
            await update.message.reply_text("❌ آیدی وارد شده با @ معتبر نیست. مثال صحیح: @channelname")
            return ADMIN_ADD_LINK
    elif link_input.lower().startswith("https://t.me/"):
        full_link = link_input
    elif link_input.lower().startswith("t.me/"):
        full_link = "https://" + link_input
    else:
        full_link = f"https://t.me/{link_input}"


    if not full_link or len(full_link) < len("https://t.me/a"):
        await update.message.reply_text("❌ لینک وارد شده معتبر به نظر نمی‌رسد. لطفا دوباره تلاش کنید.")
        return ADMIN_ADD_LINK

    if full_link not in db.get("promotional_links", []):
        db.setdefault("promotional_links", []).append(full_link)
        save_db(db)
        await update.message.reply_text(f"✅ لینک '{full_link}' با موفقیت به لیست لینک‌های تبلیغاتی اضافه شد.")
    else:
        await update.message.reply_text("❌ این لینک قبلاً در لیست موجود است.")

    await manage_promotional_links(update, context)
    return ConversationHandler.END

async def remove_promotional_link_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return

    promo_links = db.get("promotional_links", [])
    if not promo_links:
        await update.message.reply_text("❌ هیچ لینکی برای حذف وجود ندارد.")
        # No need to call manage_promotional_links here, as the current menu is likely manage_promotional_links itself
        # or the user will be returned to admin menu by the general text handler.
        return # Simply return, user is likely in the link management menu.

    text = "🔗 لیست لینک‌های موجود برای حذف:\n\n" # This text might not be needed if we directly show inline kbd
    keyboard_buttons = []
    for i, link in enumerate(promo_links):
        keyboard_buttons.append([InlineKeyboardButton(f"حذف: {link}", callback_data=f"del_promo_link_{i}")])
    keyboard_buttons.append([InlineKeyboardButton("انصراف و بازگشت", callback_data="cancel_del_promo_link")])

    if not keyboard_buttons: # Should only happen if promo_links was empty and we didn't return earlier
        await update.message.reply_text("❌ هیچ لینکی برای نمایش جهت حذف یافت نشد.")
        return

    await update.message.reply_text( # Changed from text variable
        "لطفا لینکی که می‌خواهید حذف کنید را از لیست زیر انتخاب نمایید:",
        reply_markup=InlineKeyboardMarkup(keyboard_buttons)
    )


async def broadcast_message_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return

    groups_for_broadcast = db.get("groups", {})

    if not groups_for_broadcast:
        await update.message.reply_text("❌ هیچ گروهی در دیتابیس برای ارسال پیام همگانی یافت نشد.")
        return ConversationHandler.END

    keyboard = ReplyKeyboardMarkup([["انصراف از ارسال همگانی 🔙"]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        f"پیام خود را برای ارسال به {len(groups_for_broadcast)} گروه ثبت شده در دیتابیس، ارسال کنید:",
        reply_markup=keyboard
    )
    return ADMIN_BROADCAST

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "انصراف از ارسال همگانی 🔙":
        await update.message.reply_text("ارسال پیام همگانی لغو شد.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    db = load_db()
    message_to_broadcast = update.message.text
    active_groups_map = db.get("groups", {})
    sent_count = 0
    failed_count = 0
    failed_group_details = []

    if not active_groups_map:
        await update.message.reply_text("❌ هیچ گروهی برای ارسال پیام یافت نشد (مجدداً بررسی شد).", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    await update.message.reply_text(f"⏳ در حال ارسال پیام به {len(active_groups_map)} گروه. این عملیات ممکن است زمان‌بر باشد...")

    for group_id_str, group_data in active_groups_map.items():
        group_title = group_data.get("title", group_id_str)
        try:
            await context.bot.send_message(int(group_id_str), message_to_broadcast)
            sent_count += 1
            logging.info(f"Broadcast sent successfully to group {group_title} ({group_id_str})")
        except Exception as e:
            failed_count += 1
            logging.error(f"Failed to send broadcast to group {group_title} ({group_id_str}): {e}")
            failed_group_details.append(f"- گروه '{group_title}' (ID: {group_id_str}): {type(e).__name__}")
        await asyncio.sleep(0.3)

    result_message = f"📣 **نتیجه ارسال پیام همگانی:**\n\n"
    result_message += f"✅ با موفقیت به {sent_count} گروه ارسال شد.\n"
    if failed_count > 0:
        result_message += f"❌ ارسال به {failed_count} گروه ناموفق بود.\n"
        if failed_group_details:
            result_message += "\nجزئیات گروه‌های ناموفق:\n" + "\n".join(failed_group_details)
            result_message += "\n\n(دلایل رایج عدم موفقیت: ربات دیگر در گروه عضو نیست، ادمین نیست، یا از گروه اخراج شده است. جزئیات بیشتر در لاگ‌های سرور ربات موجود است.)"

    await update.message.reply_text(result_message, reply_markup=get_admin_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def manage_admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return
    keyboard = ReplyKeyboardMarkup([
        ["لیست ادمین‌های ربات 👥", "افزودن ادمین جدید ➕"],
        ["حذف ادمین ❌", "برگشت به منو ادمین 🔙"]
    ], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("بخش مدیریت ادمین‌های ربات:", reply_markup=keyboard)


async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []):
        # No need to send a message here if it's called from handle_text,
        # as handle_text already checks admin status.
        # If called directly, this check is fine.
        # await update.message.reply_text("❌ شما دسترسی ادمین ندارید!")
        return

    admin_ids = db.get("admins", [])
    if not admin_ids: # Should not happen as ADMIN_ID is always there
        await update.message.reply_text("❌ خطای داخلی: هیچ ادمینی در سیستم یافت نشد.")
        return

    text = "👥 لیست ادمین‌های فعلی ربات:\n\n"

    def escape_markdown_v1(text_to_escape: str) -> str:
        if not text_to_escape:
            return ""
        # For MarkdownV1, primarily escape _, *, `
        # \ is used for escaping in MarkdownV1 e.g. \_
        escaped = text_to_escape.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        return escaped

    for i, admin_id_val in enumerate(admin_ids, 1):
        name_display_raw = f"کاربر با شناسه"  # Default if get_chat fails or no name
        username_raw = ""
        try:
            
            chat = await context.bot.get_chat(int(admin_id_val))
            current_name = chat.full_name or chat.first_name
            if current_name: # Ensure there's some name
                name_display_raw = current_name
            elif not current_name and chat.username: # If no name but username exists
                 name_display_raw = f"@{chat.username}" # Use username as name
            else: # If no name and no username, use the ID fallback
                name_display_raw = f"کاربر {admin_id_val}"


            if chat.username:
                username_raw = chat.username
        except Exception as e:
            logging.warning(f"Could not fetch info for admin ID {admin_id_val}: {e}")
            name_display_raw = f"کاربر {admin_id_val}" # Fallback if chat fetch fails

        safe_name_display = escape_markdown_v1(name_display_raw)
        username_mention_display = ""
        if username_raw:
            safe_username = escape_markdown_v1(username_raw)
            username_mention_display = f" (@{safe_username})" # Username itself is escaped, @ and () are not MD special

        text += f"{i}. {safe_name_display} (ID: `{admin_id_val}`){username_mention_display}\n"
        if admin_id_val == ADMIN_ID:
            text += "   **(ادمین اصلی)**\n" # This **bold** is fine for MarkdownV1

    try:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logging.error(f"Error sending admin list: {e}. Text was: {text}", exc_info=True)
        await update.message.reply_text("خطایی در نمایش لیست ادمین‌ها رخ داد. ممکن است به دلیل کاراکترهای خاص در نام‌ها باشد. لاگ‌ها را بررسی کنید.")


async def add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return
    keyboard = ReplyKeyboardMarkup([["انصراف و بازگشت به مدیریت ادمین‌ها 🔙"]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "لطفا شناسه عددی (User ID) کاربر تلگرامی که می‌خواهید به عنوان ادمین جدید اضافه کنید را ارسال نمایید:",
        reply_markup=keyboard
    )
    return ADMIN_ADD_ADMIN

async def handle_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "انصراف و بازگشت به مدیریت ادمین‌ها 🔙":
        await manage_admins_cmd(update, context)
        return ConversationHandler.END

    db = load_db()
    try:
        new_admin_id_input = update.message.text.strip()
        if not new_admin_id_input.isdigit():
            raise ValueError("شناسه باید عددی باشد.")
        new_admin_id = int(new_admin_id_input)
        if new_admin_id <= 0:
            raise ValueError("شناسه عددی باید مثبت باشد.")

        try:
            await context.bot.get_chat(new_admin_id)
            logging.info(f"Successfully fetched chat info for potential new admin ID: {new_admin_id}")
        except Exception as e:
            logging.warning(f"Could not fetch chat info for new admin ID {new_admin_id}: {e}. Proceeding with adding ID.")

        if new_admin_id not in db.get("admins", []):
            db.setdefault("admins", []).append(new_admin_id)
            save_db(db)
            await update.message.reply_text(f"✅ کاربر با شناسه `{new_admin_id}` با موفقیت به لیست ادمین‌ها اضافه شد.")
        else:
            await update.message.reply_text("❌ این کاربر در حال حاضر جزو ادمین‌های ربات می‌باشد.")

    except ValueError as ve:
        await update.message.reply_text(f"❌ ورودی نامعتبر: {ve}. لطفا فقط شناسه عددی کاربر را ارسال کنید.")
        return ADMIN_ADD_ADMIN

    await manage_admins_cmd(update, context)
    return ConversationHandler.END


async def remove_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return

    admin_ids = db.get("admins", [])
    removable_admins = [ad_id for ad_id in admin_ids if ad_id != ADMIN_ID]

    if not removable_admins:
        await update.message.reply_text("❌ هیچ ادمین دیگری (به جز ادمین اصلی) برای حذف وجود ندارد.")
        # await manage_admins_cmd(update, context) # No need, user is likely in admin management menu
        return

    
    keyboard_buttons = []

    def escape_text_for_button(text_to_escape: str) -> str: # Simple escape for button text if needed
        if not text_to_escape: return ""
        return text_to_escape # Usually not needed for button text unless it's very long or complex

    for i, admin_id_val in enumerate(removable_admins):
        name_display = f"ادمین {i+1}"
        username_display_part = ""
        try:
            chat = await context.bot.get_chat(int(admin_id_val)) # Ensure int
            current_name = chat.full_name or chat.first_name
            if current_name: name_display = current_name
            elif chat.username: name_display = f"@{chat.username}"
            else: name_display = f"کاربر {admin_id_val}"

            if chat.username: username_display_part = f" (@{chat.username})"
        except: pass # Keep default name_display if get_chat fails

        button_text = f"حذف: {escape_text_for_button(name_display)} (ID: {admin_id_val}){escape_text_for_button(username_display_part)}"
        # Truncate button text if too long, Telegram has limits
        max_button_len = 60 # Approximation
        if len(button_text) > max_button_len:
            button_text = button_text[:max_button_len-3] + "..."

        keyboard_buttons.append([InlineKeyboardButton(button_text, callback_data=f"del_admin_{admin_id_val}")])

    keyboard_buttons.append([InlineKeyboardButton("انصراف و بازگشت", callback_data="cancel_del_admin")])
    await update.message.reply_text(
        "لطفا ادمینی که می‌خواهید حذف کنید را از لیست زیر انتخاب نمایید (ادمین اصلی قابل حذف نیست):",
        reply_markup=InlineKeyboardMarkup(keyboard_buttons)
    )


async def switch_to_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    if user_id not in db.get("admins", []): return
    await update.message.reply_text("بازگشت به منوی کاربران:", reply_markup=get_main_keyboard())

# --- Group Member Tracking ---
async def track_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    adder_user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title or f"گروه {chat_id}"

    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            logging.info(f"track_new_member: Bot is not admin in group '{chat_title}' ({chat_id}). Ignoring new members.")
            return
    except Exception as e:
        logging.error(f"track_new_member: Could not verify bot admin status in chat {chat_id}: {e}. Ignoring.")
        return

    db = load_db()
    group_id_str = str(chat_id)

    if group_id_str not in db.get("groups", {}):
        logging.warning(f"track_new_member: Group '{chat_title}' ({group_id_str}) was not in db['groups'] but bot is admin. Adding it now.")
        db.setdefault("groups", {})[group_id_str] = {"title": chat_title, "members": []}

    group_data = db["groups"].get(group_id_str, {"title": chat_title, "members": []})
    group_members_list = group_data.get("members", [])


    points_awarded_this_event = 0
    newly_added_to_group_db = False
    changes_made_to_db = False # Flag to save DB once at the end

    for new_member in update.message.new_chat_members:
        if new_member.is_bot:
            logging.info(f"track_new_member: Ignoring new bot member {new_member.id} in group {chat_id}.")
            continue

        new_member_id_str = str(new_member.id)

        if new_member_id_str not in db.get("unique_members", {}):
            db.setdefault("unique_members", {})[new_member_id_str] = {
                "first_added_by": adder_user_id,
                "first_added_date": datetime.now().isoformat(),
                "first_group_id": group_id_str,
                "first_group_title": chat_title,
                "added_by_username": update.effective_user.username or "ندارد",
                "new_member_username": new_member.username or "ندارد"
            }
            changes_made_to_db = True
            logging.info(f"track_new_member: New unique member {new_member_id_str} added by {adder_user_id} to system via group {chat_id}.")

            adder_user_id_str = str(adder_user_id)
            if adder_user_id_str in db.get("users", {}) and db["users"][adder_user_id_str].get("registered"):
                db["users"][adder_user_id_str]["points"] = db["users"][adder_user_id_str].get("points", 0) + 1
                points_awarded_this_event += 1
                changes_made_to_db = True
                current_points = db["users"][adder_user_id_str]["points"]
                logging.info(f"track_new_member: User {adder_user_id_str} awarded 1 point. Total points: {current_points}.")

                if current_points > 0 and current_points % 100 == 0:
                    new_code_id = db.get("next_code_id", 1)
                    db["next_code_id"] = new_code_id + 1
                    db.setdefault("codes", {})[str(new_code_id)] = {
                        "user_id": adder_user_id, "date": datetime.now().isoformat(), "settled": False
                    }
                    db["users"][adder_user_id_str].setdefault("codes", []).append(new_code_id)
                    changes_made_to_db = True
                    logging.info(f"track_new_member: User {adder_user_id_str} reached {current_points} points. New code {new_code_id} generated.")
                    try:
                        await context.bot.send_message(
                            adder_user_id,
                            f"🎉 تبریک! شما به {current_points} امتیاز رسیدید و یک کد جایزه جدید دریافت کردید!\n"
                            f"شماره کد جایزه شما: `{new_code_id}`\n"
                            "می‌توانید از بخش 'کدهای من' آن را مشاهده و برای تسویه اقدام کنید.",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except Exception as e:
                        logging.warning(f"track_new_member: Failed to notify user {adder_user_id} about new code {new_code_id}: {e}")
            else:
                logging.info(f"track_new_member: Adder {adder_user_id} is not registered in the bot. No points awarded for adding {new_member_id_str}.")
        else:
            logging.info(f"track_new_member: Member {new_member_id_str} was already in unique_members. No points for this addition.")

        if new_member_id_str not in group_members_list:
            group_members_list.append(new_member_id_str)
            newly_added_to_group_db = True # This specific flag is for group's local list
            changes_made_to_db = True


    if newly_added_to_group_db: # Only update if group member list changed
        if group_id_str in db.get("groups", {}):
             db["groups"][group_id_str]["members"] = group_members_list
        else:
             db.setdefault("groups", {})[group_id_str] = {"title": chat_title, "members": group_members_list}
        logging.info(f"track_new_member: Updated member list for group {group_id_str}.")

    if changes_made_to_db:
        save_db(db)
        if points_awarded_this_event > 0:
             logging.info(f"track_new_member: Finished processing. User {adder_user_id} received a total of {points_awarded_this_event} points in this event for group {chat_id}.")


async def track_left_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.left_chat_member:
        return

    db = load_db()
    group_id_str = str(update.effective_chat.id)
    left_member = update.message.left_chat_member

    if left_member.is_bot and left_member.id == context.bot.id:
        if group_id_str in db.get("groups", {}):
            del db["groups"][group_id_str]
            save_db(db)
            logging.info(f"track_left_member: Bot itself left/was kicked from group {group_id_str}. Removed from db['groups'].")
        return

    left_member_id_str = str(left_member.id)
    if group_id_str in db.get("groups", {}) and "members" in db["groups"][group_id_str]:
        if left_member_id_str in db["groups"][group_id_str]["members"]:
            db["groups"][group_id_str]["members"].remove(left_member_id_str)
            save_db(db)
            logging.info(f"track_left_member: Member {left_member_id_str} removed from local member list of group {group_id_str}.")
        else:
            logging.info(f"track_left_member: Member {left_member_id_str} left group {group_id_str}, but was not in local member list.")
    else:
        logging.info(f"track_left_member: Group {group_id_str} not in db or has no member list. Cannot remove left member {left_member_id_str}.")


# --- Admin Settlement Photo Handling ---
async def handle_admin_settlement_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settlement_id = context.user_data.get('settlement_id_for_receipt_conv')
    original_message_id = context.user_data.get('original_settlement_message_id_conv')
    admin_chat_id = update.effective_chat.id

    if not settlement_id:
        await update.message.reply_text("خطا: اطلاعات تسویه برای پردازش فیش یافت نشد. لطفا دوباره از لیست درخواست‌ها انتخاب کنید.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    photo_file = update.message.photo[-1] if update.message.photo else None
    document_file = update.message.document if update.message.document else None

    file_id_to_log = None; file_type_display = "فایل نامشخص"
    receipt_file_data = {}

    if photo_file:
        file_id_to_log = photo_file.file_id
        file_type_display = "عکس فیش"
        receipt_file_data = {"type": "photo", "file_id": file_id_to_log, "file_unique_id": photo_file.file_unique_id}
    elif document_file:
        file_id_to_log = document_file.file_id
        file_type_display = f"فایل ({document_file.mime_type or 'نوع نامشخص'})" # Corrected typo
        receipt_file_data = {"type": "document", "file_id": file_id_to_log, "file_unique_id": document_file.file_unique_id, "mime_type": document_file.mime_type, "file_name": document_file.file_name}


    if not file_id_to_log:
        await update.message.reply_text("لطفا یک عکس یا فایل معتبر برای فیش واریزی ارسال کنید. در غیر اینصورت، عملیات را لغو کنید.", reply_markup=ReplyKeyboardMarkup([["لغو ارسال فیش"]], resize_keyboard=True, one_time_keyboard=True))
        return ADMIN_AWAITING_SETTLEMENT_RECEIPT_STATE

    logging.info(f"Admin {update.effective_user.id} submitted receipt ({file_type_display}, FileID: {file_id_to_log}) for settlement ID: {settlement_id}")

    db = load_db()
    if settlement_id in db.get("settlements", {}):
        db["settlements"][settlement_id]["receipt_info"] = receipt_file_data
        db["settlements"][settlement_id]["receipt_submission_date"] = datetime.now().isoformat()
        save_db(db)
    else:
        await update.message.reply_text("خطای بحرانی: درخواست تسویه در دیتابیس یافت نشد. با توسعه‌دهنده تماس بگیرید.", reply_markup=get_admin_keyboard())
        context.user_data.clear()
        return ConversationHandler.END

    settlement_info = db.get("settlements", {}).get(settlement_id)
    requesting_user_id_str = str(settlement_info.get("user_id"))
    requesting_user_info = db.get("users", {}).get(requesting_user_id_str, {})

    text = (
        f"💳 **بررسی درخواست تسویه (فیش واریزی دریافت شد)** 💳\n\n"
        f"کد جایزه: `{settlement_info.get('code_id')}`\n"
        f"کاربر درخواست دهنده: {requesting_user_info.get('name', 'نامشخص')} (ID: `{requesting_user_id_str}`)\n"
        f"یوزرنیم تلگرام: @{requesting_user_info.get('username', 'ندارد')}\n"
        f"نوع فیش ارسالی: {file_type_display}\n\n"
        f"**اطلاعات بانکی کاربر جهت تطابق:**\n"
        f"شماره تماس: `{requesting_user_info.get('phone', 'ثبت نشده')}`\n"
        f"شماره کارت: `{requesting_user_info.get('card', 'ثبت نشده')}`\n"
        f"شماره شبا (بدون IR): `{requesting_user_info.get('sheba', 'ثبت نشده')}`\n"
        f"نام بانک: {requesting_user_info.get('bank', 'ثبت نشده')}\n\n"
        f"لطفا پس از بررسی فیش و اطلاعات، وضعیت تسویه را مشخص کنید:"
    )

    settlement_actions_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید و علامت‌گذاری به عنوان تسویه شده", callback_data=f"settle_approve_{settlement_id}")],
        [InlineKeyboardButton("❌ رد کردن این درخواست تسویه", callback_data=f"settle_reject_{settlement_id}")],
        [InlineKeyboardButton("بازگشت (بدون تغییر و لغو)", callback_data="admin_settle_cancel_final_view")]
    ])

    try:
        if original_message_id:
            await context.bot.edit_message_text(chat_id=admin_chat_id, message_id=original_message_id, text=text, reply_markup=settlement_actions_keyboard, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(text, reply_markup=settlement_actions_keyboard, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logging.error(f"Error updating/sending message after receipt for settlement {settlement_id}: {e}", exc_info=True)
        await update.message.reply_text(text, reply_markup=settlement_actions_keyboard, parse_mode=ParseMode.MARKDOWN)

    context.user_data.pop('settlement_id_for_receipt_conv', None)
    context.user_data.pop('original_settlement_message_id_conv', None)
    return ConversationHandler.END

async def cancel_settlement_receipt_stage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ارسال فیش واریزی لغو شد. برای پردازش مجدد، از لیست درخواست‌های تسویه انتخاب کنید.", reply_markup=get_admin_keyboard())
    context.user_data.pop('settlement_id_for_receipt_conv', None)
    context.user_data.pop('original_settlement_message_id_conv', None)
    return ConversationHandler.END

# --- Callback Query Handlers ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    user_id_str = str(user_id)
    db = load_db()

    if data == "check_membership":
        if await check_channel_membership(update, context):
            await query.edit_message_text("✅ عضویت شما در کانال تایید شد! حالا می‌توانید مراحل ثبت نام را با ارسال /start ادامه دهید یا اگر در مراحل ثبت نام بودید، اطلاعات بعدی را ارسال کنید.")
        else:
            await query.answer("❌ شما هنوز در کانال عضو نشده‌اید. لطفا ابتدا عضو شوید و سپس دکمه '✅ عضو شدم' را بزنید.", show_alert=True)
        return

    elif data == "phone_guide":
        await query.message.reply_text(
            "راهنمای ارسال شماره تماس:\n"
            "1. در پایین صفحه چت، روی دکمه مربعی شکل با چهار نقطه (یا آیکون سنجاقک) ضربه بزنید.\n"
            "2. گزینه 'Contact' یا 'مخاطب' را انتخاب کنید.\n"
            "3. شماره خودتان (My Number / شماره من) را انتخاب و ارسال کنید.\n\n"
            "روش جایگزین:\n"
            "روی دکمه 'ارسال شماره تماس 📱' که ربات نمایش داده کلیک کنید. تلگرام از شما برای اشتراک‌گذاری شماره سوال می‌کند؛ آن را تایید کنید.\n\n"
            "اگر هیچ‌کدام از این گزینه‌ها کار نکرد، می‌توانید شماره خود را به صورت دستی تایپ و ارسال کنید (مثال: +989123456789)."
        )
        return
    elif data == "manual_phone_entry":
        # This callback now implies the user is in the WAITING_PHONE state of registration.
        # The message for manual entry is now part of the initial /start message.
        # We can simply prompt again or rely on the user to type.
        await query.message.reply_text("لطفا شماره تماس خود را به صورت دستی و با کد کشور ارسال کنید (مثال: +989123456789):")
        # No return WAITING_PHONE here, as this is a callback, not a conversation handler state return.
        return

    elif data.startswith("settle_") and not data.startswith("settle_approve_") and not data.startswith("settle_reject_") and not data.startswith("settle_admin_"):
        code_id_to_settle = data.split("settle_")[1]
        user_data = db.get("users", {}).get(user_id_str)

        if not user_data or not user_data.get("registered"):
            await query.edit_message_text("❌ برای درخواست تسویه، ابتدا باید از طریق /start ثبت نام کنید.")
            return

        all_codes_db = db.get("codes", {})
        code_info = all_codes_db.get(str(code_id_to_settle))

        if not code_info or str(code_info.get("user_id")) != user_id_str:
            await query.edit_message_text(f"❌ کد جایزه شماره `{code_id_to_settle}` متعلق به شما نیست یا یافت نشد.", parse_mode=ParseMode.MARKDOWN)
            return
        if code_info.get("settled"):
            await query.edit_message_text(f"❌ کد جایزه شماره `{code_id_to_settle}` قبلاً تسویه شده است.", parse_mode=ParseMode.MARKDOWN)
            return

        for settlement_id_existing, settlement_data_existing in db.get("settlements", {}).items():
            if str(settlement_data_existing.get("code_id")) == str(code_id_to_settle) and \
               str(settlement_data_existing.get("user_id")) == user_id_str and \
               settlement_data_existing.get("status") == "pending":
                await query.edit_message_text(f"⚠️ شما قبلاً برای کد جایزه شماره `{code_id_to_settle}` یک درخواست تسویه فعال ثبت کرده‌اید. لطفاً منتظر بررسی ادمین بمانید.", parse_mode=ParseMode.MARKDOWN)
                return

        settlement_id_new = f"{user_id_str}_{code_id_to_settle}_{int(datetime.now().timestamp())}"
        db.setdefault("settlements", {})[settlement_id_new] = {
            "user_id": user_id, "code_id": code_id_to_settle,
            "date": datetime.now().isoformat(), "status": "pending",
            "receipt_info": None
        }
        save_db(db)

        await query.edit_message_text(f"✅ درخواست تسویه شما برای کد جایزه شماره `{code_id_to_settle}` با موفقیت ثبت شد. نتیجه بررسی توسط ادمین از طریق همین ربات به شما اطلاع داده خواهد شد.", parse_mode=ParseMode.MARKDOWN)

        admins_to_notify = db.get("admins", [])
        admin_notification_text = (
            f"🔔 **درخواست تسویه حساب جدید دریافت شد!** 🔔\n\n"
            f"کد جایزه: `{code_id_to_settle}`\n"
            f"از طرف کاربر: {user_data.get('name', 'نامشخص')} (ID: `{user_id_str}`)\n"
            f"یوزرنیم تلگرام: @{user_data.get('username', 'ندارد')}\n"
            f"شماره تماس کاربر: `{user_data.get('phone', 'ثبت نشده')}`\n\n"
            f"برای بررسی و پردازش، به پنل ادمین، بخش مدیریت درخواست‌های تسویه مراجعه کنید."
        )
        for admin_id_val in admins_to_notify:
            try:
                await context.bot.send_message(admin_id_val, admin_notification_text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logging.warning(f"Failed to notify admin {admin_id_val} about new settlement request for code {code_id_to_settle}: {e}")
        return

    elif data == "cancel_settlement_selection":
        await query.edit_message_text("انتخاب کد برای تسویه لغو شد. برای تلاش مجدد، از منوی اصلی اقدام کنید.")
        return

    elif data.startswith("settle_approve_") or data.startswith("settle_reject_"):
        if user_id not in db.get("admins", []):
            await query.answer("❌ شما اجازه انجام این عملیات را ندارید.", show_alert=True)
            return

        action_type = "approve" if data.startswith("settle_approve_") else "reject"
        settlement_id_to_act = data.split("_", 2)[2]
        settlement_info = db.get("settlements", {}).get(settlement_id_to_act)

        if not settlement_info:
            await query.edit_message_text("❌ این درخواست تسویه یافت نشد. ممکن است قبلاً پردازش یا حذف شده باشد.")
            return
        if settlement_info.get("status") != "pending": # Or "awaiting_receipt" if you had such a state
            await query.edit_message_text(f"⚠️ این درخواست تسویه قبلاً در وضعیت '{settlement_info.get('status')}' بوده و نمی‌تواند مجدداً پردازش شود. وضعیت فعلی: {settlement_info.get('status')}.")
            return

        requesting_user_id = settlement_info.get("user_id")
        code_id_affected = str(settlement_info.get("code_id"))

        if action_type == "approve":
            # Ensure there's receipt info before approving, if it's mandatory
            if not settlement_info.get("receipt_info"):
                await query.edit_message_text("❌ خطا: فیش واریزی برای این تسویه ثبت نشده است. لطفاً ابتدا فیش را ارسال و سپس تایید کنید.")
                # Potentially resend the original settlement detail message if needed
                # This state implies the admin might have clicked approve on the *initial* detail message, not the one after receipt submission.
                # It's better if "approve" is only available after receipt is logged.
                # For now, we just block.
                return


            db["settlements"][settlement_id_to_act]["status"] = "completed"
            db["settlements"][settlement_id_to_act]["completed_date"] = datetime.now().isoformat()
            db["settlements"][settlement_id_to_act]["processed_by"] = user_id
            if code_id_affected in db.get("codes", {}):
                db["codes"][code_id_affected]["settled"] = True
            else:
                logging.error(f"Code {code_id_affected} not found in codes DB during settlement approval for {settlement_id_to_act}")

            save_db(db)
            await query.edit_message_text(f"✅ درخواست تسویه برای کد `{code_id_affected}` با موفقیت **تایید شد** و به عنوان 'تسویه شده' علامت‌گذاری گردید.", parse_mode=ParseMode.MARKDOWN)

            try:
                receipt_info = settlement_info.get("receipt_info")
                approval_caption = (
                    f"🎉 خبر خوب! درخواست تسویه شما برای کد جایزه شماره `{code_id_affected}` **تأیید شد**.\n"
                    "مبلغ مربوطه واریز گردید. فیش پیوست را مشاهده کنید."
                )
                fallback_message = (
                     f"🎉 خبر خوب! درخواست تسویه شما برای کد جایزه شماره `{code_id_affected}` **تأیید شد**.\n"
                     "مبلغ مربوطه واریز شد."
                )

                if receipt_info and receipt_info.get("file_id"):
                    file_id = receipt_info.get("file_id")
                    file_type = receipt_info.get("type")

                    if file_type == "photo":
                        await context.bot.send_photo(
                            chat_id=requesting_user_id,
                            photo=file_id,
                            caption=approval_caption,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    elif file_type == "document":
                        await context.bot.send_document(
                            chat_id=requesting_user_id,
                            document=file_id,
                            caption=approval_caption,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    else:
                         await context.bot.send_message(
                            requesting_user_id,
                            fallback_message + " (فیش پیوست نشد)",
                            parse_mode=ParseMode.MARKDOWN
                        )
                else:
                    logging.warning(f"Approving settlement {settlement_id_to_act} for user {requesting_user_id} WITHOUT a receipt_info file_id, though receipt_info might exist: {receipt_info}")
                    await context.bot.send_message(
                        requesting_user_id,
                        fallback_message,
                        parse_mode=ParseMode.MARKDOWN
                    )
            except Exception as e:
                logging.warning(f"Failed to notify user {requesting_user_id} about settlement approval for code {code_id_affected}: {e}")


        elif action_type == "reject":
            db["settlements"][settlement_id_to_act]["status"] = "rejected"
            db["settlements"][settlement_id_to_act]["rejected_date"] = datetime.now().isoformat()
            db["settlements"][settlement_id_to_act]["processed_by"] = user_id
            save_db(db)
            await query.edit_message_text(f"❌ درخواست تسویه برای کد `{code_id_affected}` **رد شد**.", parse_mode=ParseMode.MARKDOWN)
            try:
                await context.bot.send_message(
                    requesting_user_id,
                    f"⚠️ متاسفانه درخواست تسویه شما برای کد جایزه شماره `{code_id_affected}` توسط ادمین **رد شد**.\n"
                    "در صورت داشتن سوال یا اعتراض، لطفاً از طریق بخش پشتیبانی با ما تماس بگیرید.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logging.warning(f"Failed to notify user {requesting_user_id} about settlement rejection for code {code_id_affected}: {e}")
        return

    elif data == "admin_settle_cancel_receipt_stage": # Callback from InlineKeyboard in admin_settle_...
        # This means admin clicked "لغو ارسال فیش و بازگشت"
        await query.edit_message_text("ارسال فیش واریزی و پردازش این تسویه لغو شد. برای مشاهده لیست، مجدداً گزینه مربوطه را از منوی ادمین انتخاب کنید.")
        # Clear context data related to this specific settlement processing
        context.user_data.pop('settlement_id_for_receipt_conv', None)
        context.user_data.pop('original_settlement_message_id_conv', None)
        # No ConversationHandler.END needed here as this callback is part of the admin_settlement_processing_conv
        # and this action effectively ends the current interaction for this settlement,
        # allowing the admin to pick another or do something else.
        return

    elif data == "admin_settle_cancel_final_view":
        await query.edit_message_text("عملیات تسویه برای این مورد لغو شد و به حالت قبل بازگشت. درخواست همچنان در وضعیت قبلی خود باقی می‌ماند.")
        return

    elif data.startswith("del_promo_link_"):
        if user_id not in db.get("admins", []):
            await query.answer("❌ شما اجازه انجام این عملیات را ندارید.", show_alert=True)
            return
        try:
            link_index_to_remove = int(data.split("del_promo_link_")[1])
            if 0 <= link_index_to_remove < len(db.get("promotional_links", [])):
                removed_link = db["promotional_links"].pop(link_index_to_remove)
                save_db(db)
                await query.edit_message_text(f"✅ لینک '{removed_link}' با موفقیت از لیست حذف شد.")
                # To refresh the list of links to delete, the admin would click "حذف لینک ❌" again.
            else:
                await query.answer("❌ شماره لینک نامعتبر است.", show_alert=True)
                await query.edit_message_text("خطا در حذف لینک. لیست ممکن است تغییر کرده باشد. دوباره امتحان کنید.") # Refresh state
        except (ValueError, IndexError) as e:
            await query.answer("❌ خطایی در پردازش حذف لینک رخ داد.", show_alert=True)
            logging.error(f"Error processing del_promo_link callback data '{data}': {e}")
            await query.edit_message_text("خطا در پردازش. دوباره امتحان کنید.")
        return

    elif data == "cancel_del_promo_link":
        await query.edit_message_text("عملیات حذف لینک لغو شد.")
        return

    elif data.startswith("del_admin_"):
        if user_id not in db.get("admins", []):
            await query.answer("❌ شما اجازه انجام این عملیات را ندارید.", show_alert=True)
            return
        if user_id != ADMIN_ID: # Only main admin can delete other admins
            await query.answer("❌ فقط ادمین اصلی می‌تواند سایر ادمین‌ها را حذف کند.", show_alert=True)
            return

        try:
            admin_id_to_delete = int(data.split("del_admin_")[1])
            if admin_id_to_delete == ADMIN_ID:
                await query.answer("❌ ادمین اصلی قابل حذف نیست.", show_alert=True)
                return
            current_admins = db.get("admins", [])
            if admin_id_to_delete in current_admins:
                current_admins.remove(admin_id_to_delete)
                db["admins"] = current_admins # Ensure the list is updated back
                save_db(db)
                await query.edit_message_text(f"✅ ادمین با شناسه `{admin_id_to_delete}` با موفقیت حذف شد.")
            else:
                await query.answer(f"❌ ادمین با شناسه {admin_id_to_delete} یافت نشد یا قبلا حذف شده.", show_alert=True)
                await query.edit_message_text("خطا: ادمین یافت نشد. لیست ممکن است تغییر کرده باشد.")
        except (ValueError, IndexError) as e:
            await query.answer("❌ خطایی در پردازش حذف ادمین رخ داد.", show_alert=True)
            logging.error(f"Error processing del_admin_ callback data '{data}': {e}")
            await query.edit_message_text("خطا در پردازش. دوباره امتحان کنید.")
        return

    elif data == "cancel_del_admin":
        await query.edit_message_text("عملیات حذف ادمین لغو شد.")
        return

    if data.startswith("admin_ticket_"): # This starts the ADMIN_SUPPORT_REPLY_STATE conversation
        if user_id not in db.get("admins", []):
            await query.answer("❌ شما اجازه این کار را ندارید.", show_alert=True)
            # Do not return ConversationHandler.END here as this CBQ might be the entry point
            return

        ticket_id_to_view = data.split("admin_ticket_")[1]
        ticket_info = db.get("support_tickets", {}).get(ticket_id_to_view)

        if not ticket_info or ticket_info.get("status") != "open":
            await query.edit_message_text("❌ این تیکت دیگر باز نیست یا یافت نشد.")
            # Do not return ConversationHandler.END here if this CBQ is an entry point.
            # If it's an entry point, it should return the first state of the conversation.
            # The admin_support_reply_conv handles this logic.
            return

        requesting_user_id_str_val = str(ticket_info.get("user_id"))
        requesting_user_info_val = db.get("users", {}).get(requesting_user_id_str_val, {})
        ticket_date_val_str = "نامشخص"
        if ticket_info.get("date"):
            try: ticket_date_val_str = datetime.fromisoformat(ticket_info.get("date")).strftime('%Y/%m/%d ساعت %H:%M')
            except: pass

        text_to_admin = (
            f"📮 **پاسخ به تیکت پشتیبانی شماره: {ticket_id_to_view}**\n\n"
            f"کاربر: {requesting_user_info_val.get('name', 'نامشخص')} (ID: `{requesting_user_id_str_val}`)\n"
            f"یوزرنیم: @{requesting_user_info_val.get('username', 'ندارد')}\n"
            f"شماره تماس کاربر: `{requesting_user_info_val.get('phone', 'ثبت نشده')}`\n"
            f"تاریخ ارسال تیکت: {ticket_date_val_str}\n\n"
            f"**متن پیام کاربر:**\n---\n{ticket_info.get('message', '')}\n---\n\n"
            f"✍️ لطفا پاسخ خود را برای این تیکت ارسال کنید. برای لغو، از دکمه زیر استفاده کنید."
        )
        reply_keyboard_admin = ReplyKeyboardMarkup([["انصراف از پاسخ به تیکت"]], resize_keyboard=True, one_time_keyboard=True)

        await query.edit_message_text("در حال آماده‌سازی جزئیات تیکت برای پاسخ...") # This message will be quickly replaced
        await query.message.reply_text(text_to_admin, reply_markup=reply_keyboard_admin, parse_mode=ParseMode.MARKDOWN)

        context.user_data['admin_reply_context'] = {'ticket_id': ticket_id_to_view}
        return ADMIN_SUPPORT_REPLY_STATE # This callback is an entry point to this state

    elif data.startswith("admin_settle_") and not data.startswith("admin_settle_cancel_"): # This starts ADMIN_AWAITING_SETTLEMENT_RECEIPT_STATE
        if user_id not in db.get("admins", []):
            await query.answer("شما اجازه این کار را ندارید.", show_alert=True)
            return

        settlement_id_to_process = data.split("admin_settle_")[1]
        settlement_info = db.get("settlements", {}).get(settlement_id_to_process)

        if not settlement_info or settlement_info.get("status") != "pending":
            await query.edit_message_text("❌ این درخواست تسویه دیگر در حالت انتظار نیست یا یافت نشد.")
            return

        req_user_id_str = str(settlement_info.get("user_id"))
        req_user_info = db.get("users", {}).get(req_user_id_str, {})
        settle_date_str = "نامشخص"
        if settlement_info.get("date"):
            try: settle_date_str = datetime.fromisoformat(settlement_info.get("date")).strftime('%Y/%m/%d ساعت %H:%M')
            except: pass

        text = (
            f"💳 **بررسی اولیه درخواست تسویه حساب** 💳\n\n"
            f"کد جایزه: `{settlement_info.get('code_id')}`\n"
            f"کاربر: {req_user_info.get('name', 'نامشخص')} (ID: `{req_user_id_str}`)\n"
            f"یوزرنیم: @{req_user_info.get('username', 'ندارد')}\n"
            f"تاریخ درخواست: {settle_date_str}\n\n"
            f"**اطلاعات بانکی کاربر (جهت واریز):**\n"
            f"شماره تماس: `{req_user_info.get('phone', 'ثبت نشده')}`\n"
            f"شماره کارت: `{req_user_info.get('card', 'ثبت نشده')}`\n"
            f"شماره شبا (بدون IR): `{req_user_info.get('sheba', 'ثبت نشده')}`\n"
            f"نام بانک: {req_user_info.get('bank', 'ثبت نشده')}\n\n"
            
        )
        context.user_data['settlement_id_for_receipt_conv'] = settlement_id_to_process
        context.user_data['original_settlement_message_id_conv'] = query.message.message_id

        cancel_receipt_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("لغو ارسال فیش و بازگشت", callback_data="admin_settle_cancel_receipt_stage")
        ]])

        await query.edit_message_text(
            text + "لطفا تصویر فیش واریزی مربوط به این تسویه را ارسال کنید. برای لغو این مرحله، از دکمه زیر استفاده کنید.",
            reply_markup=cancel_receipt_keyboard, # This makes it an inline button under the edited message
            parse_mode=ParseMode.MARKDOWN
        )
        # This callback is an entry point to this state
        return ADMIN_AWAITING_SETTLEMENT_RECEIPT_STATE
    return


async def admin_typed_support_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_reply_text = update.message.text
    admin_reply_ctx = context.user_data.get('admin_reply_context')

    if admin_reply_text == "انصراف از پاسخ به تیکت":
        if admin_reply_ctx: context.user_data.pop('admin_reply_context', None)
        await update.message.reply_text("پاسخ به تیکت لغو شد. بازگشت به منوی ادمین.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    if not admin_reply_ctx or 'ticket_id' not in admin_reply_ctx:
        await update.message.reply_text("خطای داخلی: اطلاعات تیکت برای ارسال پاسخ یافت نشد. لطفا دوباره از لیست تیکت‌ها انتخاب کنید.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END

    ticket_id_to_reply = admin_reply_ctx.get('ticket_id')
    db = load_db()

    if ticket_id_to_reply and str(ticket_id_to_reply) in db.get("support_tickets", {}):
        ticket_info = db["support_tickets"][str(ticket_id_to_reply)]
        if ticket_info.get("status") != "open":
            await update.message.reply_text(f"⚠️ این تیکت (شماره: {ticket_id_to_reply}) دیگر باز نیست و قبلاً پردازش شده است.", reply_markup=get_admin_keyboard())
        else:
            db["support_tickets"][str(ticket_id_to_reply)]["status"] = "closed"
            db["support_tickets"][str(ticket_id_to_reply)]["response"] = admin_reply_text
            db["support_tickets"][str(ticket_id_to_reply)]["response_date"] = datetime.now().isoformat()
            db["support_tickets"][str(ticket_id_to_reply)]["responded_by"] = update.effective_user.id
            save_db(db)
            try:
                await context.bot.send_message(
                    ticket_info.get("user_id"),
                    f"📬 پاسخ به درخواست پشتیبانی شما (شماره تیکت: `{ticket_id_to_reply}`):\n\n---\n{admin_reply_text}\n---\n\nاین تیکت اکنون بسته شده است. در صورت نیاز به پیگیری بیشتر، لطفاً یک تیکت جدید ایجاد کنید.",
                    parse_mode=ParseMode.MARKDOWN
                )
                await update.message.reply_text(f"✅ پاسخ شما برای تیکت `{ticket_id_to_reply}` با موفقیت ارسال و تیکت بسته شد.", reply_markup=get_admin_keyboard(), parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                await update.message.reply_text(f"⚠️ پاسخ ذخیره شد اما در ارسال به کاربر برای تیکت `{ticket_id_to_reply}` خطایی رخ داد: {e}. لطفاً وضعیت ارسال را بررسی کنید.", reply_markup=get_admin_keyboard(), parse_mode=ParseMode.MARKDOWN)
                logging.error(f"Failed to send support reply to user {ticket_info.get('user_id')} for ticket {ticket_id_to_reply}: {e}")
    else:
        await update.message.reply_text(f"❌ تیکت شماره `{ticket_id_to_reply}` برای پاسخ یافت نشد یا قبلاً پردازش شده است.", reply_markup=get_admin_keyboard(), parse_mode=ParseMode.MARKDOWN)

    context.user_data.pop('admin_reply_context', None)
    return ConversationHandler.END



async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private' or not update.message or not update.message.text:
        return

    text = update.message.text
    user_id = update.effective_user.id
    db = load_db()

    # User Menu Options
    if text == "امتیازات من 🏆": await show_points(update, context)
    elif text == "کد های من 🎫": await show_codes(update, context)
    elif text == "تسویه حساب 💰": await settlement_menu(update, context)
    elif text == "ارتباط با پشتیبانی 📞": await support_menu(update, context)
    elif text == "راهنما ❓": await show_help(update, context)
    elif text == "بازگشت به منو اصلی 🔙":
        await update.message.reply_text("بازگشت به منو اصلی.", reply_markup=get_main_keyboard())

    # Admin Menu Options
    elif user_id in db.get("admins", []):
        current_admin_keyboard = get_admin_keyboard()
        if text == "آمار کلی 📊": await admin_stats(update, context)
        elif text == "خروجی اکسل اعضا 📄": await export_users(update, context)
        elif text == "مدیریت درخواست های تسویه 💳": await manage_settlements(update, context)
        elif text == "مدیریت درخواست های پشتیبانی 📮": await manage_support(update, context)
        elif text == "مدیریت لینک های تبلیغاتی 🔗": await manage_promotional_links(update, context)
        elif text == "مدیریت ادمین ها 👨‍💼": await manage_admins_cmd(update, context)
        elif text == "برگشت به منو کاربران 🔙": await switch_to_user_menu(update, context)

        # Admin Sub-Menu Options (from ReplyKeyboards of sub-menus)
        elif text == "مشاهده درخواست‌های تسویه فعال 📋": await show_active_settlements(update, context)
        elif text == "مشاهده تیکت‌های پشتیبانی باز 📋": await show_active_tickets(update, context)
        elif text == "برگشت به منو ادمین 🔙":
             await update.message.reply_text("بازگشت به پنل مدیریت.", reply_markup=current_admin_keyboard)
        elif text == "لیست لینک‌های تبلیغاتی 📋": await list_promotional_links(update, context)
        # "افزودن لینک جدید ➕" is handled by add_link_conv
        elif text == "حذف لینک ❌": 
            await remove_promotional_link_start(update, context) 
        elif text == "لیست ادمین‌های ربات 👥": await list_admins(update, context) # list_admins already checks admin status
        # "افزودن ادمین جدید ➕" is handled by add_admin_conv
        elif text == "حذف ادمین ❌": 
            await remove_admin_start(update, context) # This will show inline keyboard
        # Note: If other admin buttons send text that starts a ConversationHandler,
        # those handlers (added before this generic text handler) will catch them first.
    else: # User is not admin and text didn't match user menu
        user_data = db.get("users", {}).get(str(user_id))
        if not user_data or not user_data.get("registered"):
            if update.effective_chat.type == 'private':
                pass # Avoid sending "unknown command" if user is not registered and types something other than /start
        


# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            error_message_to_user = (
                "متاسفانه مشکلی در پردازش درخواست شما پیش آمد. تیم فنی در حال بررسی است. "
                "لطفا لحظاتی دیگر دوباره تلاش کنید. اگر مشکل ادامه داشت، با ادمین تماس بگیرید.\n\n"
                f"جزئیات خطا (برای ارسال به ادمین در صورت نیاز): `{type(context.error).__name__}: {str(context.error)}`"
            )
            # Escape markdown for the error message itself if it contains special characters
            error_message_to_user = error_message_to_user.replace("`", "\\`").replace("*", "\\*").replace("_", "\\_")

            await update.effective_message.reply_text(error_message_to_user, parse_mode=ParseMode.MARKDOWN_V2 if '`' in str(context.error) else ParseMode.MARKDOWN)
        except Exception as e_send:
            logging.error(f"Failed to send user-facing error message: {e_send}")


def main():
    db = init_db()

    app_builder = Application.builder().token(BOT_TOKEN)
    app_builder.post_init(post_startup_group_check)
    app = app_builder.build()

    if app.job_queue:
        app.job_queue.run_repeating(periodic_group_check, interval=3600, first=120)
        logging.info("Periodic group check job scheduled.")
    else:
        logging.warning("Job Queue not available. Periodic tasks will not run automatically.")

    registration_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start, filters.ChatType.PRIVATE)],
        states={
            WAITING_PHONE: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE), handle_phone)],
            WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_name)],
            WAITING_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_card)],
            WAITING_SHEBA: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_sheba)],
            WAITING_BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_bank)],
        },
        fallbacks=[
            CommandHandler("start", start, filters.ChatType.PRIVATE), # Allow re-starting
            MessageHandler(filters.Regex("^انصراف از ثبت نام ❌$"), handle_bank) # Generic cancel during registration
        ], per_message=False, name="registration_conversation"
    )

    edit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^ویرایش اطلاعات ✏️$") & filters.ChatType.PRIVATE, edit_menu_start)],
        states={
            EDIT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_edit_menu_choice)],
            EDIT_PHONE: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE), handle_phone)], # Unified phone handler
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_edit_name)],
            EDIT_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_edit_card)],
            EDIT_SHEBA: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_edit_sheba)],
            EDIT_BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_edit_bank)],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^بازگشت به منو اصلی 🔙$"), lambda u,c: ConversationHandler.END), # From get_edit_keyboard()
            MessageHandler(filters.Regex("^انصراف از ویرایش 🔙$"), lambda u,c: generic_edit_handler(u,c, "اطلاعات","",False,"",EDIT_MENU)), # From reply_cancel_keyboard and edit phone keyboard
            CommandHandler("start", start, filters.ChatType.PRIVATE) # Allow escaping with /start
        ], per_message=False, name="edit_info_conversation"
    )

    support_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^ایجاد درخواست پشتیبانی جدید 📮$") & filters.ChatType.PRIVATE, create_support_ticket)],
        states={
            SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_support_message)],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^انصراف از ارسال پیام 🔙$"), lambda u,c: ConversationHandler.END),
            CommandHandler("start", start, filters.ChatType.PRIVATE) # Allow escaping
            ],
        per_message=False, name="create_support_ticket_conversation"
    )

    admin_support_reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^admin_ticket_")], # Enters via callback
        states={
            ADMIN_SUPPORT_REPLY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, admin_typed_support_reply)]
        },
        fallbacks=[
            MessageHandler(filters.Regex("^انصراف از پاسخ به تیکت$"), admin_typed_support_reply), # Text based cancel
            CommandHandler("admin", admin_panel, filters.ChatType.PRIVATE) # Escape to admin panel
            ],
        per_message=False, name="admin_support_reply_conversation"
    )

    admin_settlement_processing_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^admin_settle_")], # Enters via callback for selecting a settlement
        states={
            ADMIN_AWAITING_SETTLEMENT_RECEIPT_STATE: [ # After selecting, admin is asked for receipt
                MessageHandler(filters.PHOTO | filters.Document.ALL, handle_admin_settlement_receipt),
                CallbackQueryHandler(handle_callback, pattern="^admin_settle_cancel_receipt_stage$"), # Inline button to cancel receipt submission
                MessageHandler(filters.Regex("^لغو ارسال فیش$"), cancel_settlement_receipt_stage_cmd) # ReplyKeyboard button to cancel
            ],
        },
        fallbacks=[
            CallbackQueryHandler(handle_callback, pattern="^admin_settle_cancel_receipt_stage$"), # Fallback for the inline cancel
            CommandHandler("admin", admin_panel, filters.ChatType.PRIVATE) # Escape to admin panel
        ], per_message=False, name="admin_settlement_processing_conversation"
    )

    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^ارسال پیام همگانی 📢$") & filters.ChatType.PRIVATE & filters.User(db.get("admins", [ADMIN_ID])), broadcast_message_start)],
        states={ ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_broadcast)] },
        fallbacks=[
            MessageHandler(filters.Regex("^انصراف از ارسال همگانی 🔙$"), lambda u,c: ConversationHandler.END),
            CommandHandler("admin", admin_panel, filters.ChatType.PRIVATE)
            ],
        per_message=False, name="broadcast_conversation"
    )

    add_link_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن لینک جدید ➕$") & filters.ChatType.PRIVATE & filters.User(db.get("admins", [ADMIN_ID])), add_promotional_link_start)],
        states={ ADMIN_ADD_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_add_link)] },
        fallbacks=[
            MessageHandler(filters.Regex("^انصراف و بازگشت به مدیریت لینک‌ها 🔙$"), lambda u,c: ConversationHandler.END),
            CommandHandler("admin", admin_panel, filters.ChatType.PRIVATE)
            ],
        per_message=False, name="add_promo_link_conversation"
    )

    add_admin_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن ادمین جدید ➕$") & filters.ChatType.PRIVATE & filters.User(db.get("admins", [ADMIN_ID])), add_admin_start)],
        states={ ADMIN_ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_add_admin)] },
        fallbacks=[
            MessageHandler(filters.Regex("^انصراف و بازگشت به مدیریت ادمین‌ها 🔙$"), lambda u,c: ConversationHandler.END),
            CommandHandler("admin", admin_panel, filters.ChatType.PRIVATE)
            ],
        per_message=False, name="add_admin_conversation"
    )

    # Add conversation handlers first, as they are more specific.
    app.add_handler(registration_conv)
    app.add_handler(edit_conv)
    app.add_handler(support_conv)
    app.add_handler(admin_support_reply_conv)
    app.add_handler(admin_settlement_processing_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(add_link_conv)
    app.add_handler(add_admin_conv)

    # Command Handlers (general commands)
    app.add_handler(CommandHandler("admin", admin_panel, filters.ChatType.PRIVATE))

    # Callback Query Handler (for inline buttons not part of conversations or acting as entry points)
    app.add_handler(CallbackQueryHandler(handle_callback)) # This will catch callbacks not handled by conversations

    # Chat Member Handlers
    app.add_handler(ChatMemberHandler(unified_bot_status_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS & filters.ChatType.GROUPS, track_new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER & filters.ChatType.GROUPS, track_left_member))

    # Generic Text Handler (must be one of the last for private chats to catch menu buttons)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_text))

    # Error Handler (should be last)
    app.add_error_handler(error_handler)

    logging.info("Bot starting to poll...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)


if __name__ == "__main__":
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s',
        level=logging.INFO,
        handlers=[
            logging.FileHandler("bot.log", encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.INFO)

    main()