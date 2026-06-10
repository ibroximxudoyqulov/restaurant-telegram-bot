import os
import re
import random
import sqlite3
import string
import time
import math
import calendar
import threading
from datetime import datetime
import telebot
from telebot import types

# ============================================================
#  ⚙️  АСОСИЙ СОЗЛАМАЛАР — СОТИШДА БУ ЕРНИ ЎЗГАРТИРАСАН
# ============================================================
TOKEN    = os.environ.get("BOT_TOKEN", "8843528675:AAFIEZtTMA4u2Ui_TYSumpy2mwvhW3V6Ws1U")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

bot     = telebot.TeleBot(TOKEN)
DB_NAME = "restaurant.db"

RESTAURANT_LAT = 38.5642
RESTAURANT_LON = 68.7610

OPEN_HOUR      = 8
CLOSE_HOUR     = 23
SESSION_TIMEOUT = 600  # 10 дақиқа

# Тил файллари
LANGS = {
    "tj": {
        "welcome":        "🌟 *Хуш омадед, {name}!*\nХизматрасониро интихоб кунед 👇",
        "choose_lang":    "🌐 Забонро интихоб кунед / Tilni tanlang:",
        "menu_title":     "📋 *Категорияро интихоб кунед:*",
        "cart_title":     "🛒 *Сабади харидии шумо:*",
        "cart_empty":     "🛒 Сабади харид холӣ аст.",
        "order_done":     "✅ *Фармоиш қабул шуд!*\n🆔 Код: `{code}`\n💰 Жами: {total:.2f} смн",
        "booking_done":   "✅ *Стол бронланди!*\n📅 {date} соат {time}\n👥 {guests} нафар",
        "closed":         "🔒 *Ресторан ёпиқ!*\nИш вақти: {open}:00 — {close}:00",
        "session_expired":"⏱️ Сессия тугади. Сабад тозаланди. /start босинг.",
        "outside_city":   "❌ Шумо Душанбе ҳудудидан ташқаридасиз!",
        "not_in_rest":    "❌ Шумо ресторанда эмассиз! Масофа: {dist:.0f}м",
        "phone_request":  "📱 Телефонингизни тасдиқланг:",
        "guests_ask":     "👥 Неча нафар меҳмон?",
        "day_ask":        "📅 Кунни киритинг (масалан: 15):",
        "month_ask":      "🗓️ Ойни рақамда киритинг (6 = июнь):",
        "time_ask":       "⏱️ Вақтни киритинг (масалан: 18:00):",
        "service_ask":    "Хизмат турини танланг:",
        "delivery":       "🛵 Доставка",
        "dine_in":        "🍽️ Ресторанда",
        "btn_menu":       "📋 Меню",
        "btn_cart":       "🛒 Сабад",
        "btn_book":       "📅 Стол брон",
        "btn_profile":    "👤 Профил",
        "btn_lang":       "🌐 Забон",
        "btn_admin":      "👑 Админ",
        "status_new":     "🆕 Янги",
        "status_cooking": "👨‍🍳 Тайёрланмоқда",
        "status_ready":   "✅ Тайёр",
        "status_deliver": "🛵 Йўлда",
        "status_done":    "✔️ Етиб борди",
    },
    "uz": {
        "welcome":        "🌟 *Xush kelibsiz, {name}!*\nXizmat turini tanlang 👇",
        "choose_lang":    "🌐 Забонро интихоб кунед / Tilni tanlang:",
        "menu_title":     "📋 *Kategoriyani tanlang:*",
        "cart_title":     "🛒 *Savatingiz:*",
        "cart_empty":     "🛒 Savat bo'sh.",
        "order_done":     "✅ *Buyurtma qabul qilindi!*\n🆔 Kod: `{code}`\n💰 Jami: {total:.2f} so'm",
        "booking_done":   "✅ *Stol band qilindi!*\n📅 {date} soat {time}\n👥 {guests} kishi",
        "closed":         "🔒 *Restoran yopiq!*\nIsh vaqti: {open}:00 — {close}:00",
        "session_expired":"⏱️ Sessiya tugadi. Savat tozalandi. /start bosing.",
        "outside_city":   "❌ Siz Dushanbe hududidan tashqaridasiz!",
        "not_in_rest":    "❌ Siz restoranda emassiz! Masofa: {dist:.0f}m",
        "phone_request":  "📱 Telefon raqamingizni tasdiqlang:",
        "guests_ask":     "👥 Necha nafar mehmon?",
        "day_ask":        "📅 Kunni kiriting (masalan: 15):",
        "month_ask":      "🗓️ Oyni raqamda kiriting (6 = iyun):",
        "time_ask":       "⏱️ Vaqtni kiriting (masalan: 18:00):",
        "service_ask":    "Xizmat turini tanlang:",
        "delivery":       "🛵 Yetkazib berish",
        "dine_in":        "🍽️ Restoranda",
        "btn_menu":       "📋 Menyu",
        "btn_cart":       "🛒 Savat",
        "btn_book":       "📅 Stol band",
        "btn_profile":    "👤 Profil",
        "btn_lang":       "🌐 Til",
        "btn_admin":      "👑 Admin",
        "status_new":     "🆕 Yangi",
        "status_cooking": "👨‍🍳 Tayyorlanmoqda",
        "status_ready":   "✅ Tayyor",
        "status_deliver": "🛵 Yo'lda",
        "status_done":    "✔️ Yetib bordi",
    }
}

CATEGORIES = [
    "🍲 Таомҳои миллии гарм",
    "🍢 Кабобҳо",
    "🥗 Хӯришҳо ва Газакҳо",
    "🥤 Нӯшокиҳои миллӣ",
    "🍰 Десертҳо ва Ширинлиҳо",
]

# ============================================================
#  🗄️  DATABASE
# ============================================================
def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, phone TEXT,
        last_activity INTEGER DEFAULT 0, lang TEXT DEFAULT 'tj'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS menu (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL, price REAL NOT NULL,
        category TEXT NOT NULL, image_id TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS cart (
        user_id INTEGER, food TEXT, qty INTEGER DEFAULT 1, price REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, guests INTEGER,
        booking_date TEXT, time_slot TEXT,
        phone TEXT, status TEXT DEFAULT 'Интизор 🟡'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        code TEXT PRIMARY KEY, user_id INTEGER,
        receiver_id INTEGER, type TEXT, details TEXT,
        total REAL, status TEXT DEFAULT 'Янги 🆕',
        date_time TEXT
    )""")
    c.execute("SELECT COUNT(*) FROM menu")
    if c.fetchone()[0] == 0:
        default_menu = [
            ("Оши палови тоҷикӣ", 40.0, "🍲 Таомҳои миллии гарм", None),
            ("Шӯрбои гӯсфандӣ",   35.0, "🍲 Таомҳои миллии гарм", None),
            ("Қорутоб",           45.0, "🍲 Таомҳои миллии гарм", None),
            ("Сихкабоби говӣ",    25.0, "🍢 Кабобҳо",             None),
            ("Хӯриши Шакароб",    15.0, "🥗 Хӯришҳо ва Газакҳо", None),
            ("Чои кабуд бо лимӯ",  5.0, "🥤 Нӯшокиҳои миллӣ",   None),
        ]
        c.executemany("INSERT INTO menu (name,price,category,image_id) VALUES(?,?,?,?)", default_menu)
    conn.commit()
    conn.close()

init_db()

# ============================================================
#  📦  STATE
# ============================================================
pending_orders = {}
admin_state    = {}
booking_state  = {}
order_mode     = {}
service_type   = {}

# ============================================================
#  🛠️  HELPERS
# ============================================================
def get_lang(uid: int) -> str:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT lang FROM users WHERE id=?", (uid,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else "tj"

def t(uid: int, key: str, **kwargs) -> str:
    lang = get_lang(uid)
    text = LANGS.get(lang, LANGS["tj"]).get(key, key)
    return text.format(**kwargs) if kwargs else text

def is_open() -> bool:
    return OPEN_HOUR <= datetime.now().hour < CLOSE_HOUR

def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def in_dushanbe(lat, lon) -> bool:
    return 38.48 <= lat <= 38.65 and 68.68 <= lon <= 68.90

def gen_code(n=6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))

def valid_time(t_str: str) -> bool:
    return bool(re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", t_str.strip()))

def ensure_user(uid: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (id, last_activity, lang) VALUES (?,?,?)",
              (uid, int(time.time()), "tj"))
    conn.commit()
    conn.close()

def check_session(uid: int) -> bool:
    ensure_user(uid)
    now = int(time.time())
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT last_activity FROM users WHERE id=?", (uid,))
    row = c.fetchone()
    if row and now - row[0] > SESSION_TIMEOUT:
        c.execute("DELETE FROM cart WHERE user_id=?", (uid,))
        c.execute("UPDATE users SET last_activity=? WHERE id=?", (now, uid))
        conn.commit()
        conn.close()
        bot.send_message(uid, t(uid, "session_expired"), reply_markup=main_kb(uid))
        return False
    c.execute("UPDATE users SET last_activity=? WHERE id=?", (now, uid))
    conn.commit()
    conn.close()
    return True

def clear_state(uid: int):
    for d in (order_mode, service_type, booking_state, pending_orders):
        d.pop(uid, None)

# ============================================================
#  ⌨️  KEYBOARDS
# ============================================================
def main_kb(uid: int):
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(t(uid,"btn_menu"), t(uid,"btn_cart"))
    m.add(t(uid,"btn_book"), t(uid,"btn_profile"))
    m.add(t(uid,"btn_lang"), t(uid,"btn_admin"))
    return m

def admin_kb():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add("📊 Статистика",    "📦 Фармоишлар")
    m.add("📅 Бронлар",       "➕ Таом қўшиш")
    m.add("🗑️ Таом ўчириш",   "📨 Статус ўзгартириш")
    m.add("⬅️ Орқага")
    return m

# ============================================================
#  /start — ТИЛ ТАНЛАШ
# ============================================================
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.chat.id
    clear_state(uid)
    admin_state.pop(ADMIN_ID, None)
    ensure_user(uid)
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM cart WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()

    # Тил танлаш клавиатураси
    mk = types.InlineKeyboardMarkup()
    mk.add(
        types.InlineKeyboardButton("🇹🇯 Тоҷикӣ",  callback_data="lang_tj"),
        types.InlineKeyboardButton("🇺🇿 O'zbek",   callback_data="lang_uz"),
    )
    bot.send_message(uid, LANGS["tj"]["choose_lang"], reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("lang_"))
def cb_lang(call):
    uid  = call.message.chat.id
    lang = call.data.split("_")[1]
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET lang=? WHERE id=?", (lang, uid))
    conn.commit()
    conn.close()
    try:
        bot.delete_message(uid, call.message.message_id)
    except:
        pass
    name = call.from_user.first_name or "дӯст"
    bot.send_message(uid, t(uid,"welcome", name=name),
                     parse_mode="Markdown", reply_markup=main_kb(uid))

# ============================================================
#  🌐  ТИЛ АЛМАШТИРИШ
# ============================================================
def is_lang_btn(msg):
    return msg.text in ("🌐 Забон", "🌐 Til")

@bot.message_handler(func=is_lang_btn)
def change_lang(msg):
    uid = msg.chat.id
    mk = types.InlineKeyboardMarkup()
    mk.add(
        types.InlineKeyboardButton("🇹🇯 Тоҷикӣ", callback_data="lang_tj"),
        types.InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="lang_uz"),
    )
    bot.send_message(uid, LANGS["tj"]["choose_lang"], reply_markup=mk)

# ============================================================
#  👑  ADMIN PANEL
# ============================================================
ADMIN_BTNS = {
    "👑 Админ", "👑 Admin",
    "📊 Статистика", "📦 Фармоишлар",
    "📅 Бронлар", "➕ Таом қўшиш",
    "🗑️ Таом ўчириш", "📨 Статус ўзгартириш",
}

@bot.message_handler(func=lambda m: m.text in ADMIN_BTNS)
def admin_router(msg):
    uid = msg.chat.id
    if uid != ADMIN_ID:
        bot.send_message(uid, "❌ Фақат Admin!", reply_markup=main_kb(uid))
        return
    txt = msg.text

    if txt in ("👑 Админ", "👑 Admin"):
        bot.send_message(ADMIN_ID, "👑 Admin panel:", reply_markup=admin_kb())

    elif txt == "📊 Статистика":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders")
        cnt, earned = c.fetchone()
        c.execute("SELECT COUNT(*) FROM orders WHERE DATE(date_time)=DATE('now')")
        today = c.fetchone()[0]
        c.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE DATE(date_time)=DATE('now')")
        today_earn = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM bookings")
        bk = c.fetchone()[0]
        conn.close()
        bot.send_message(ADMIN_ID,
            f"📊 *Статистика:*\n\n"
            f"👤 Фойдаланувчилар: *{users}*\n"
            f"📦 Жами фармоишлар: *{cnt}* та\n"
            f"💰 Жами даромад: *{earned:.2f}* смн\n\n"
            f"📅 Бугун фармоишлар: *{today}* та\n"
            f"💵 Бугун даромад: *{today_earn:.2f}* смн\n"
            f"🪑 Жами бронлар: *{bk}* та",
            parse_mode="Markdown", reply_markup=admin_kb())

    elif txt == "📦 Фармоишлар":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT code,total,status,type,date_time FROM orders ORDER BY date_time DESC LIMIT 10")
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(ADMIN_ID, "📭 Фармоиш йўқ.", reply_markup=admin_kb())
            return
        txt2 = "📦 *Охирги 10 та фармоиш:*\n\n"
        for code, total, status, otype, dt in rows:
            txt2 += f"• `{code}` | {total:.0f}смн | {status} | {otype}\n  🕐{dt}\n"
        bot.send_message(ADMIN_ID, txt2, parse_mode="Markdown", reply_markup=admin_kb())

    elif txt == "📅 Бронлар":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id,booking_date,time_slot,guests,phone,status FROM bookings ORDER BY id DESC LIMIT 10")
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(ADMIN_ID, "📭 Брон йўқ.", reply_markup=admin_kb())
            return
        txt2 = "📅 *Бронлар:*\n\n"
        for bid, bdate, btime, guests, phone, status in rows:
            txt2 += f"• ID:{bid} | {bdate} {btime} | 👥{guests} | 📱{phone} | {status}\n"
        bot.send_message(ADMIN_ID, txt2, parse_mode="Markdown", reply_markup=admin_kb())

    elif txt == "➕ Таом қўшиш":
        admin_state[ADMIN_ID] = {"step": "add_name"}
        bot.send_message(ADMIN_ID, "📝 Таом номини киритинг:", reply_markup=types.ReplyKeyboardRemove())

    elif txt == "🗑️ Таом ўчириш":
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id,name,price FROM menu ORDER BY category,name")
        items = c.fetchall()
        conn.close()
        if not items:
            bot.send_message(ADMIN_ID, "📭 Меню бош.", reply_markup=admin_kb())
            return
        mk = types.InlineKeyboardMarkup(row_width=1)
        for fid, fname, fprice in items:
            mk.add(types.InlineKeyboardButton(
                f"🗑️ {fname} — {fprice:.0f}смн", callback_data=f"delfood|{fid}"))
        bot.send_message(ADMIN_ID, "O'chirish uchun tanlang:", reply_markup=mk)

    elif txt == "📨 Статус ўзгартириш":
        # Охирги 10 та фармоишни кўрсатади — статусни ўзгартириш учун
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT code,status FROM orders WHERE status NOT IN ('✔️ Етиб борди','✔️ Yetib bordi') ORDER BY date_time DESC LIMIT 10")
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(ADMIN_ID, "✅ Барча фармоишлар якунланган.", reply_markup=admin_kb())
            return
        mk = types.InlineKeyboardMarkup(row_width=1)
        for code, status in rows:
            mk.add(types.InlineKeyboardButton(
                f"📦 {code} — {status}", callback_data=f"changestatus|{code}"))
        bot.send_message(ADMIN_ID, "Статусини ўзгартириш учун фармоишни танланг:", reply_markup=mk)

# ── Таом ўчириш ────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("delfood|"))
def cb_delete_food(call):
    if call.message.chat.id != ADMIN_ID: return
    fid = int(call.data.split("|")[1])
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT name FROM menu WHERE id=?", (fid,))
    row = c.fetchone()
    if row:
        c.execute("DELETE FROM menu WHERE id=?", (fid,))
        conn.commit()
        bot.answer_callback_query(call.id, f"✅ {row[0]} ўчирилди!")
        c.execute("SELECT id,name,price FROM menu ORDER BY category,name")
        items = c.fetchall()
        if not items:
            bot.edit_message_text("📭 Меню бош.", call.message.chat.id, call.message.message_id)
        else:
            mk = types.InlineKeyboardMarkup(row_width=1)
            for fi,fn,fp in items:
                mk.add(types.InlineKeyboardButton(f"🗑️ {fn} — {fp:.0f}смн", callback_data=f"delfood|{fi}"))
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=mk)
    else:
        bot.answer_callback_query(call.id, "❌ Топилмади.")
    conn.close()

# ── Статус ўзгартириш ──────────────────────────────────────
STATUS_LIST = ["🆕 Янги", "👨‍🍳 Тайёрланмоқда", "✅ Тайёр", "🛵 Йўлда", "✔️ Етиб борди"]

@bot.callback_query_handler(func=lambda c: c.data.startswith("changestatus|"))
def cb_change_status(call):
    if call.message.chat.id != ADMIN_ID: return
    code = call.data.split("|")[1]
    mk = types.InlineKeyboardMarkup(row_width=1)
    for s in STATUS_LIST:
        mk.add(types.InlineKeyboardButton(s, callback_data=f"setstatus|{code}|{s}"))
    bot.edit_message_text(f"📦 `{code}` учун янги статус:", call.message.chat.id,
                          call.message.message_id, parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("setstatus|"))
def cb_set_status(call):
    if call.message.chat.id != ADMIN_ID: return
    _, code, new_status = call.data.split("|", 2)
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE orders SET status=? WHERE code=?", (new_status, code))
    c.execute("SELECT user_id FROM orders WHERE code=?", (code,))
    row = c.fetchone()
    conn.commit()
    conn.close()

    bot.answer_callback_query(call.id, f"✅ Статус: {new_status}")
    bot.edit_message_text(f"✅ `{code}` — {new_status}", call.message.chat.id,
                          call.message.message_id, parse_mode="Markdown")

    # Мижозга хабар юбориш
    if row:
        uid = row[0]
        lang = get_lang(uid)
        try:
            bot.send_message(uid,
                f"📦 *Фармоишингиз холати ўзгарди!*\n"
                f"🆔 Код: `{code}`\n"
                f"📊 Янги ҳолат: *{new_status}*",
                parse_mode="Markdown")
        except:
            pass

# ── Таом қўшиш — steps ─────────────────────────────────────
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and ADMIN_ID in admin_state)
def admin_add_steps(msg):
    state = admin_state[ADMIN_ID]
    step  = state.get("step")

    if step == "add_name":
        name = msg.text.strip()
        if len(name) < 2:
            bot.send_message(ADMIN_ID, "❌ Ном жуда қисқа:")
            return
        state["name"] = name
        state["step"] = "add_price"
        bot.send_message(ADMIN_ID, "💰 Нарх (масалан: 35.5):")

    elif step == "add_price":
        try:
            price = float(msg.text.replace(",","."))
            if price <= 0: raise ValueError
            state["price"] = price
            state["step"]  = "add_category"
            mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            for cat in CATEGORIES: mk.add(cat)
            bot.send_message(ADMIN_ID, "📁 Категория:", reply_markup=mk)
        except ValueError:
            bot.send_message(ADMIN_ID, "❌ Нотўғри нарх! Масалан: 35.5")

    elif step == "add_category":
        if msg.text not in CATEGORIES:
            bot.send_message(ADMIN_ID, "❌ Рӯйхатдан танланг!")
            return
        conn = get_conn()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO menu (name,price,category,image_id) VALUES(?,?,?,?)",
                      (state["name"], state["price"], msg.text, None))
            conn.commit()
            bot.send_message(ADMIN_ID,
                f"✅ *{state['name']}* қўшилди!\n💰 {state['price']:.2f} смн",
                parse_mode="Markdown", reply_markup=admin_kb())
        except sqlite3.IntegrityError:
            bot.send_message(ADMIN_ID, "❌ Бу таом аллақачон мавжуд!", reply_markup=admin_kb())
        finally:
            conn.close()
        del admin_state[ADMIN_ID]

# ── ⬅️ Орқага ──────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "⬅️ Орқага")
def back_to_main(msg):
    uid = msg.chat.id
    if uid != ADMIN_ID: return
    bot.send_message(uid, "🏠 Асосий меню:", reply_markup=main_kb(uid))

# ============================================================
#  📋  CLIENT ROUTING
# ============================================================
def is_client_btn(msg):
    uid = msg.chat.id
    btns = {t(uid,"btn_menu"), t(uid,"btn_cart"),
            t(uid,"btn_book"), t(uid,"btn_profile"),
            t(uid,"btn_admin")}
    return msg.text in btns

@bot.message_handler(func=is_client_btn)
def client_router(msg):
    uid = msg.chat.id
    if not check_session(uid): return
    txt = msg.text

    if txt == t(uid,"btn_admin"):
        if uid == ADMIN_ID:
            bot.send_message(uid, "👑 Admin panel:", reply_markup=admin_kb())
        else:
            bot.send_message(uid, "❌ Фақат Admin!")
        return

    if txt == t(uid,"btn_menu"):
        show_categories(uid)
    elif txt == t(uid,"btn_cart"):
        if not is_open():
            bot.send_message(uid, t(uid,"closed",open=OPEN_HOUR,close=CLOSE_HOUR),
                             parse_mode="Markdown", reply_markup=main_kb(uid))
            return
        show_cart(uid)
    elif txt == t(uid,"btn_book"):
        if not is_open():
            bot.send_message(uid, t(uid,"closed",open=OPEN_HOUR,close=CLOSE_HOUR),
                             parse_mode="Markdown", reply_markup=main_kb(uid))
            return
        start_booking(uid)
    elif txt == t(uid,"btn_profile"):
        show_profile(msg)

# ============================================================
#  📋  MENU — KATEGORIYALAR
# ============================================================
def show_categories(uid: int):
    mk = types.InlineKeyboardMarkup(row_width=1)
    for cat in CATEGORIES:
        mk.add(types.InlineKeyboardButton(cat, callback_data=f"cat|{cat}"))
    bot.send_message(uid, t(uid,"menu_title"), parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cat|") or c.data == "back_cats")
def cb_category(call):
    uid = call.message.chat.id
    if not check_session(uid): return

    if call.data == "back_cats":
        mk = types.InlineKeyboardMarkup(row_width=1)
        for cat in CATEGORIES:
            mk.add(types.InlineKeyboardButton(cat, callback_data=f"cat|{cat}"))
        try:
            bot.edit_message_text(t(uid,"menu_title"), uid, call.message.message_id,
                                  parse_mode="Markdown", reply_markup=mk)
        except:
            show_categories(uid)
        return

    cat_name = call.data.split("|",1)[1]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT name,price,image_id FROM menu WHERE category=?", (cat_name,))
    items = c.fetchall()
    conn.close()
    if not items:
        bot.answer_callback_query(call.id, "Bu kategoriyada taom yo'q.")
        return
    bot.answer_callback_query(call.id)
    for name, price, img_id in items:
        mk = types.InlineKeyboardMarkup(row_width=2)
        mk.add(
            types.InlineKeyboardButton("➖", callback_data=f"rem|{name}"),
            types.InlineKeyboardButton("➕", callback_data=f"add|{name}"),
        )
        caption = f"🍽 *{name}*\n💰 {price:.2f} смн"
        if img_id:
            try:
                bot.send_photo(uid, img_id, caption=caption, parse_mode="Markdown", reply_markup=mk)
                continue
            except: pass
        bot.send_message(uid, caption, parse_mode="Markdown", reply_markup=mk)
    back_mk = types.InlineKeyboardMarkup()
    back_mk.add(types.InlineKeyboardButton("⬅️ Орқага", callback_data="back_cats"))
    bot.send_message(uid, "─────────────", reply_markup=back_mk)

# ── Савад ──────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("add|") or c.data.startswith("rem|"))
def cb_cart(call):
    uid = call.message.chat.id
    if not check_session(uid): return
    action, food_name = call.data.split("|",1)
    conn = get_conn()
    c = conn.cursor()
    if action == "add":
        c.execute("SELECT price FROM menu WHERE name=?", (food_name,))
        row = c.fetchone()
        if row:
            c.execute("INSERT INTO cart (user_id,food,qty,price) VALUES(?,?,1,?)", (uid,food_name,row[0]))
            conn.commit()
            bot.answer_callback_query(call.id, f"✅ {food_name} savatga qo'shildi!")
        else:
            bot.answer_callback_query(call.id, "❌ Taom topilmadi.")
    else:
        c.execute("SELECT rowid FROM cart WHERE user_id=? AND food=? LIMIT 1", (uid,food_name))
        row = c.fetchone()
        if row:
            c.execute("DELETE FROM cart WHERE rowid=?", (row[0],))
            conn.commit()
            bot.answer_callback_query(call.id, f"➖ {food_name} olib tashlandi.")
        else:
            bot.answer_callback_query(call.id, "🛒 Bu taom savatda yo'q!")
    conn.close()

# ============================================================
#  🛒  SAVAT
# ============================================================
def show_cart(uid: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT food,SUM(qty),price FROM cart WHERE user_id=? GROUP BY food,price", (uid,))
    items = c.fetchall()
    conn.close()
    if not items:
        bot.send_message(uid, t(uid,"cart_empty"), reply_markup=main_kb(uid))
        return
    txt   = t(uid,"cart_title") + "\n\n"
    total = 0
    for food, qty, price in items:
        sub    = qty * price
        total += sub
        txt   += f"• {food}  ×{qty}  =  {sub:.2f} смн\n"
    txt += f"\n💰 *Жами: {total:.2f} смн*"
    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(
        types.InlineKeyboardButton("🙋 Ўзим учун", callback_data="co_self"),
        types.InlineKeyboardButton("🎁 Тӯҳфа",     callback_data="co_gift"),
        types.InlineKeyboardButton("🗑️ Тозалаш",   callback_data="co_clear"),
    )
    bot.send_message(uid, txt, parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data in ("co_self","co_gift","co_clear"))
def cb_checkout(call):
    uid = call.message.chat.id
    if not check_session(uid): return
    if not is_open():
        bot.answer_callback_query(call.id, t(uid,"closed",open=OPEN_HOUR,close=CLOSE_HOUR), show_alert=True)
        return
    if call.data == "co_clear":
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM cart WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        try: bot.delete_message(uid, call.message.message_id)
        except: pass
        bot.send_message(uid, "🗑️ Savat tozalandi.", reply_markup=main_kb(uid))
        return
    order_mode[uid] = "self" if call.data == "co_self" else "gift"
    try: bot.delete_message(uid, call.message.message_id)
    except: pass
    ask_phone(uid)

def ask_phone(uid: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT phone FROM users WHERE id=?", (uid,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        after_phone(uid)
        return
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(types.KeyboardButton("📱 Tasdiqlash", request_contact=True))
    m = bot.send_message(uid, t(uid,"phone_request"), reply_markup=mk)
    bot.register_next_step_handler(m, save_phone)

def save_phone(msg):
    uid = msg.chat.id
    if not msg.contact:
        bot.send_message(uid, "❌ Tasdiqlanmadi. /start bosing.", reply_markup=main_kb(uid))
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET phone=? WHERE id=?", (msg.contact.phone_number, uid))
    conn.commit()
    conn.close()
    after_phone(uid)

def after_phone(uid: int):
    if order_mode.get(uid) == "gift":
        m = bot.send_message(uid, "👤 Tuhfa oluvchi telefon raqamini kiriting:")
        bot.register_next_step_handler(m, process_gift_receiver)
    else:
        ask_service(uid)

def process_gift_receiver(msg):
    uid   = msg.chat.id
    phone = (msg.text or "").strip()
    conn  = get_conn()
    c     = conn.cursor()
    c.execute("SELECT id FROM users WHERE phone=?", (phone,))
    row = c.fetchone()
    conn.close()
    if not row:
        bot.send_message(uid, "❌ Bu raqam botda ro'yxatdan o'tmagan!", reply_markup=main_kb(uid))
        return
    receiver_id = row[0]
    code = gen_code()
    pending_orders[receiver_id] = {"sender_id": uid, "code": code}
    bot.send_message(uid, "⏳ Tasdiqlandi. Qabul qiluvchi lokatsiyasi kutilmoqda...", reply_markup=main_kb(uid))
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(types.KeyboardButton("📍 Lokatsiyamni yuborish", request_location=True))
    bot.send_message(receiver_id, "🎁 Do'stingiz sizga tuhfa yubormoqchi!\nLokatsiyangizni yuboring:", reply_markup=mk)

def ask_service(uid: int):
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(t(uid,"delivery"), t(uid,"dine_in"))
    m = bot.send_message(uid, t(uid,"service_ask"), reply_markup=mk)
    bot.register_next_step_handler(m, save_service)

def save_service(msg):
    uid = msg.chat.id
    if not check_session(uid): return
    if msg.text not in (t(uid,"delivery"), t(uid,"dine_in")):
        bot.send_message(uid, "❌ Tugmalardan birini tanlang.", reply_markup=main_kb(uid))
        return
    service_type[uid] = msg.text
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(types.KeyboardButton("📍 Lokatsiyamni yuborish", request_location=True))
    bot.send_message(uid, "📍 Haqiqiy joylashuvingizni yuboring:", reply_markup=mk)

# ============================================================
#  📍  LOKATSIYA
# ============================================================
@bot.message_handler(content_types=["location"])
def handle_location(msg):
    uid = msg.chat.id
    lat = msg.location.latitude
    lon = msg.location.longitude

    if uid in pending_orders:
        info = pending_orders.pop(uid)
        if not in_dushanbe(lat, lon):
            bot.send_message(uid, t(uid,"outside_city"), reply_markup=main_kb(uid))
            bot.send_message(info["sender_id"], "❌ Qabul qiluvchi xizmat hududidan tashqarida.", reply_markup=main_kb(info["sender_id"]))
            return
        finalize_order(info["sender_id"], uid, "Tuhfa", f"Lokatsiya: {lat:.5f},{lon:.5f}", info["code"])
        return

    stype = service_type.pop(uid, None)
    if not stype: return

    if not in_dushanbe(lat, lon):
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM cart WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        bot.send_message(uid, t(uid,"outside_city"), reply_markup=main_kb(uid))
        return

    if stype == t(uid,"dine_in"):
        dist = haversine(lat, lon, RESTAURANT_LAT, RESTAURANT_LON)
        if dist > 150:
            conn = get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM cart WHERE user_id=?", (uid,))
            conn.commit()
            conn.close()
            bot.send_message(uid, t(uid,"not_in_rest",dist=dist),
                             parse_mode="Markdown", reply_markup=main_kb(uid))
            return
        finalize_order(uid, uid, "Restoranda", f"Zal ({dist:.0f}m)")
    else:
        finalize_order(uid, uid, "Yetkazib berish", f"Lokatsiya: {lat:.5f},{lon:.5f}")

def finalize_order(sender_id, receiver_id, o_type, details, code=None):
    code     = code or gen_code()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT food,qty,price FROM cart WHERE user_id=?", (sender_id,))
    cart = c.fetchall()
    if not cart:
        conn.close()
        bot.send_message(sender_id, t(sender_id,"cart_empty"), reply_markup=main_kb(sender_id))
        return
    total    = sum(q*p for _,q,p in cart)
    cart_txt = "\n".join(f"  • {f} ×{q} = {q*p:.2f}смн" for f,q,p in cart)
    c.execute("SELECT phone FROM users WHERE id=?", (sender_id,))
    pr    = c.fetchone()
    phone = pr[0] if pr else "Noma'lum"
    c.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,'🆕 Yangi',?)",
              (code, sender_id, receiver_id, o_type, details, total, date_str))
    c.execute("DELETE FROM cart WHERE user_id=?", (sender_id,))
    conn.commit()
    conn.close()

    # Mижозга
    bot.send_message(sender_id,
        t(sender_id,"order_done", code=code, total=total) +
        f"\n\n{cart_txt}",
        parse_mode="Markdown", reply_markup=main_kb(sender_id))

    # Adminga
    bot.send_message(ADMIN_ID,
        f"🔔 *YANGI BUYURTMA!*\n\n"
        f"🕐 {date_str}\n"
        f"👤 ID:`{sender_id}` | 📱{phone}\n"
        f"📦 {o_type} | 📍{details}\n\n"
        f"{cart_txt}\n\n"
        f"💰 Jami: *{total:.2f}смн* | 🆔`{code}`",
        parse_mode="Markdown")

# ============================================================
#  📅  STOL BRON
# ============================================================
def start_booking(uid: int):
    booking_state[uid] = {}
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT phone FROM users WHERE id=?", (uid,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        booking_state[uid]["phone"] = row[0]
        ask_booking_guests(uid)
    else:
        mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        mk.add(types.KeyboardButton("📱 Tasdiqlash", request_contact=True))
        m = bot.send_message(uid, t(uid,"phone_request"), reply_markup=mk)
        bot.register_next_step_handler(m, save_phone_booking)

def save_phone_booking(msg):
    uid = msg.chat.id
    if not msg.contact:
        bot.send_message(uid, "❌ /start bosing.", reply_markup=main_kb(uid))
        return
    phone = msg.contact.phone_number
    conn  = get_conn()
    c     = conn.cursor()
    c.execute("UPDATE users SET phone=? WHERE id=?", (phone, uid))
    conn.commit()
    conn.close()
    booking_state[uid]["phone"] = phone
    ask_booking_guests(uid)

def ask_booking_guests(uid: int):
    m = bot.send_message(uid, t(uid,"guests_ask"), reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(m, step_guests)

def step_guests(msg):
    uid = msg.chat.id
    if not msg.text or not msg.text.strip().isdigit() or int(msg.text.strip()) < 1:
        m = bot.send_message(uid, "❌ Faqat musbat raqam!")
        bot.register_next_step_handler(m, step_guests)
        return
    g = int(msg.text.strip())
    if g > 50:
        m = bot.send_message(uid, "❌ Maksimum 50 nafar. Qayta kiriting:")
        bot.register_next_step_handler(m, step_guests)
        return
    booking_state[uid]["guests"] = g
    m = bot.send_message(uid, t(uid,"day_ask"))
    bot.register_next_step_handler(m, step_day)

def step_day(msg):
    uid = msg.chat.id
    if not msg.text or not msg.text.strip().isdigit():
        m = bot.send_message(uid, "❌ Faqat raqam! Masalan: 15")
        bot.register_next_step_handler(m, step_day)
        return
    day = int(msg.text.strip())
    if not 1 <= day <= 31:
        m = bot.send_message(uid, "❌ Kun 1-31 oralig'ida bo'lishi kerak:")
        bot.register_next_step_handler(m, step_day)
        return
    booking_state[uid]["day"] = day
    m = bot.send_message(uid, t(uid,"month_ask"))
    bot.register_next_step_handler(m, step_month)

def step_month(msg):
    uid = msg.chat.id
    if not msg.text or not msg.text.strip().isdigit():
        m = bot.send_message(uid, "❌ Faqat raqam! Masalan: 6")
        bot.register_next_step_handler(m, step_month)
        return
    month = int(msg.text.strip())
    if not 1 <= month <= 12:
        m = bot.send_message(uid, "❌ Oy 1-12 oralig'ida bo'lishi kerak:")
        bot.register_next_step_handler(m, step_month)
        return
    day  = booking_state[uid]["day"]
    now  = datetime.now()
    year = now.year
    if month < now.month or (month == now.month and day < now.day):
        year += 1
    max_day = calendar.monthrange(year, month)[1]
    if day > max_day:
        bot.send_message(uid,
            f"❌ {month}-oyda {day}-kun mavjud emas (max {max_day})!\n/start bosing.",
            reply_markup=main_kb(uid))
        booking_state.pop(uid, None)
        return
    try:
        b_date = datetime(year, month, day)
    except ValueError:
        bot.send_message(uid, "❌ Noto'g'ri sana. /start bosing.", reply_markup=main_kb(uid))
        booking_state.pop(uid, None)
        return
    booking_state[uid]["valid_date"] = b_date.strftime("%Y-%m-%d")
    m = bot.send_message(uid, t(uid,"time_ask"))
    bot.register_next_step_handler(m, step_time)

def step_time(msg):
    uid = msg.chat.id
    ts  = (msg.text or "").strip()
    if not valid_time(ts):
        m = bot.send_message(uid, "❌ Format: 18:00")
        bot.register_next_step_handler(m, step_time)
        return
    data = booking_state.pop(uid, None)
    if not data:
        bot.send_message(uid, "❌ Sessiya tugadi. /start bosing.", reply_markup=main_kb(uid))
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO bookings (user_id,guests,booking_date,time_slot,phone,status) VALUES(?,?,?,?,?,?)",
              (uid, data["guests"], data["valid_date"], ts, data["phone"], "Интизор 🟡"))
    conn.commit()
    conn.close()
    bot.send_message(uid,
        t(uid,"booking_done", date=data["valid_date"], time=ts, guests=data["guests"]),
        parse_mode="Markdown", reply_markup=main_kb(uid))
    bot.send_message(ADMIN_ID,
        f"📅 *YANGI BRON:*\n👤ID:`{uid}` | 📱{data['phone']}\n"
        f"👥{data['guests']} nafar | 📅{data['valid_date']} {ts}",
        parse_mode="Markdown")

# ============================================================
#  👤  PROFIL
# ============================================================
def show_profile(msg):
    uid  = msg.chat.id
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT phone, lang FROM users WHERE id=?", (uid,))
    row = c.fetchone()
    conn.close()
    phone = row[0] if row and row[0] else "Ro'yxatdan o'tilmagan ❌"
    lang  = row[1] if row and row[1] else "tj"
    name  = msg.from_user.first_name or "—"
    bot.send_message(uid,
        f"👤 *Profilingiz:*\n\n"
        f"📛 Ism: {name}\n"
        f"🆔 ID: `{uid}`\n"
        f"📱 Telefon: {phone}\n"
        f"🌐 Til: {'🇹🇯 Tojikcha' if lang=='tj' else '🇺🇿 O\'zbek'}",
        parse_mode="Markdown")

# ============================================================
#  📊  KUNLIK HISOBOT — har kech 21:00 da avtomatik
# ============================================================
def send_daily_report():
    while True:
        now = datetime.now()
        # Keyingi 21:00 gacha kutamiz
        next_run = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now >= next_run:
            from datetime import timedelta
            next_run += timedelta(days=1)
        wait_sec = (next_run - now).total_seconds()
        time.sleep(wait_sec)

        try:
            conn = get_conn()
            c = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")
            c.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders WHERE date_time LIKE ?", (f"{today}%",))
            cnt, earned = c.fetchone()
            c.execute("SELECT type, COUNT(*) FROM orders WHERE date_time LIKE ? GROUP BY type", (f"{today}%",))
            by_type = c.fetchall()
            conn.close()

            txt = (
                f"📊 *Kunlik hisobot — {today}*\n\n"
                f"📦 Buyurtmalar: *{cnt}* ta\n"
                f"💰 Daromad: *{earned:.2f}* smn\n\n"
            )
            if by_type:
                txt += "📋 *Tur bo'yicha:*\n"
                for otype, ocnt in by_type:
                    txt += f"  • {otype}: {ocnt} ta\n"

            if cnt == 0:
                txt += "\n😕 Bugun buyurtma bo'lmadi."
            else:
                txt += f"\n✅ Yaxshi kun!"

            bot.send_message(ADMIN_ID, txt, parse_mode="Markdown")
        except Exception as e:
            print(f"[Hisobot xatosi]: {e}")

# ============================================================
#  ⏱️  RENDER UCHUN UYG'OQ SAQLASH TIZIMI (KEEP-ALIVE)
# ============================================================
def keep_alive_ping():
    """Бот ухлаб қолмаслиги учун ҳар 10 дақиқада Telegram API орқали ўзини текширади"""
    time.sleep(30)
    print("🚀 Keep-Alive тизими ишга тушди!")
    while True:
        try:
            bot.get_me()
            print(f"⏰ [Ping] Сервер уйғоқ сақланди: {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[Ping Хатоси]: {e}")
        time.sleep(600)

# ============================================================
#  🚫  SPAM FILTER
# ============================================================
# Ака, мана бу ер аслида сизнинг кодингизда 'handle_spam' функциясидан тепароқда эди
SPAM_TYPES = ["voice","video","photo","document","sticker","audio","video_note"]

@bot.message_handler(content_types=SPAM_TYPES)
def handle_spam(msg):
    try: bot.delete_message(msg.chat.id, msg.message_id)
    except: pass
    bot.send_message(msg.chat.id, "⚠️ Faqat tugmalardan foydalaning!", reply_markup=main_kb(msg.chat.id))

@bot.message_handler(func=lambda m: True)
def handle_unknown(msg):
    uid = msg.chat.id
    if uid == ADMIN_ID and ADMIN_ID in admin_state:
        admin_add_steps(msg)
        return
    try: bot.delete_message(uid, msg.message_id)
    except: pass
    mk = admin_kb() if uid == ADMIN_ID else main_kb(uid)
    bot.send_message(uid, "⚠️ Tugmalardan foydalaning!", reply_markup=mk)

# ============================================================
#  🚀  ISHGA TUSHIRISH
# ============================================================
if __name__ == "__main__":
    print("✅ Restoran boti ishga tushdi!")
    
    # Реднер ухлаб қолмаслиги учун янги Keep-Alive thread'и
    ping_thread = threading.Thread(target=keep_alive_ping, daemon=True)
    ping_thread.start()
    
    # Kunlik hisobot thread'i
    report_thread = threading.Thread(target=send_daily_report, daemon=True)
    report_thread.start()
    
    bot.infinity_polling(timeout=30, long_polling_timeout=20)
