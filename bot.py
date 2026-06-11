import os
import re
import random
import sqlite3
import string
import time
import math
import calendar
import threading
from datetime import datetime, timedelta
import telebot
from telebot import types

# ============================================================
#  ⚙️  АСОСИЙ СОЗЛАМАЛАР
# ============================================================
TOKEN    = os.environ.get("BOT_TOKEN", "TOKEN_BУ_ЕРГА")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

bot     = telebot.TeleBot(TOKEN)
DB_NAME = "restaurant.db"

RESTAURANT_LAT = 38.5642
RESTAURANT_LON = 68.7610
OPEN_HOUR      = 8
CLOSE_HOUR     = 23
SESSION_TIMEOUT = 600  # 10 дақиқа

CATEGORIES = [
    "🍲 Таомҳои миллии гарм",
    "🍢 Кабобҳо",
    "🥗 Хӯришҳо ва Газакҳо",
    "🥤 Нӯшокиҳои миллӣ",
    "🍰 Десертҳо ва Ширинлиҳо",
]

# ============================================================
#  🗄️  БАЗА ДАННЫХ
# ============================================================
def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY,
            phone         TEXT,
            last_activity INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS menu (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT UNIQUE NOT NULL,
            price    REAL NOT NULL,
            category TEXT NOT NULL,
            image_id TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            user_id INTEGER,
            food    TEXT,
            qty     INTEGER DEFAULT 1,
            price   REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            guests       INTEGER,
            booking_date TEXT,
            time_slot    TEXT,
            phone        TEXT,
            status       TEXT DEFAULT 'Интизор 🟡'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            code        TEXT PRIMARY KEY,
            user_id     INTEGER,
            receiver_id INTEGER,
            type        TEXT,
            details     TEXT,
            total       REAL,
            status      TEXT DEFAULT '🆕 Нав',
            date_time   TEXT
        )
    """)

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
        c.executemany(
            "INSERT INTO menu (name, price, category, image_id) VALUES (?, ?, ?, ?)",
            default_menu
        )

    conn.commit()
    conn.close()

init_db()

# ============================================================
#  📦  ВАҚТИНЧАЛИК ҲОЛАТЛАР
# ============================================================
pending_orders = {}   # тӯҳфа: receiver_id -> {sender_id, code}
admin_state    = {}   # админ қадамлари
booking_state  = {}   # брон қадамлари: uid -> {}
order_mode     = {}   # "self" | "gift"
service_type   = {}   # "доставка" | "зал"

# ============================================================
#  🛠️  ЁРДАМЧИ ФУНКЦИЯЛАР
# ============================================================
def is_open() -> bool:
    return OPEN_HOUR <= datetime.now().hour < CLOSE_HOUR

def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def in_dushanbe(lat, lon) -> bool:
    return 38.48 <= lat <= 38.65 and 68.68 <= lon <= 68.90

def gen_code(n=6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))

def valid_time(t_str: str) -> bool:
    return bool(re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", t_str.strip()))

def ensure_user(uid: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (id, last_activity) VALUES (?, ?)",
        (uid, int(time.time()))
    )
    conn.commit()
    conn.close()

def check_session(uid: int) -> bool:
    ensure_user(uid)
    now  = int(time.time())
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT last_activity FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    if row and now - row[0] > SESSION_TIMEOUT:
        c.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
        c.execute("UPDATE users SET last_activity = ? WHERE id = ?", (now, uid))
        conn.commit()
        conn.close()
        bot.send_message(
            uid,
            "⏱️ *Сессия ба охир расид.*\n"
            "Шумо 10 дақиқа фаъол набудед.\n"
            "Сабади харидатон автоматӣ тоза шуд.\n"
            "Лутфан /start -ро пахш кунед 👇",
            parse_mode="Markdown",
            reply_markup=main_kb()
        )
        return False
    c.execute("UPDATE users SET last_activity = ? WHERE id = ?", (now, uid))
    conn.commit()
    conn.close()
    return True

def clear_state(uid: int):
    for d in (order_mode, service_type, booking_state, pending_orders):
        d.pop(uid, None)

# ============================================================
#  ⌨️  КЛАВИАТУРАЛАР
# ============================================================
def main_kb():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add("📋 Менюи таомҳо", "🛒 Сабади харид")
    m.add("📅 Брон кардани стол", "👤 Профили ман")
    m.add("👑 Саҳифаи Админ")
    return m

def admin_kb():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add("📊 Омори умумӣ",       "📦 Рӯйхати фармоишҳо")
    m.add("📅 Бронҳои стол",      "➕ Илова кардани таом")
    m.add("🗑️ Нест кардани таом", "📨 Тағйир додани статус")
    m.add("⬅️ Ба менюи асосӣ")
    return m

# ============================================================
#  /start
# ============================================================
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.chat.id
    clear_state(uid)
    admin_state.pop(ADMIN_ID, None)
    ensure_user(uid)

    conn = get_conn()
    c    = conn.cursor()
    c.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
    c.execute("UPDATE users SET last_activity = ? WHERE id = ?", (int(time.time()), uid))
    conn.commit()
    conn.close()

    name = msg.from_user.first_name or "дӯст"
    bot.send_message(
        uid,
        f"🌟 *Хуш омадед, {name}!*\n\n"
        "Ба боти ресторании мо хуш омадед.\n"
        "Лутфан хизматрасониро интихоб кунед 👇",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

# ============================================================
#  👑  ПАНЕЛИ АДМИН
# ============================================================
ADMIN_BTNS = {
    "👑 Саҳифаи Админ",
    "📊 Омори умумӣ",
    "📦 Рӯйхати фармоишҳо",
    "📅 Бронҳои стол",
    "➕ Илова кардани таом",
    "🗑️ Нест кардани таом",
    "📨 Тағйир додани статус",
}

@bot.message_handler(func=lambda m: m.text in ADMIN_BTNS)
def admin_router(msg):
    uid = msg.chat.id
    if uid != ADMIN_ID:
        bot.send_message(uid, "❌ Танҳо Админ дастрасӣ дорад!", reply_markup=main_kb())
        return

    txt = msg.text

    if txt == "👑 Саҳифаи Админ":
        bot.send_message(
            ADMIN_ID,
            "👑 *Панели Админ*\nБахшро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=admin_kb()
        )

    elif txt == "📊 Омори умумӣ":
        conn  = get_conn()
        c     = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")

        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]

        c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders")
        total_cnt, total_earned = c.fetchone()

        c.execute(
            "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders WHERE date_time LIKE ?",
            (f"{today}%",)
        )
        today_cnt, today_earned = c.fetchone()

        c.execute("SELECT COUNT(*) FROM bookings")
        bk_cnt = c.fetchone()[0]

        conn.close()
        bot.send_message(
            ADMIN_ID,
            f"📊 *Омори умумии..."
            f"👤 Мизоҷон: *{users}* нафар\n"
            f"📦 Ҷамъи фармоишҳо: *{total_cnt}* та\n"
            f"💰 Ҷамъи даромад: *{total_earned:.2f}* смн\n\n"
            f"📅 *Имрӯз ({today}):*\n"
            f"   📦 Фармоишҳо: *{today_cnt}* та\n"
            f"   💵 Даромад: *{today_earned:.2f}* смн\n\n"
            f"🪑 Ҷамъи бронҳо: *{bk_cnt}* та",
            parse_mode="Markdown",
            reply_markup=admin_kb()
        )

    elif txt == "📦 Рӯйхати фармоишҳо":
        conn = get_conn()
        c    = conn.cursor()
        c.execute(
            "SELECT code, total, status, type, date_time FROM orders "
            "ORDER BY date_time DESC LIMIT 10"
        )
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(ADMIN_ID, "📭 Ҳоло фармоиш мавҷуд нест.", reply_markup=admin_kb())
            return
        txt2 = "📦 *Охирин 10 та фармоиш:*\n\n"
        for code, total, status, otype, dt in rows:
            txt2 += f"• `{code}` | {total:.0f}смн | {status}\n  📦{otype} | 🕐{dt}\n\n"
        bot.send_message(ADMIN_ID, txt2, parse_mode="Markdown", reply_markup=admin_kb())

    elif txt == "📅 Бронҳои стол":
        conn = get_conn()
        c    = conn.cursor()
        c.execute(
            "SELECT id, booking_date, time_slot, guests, phone, status "
            "FROM bookings ORDER BY id DESC LIMIT 10"
        )
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(ADMIN_ID, "📭 Ҳоло брон мавҷуд нест.", reply_markup=admin_kb())
            return
        txt2 = "📅 *Охирин 10 та брон:*\n\n"
        for bid, bdate, btime, guests, phone, status in rows:
            txt2 += (
                f"• ID:{bid}\n"
                f"  📅 {bdate} | ⏱️ {btime}\n"
                f"  👥 {guests} нафар | 📱 {phone}\n"
                f"  {status}\n\n"
            )
        bot.send_message(ADMIN_ID, txt2, parse_mode="Markdown", reply_markup=admin_kb())

    elif txt == "➕ Илова кардани таом":
        admin_state[ADMIN_ID] = {"step": "add_name"}
        bot.send_message(
            ADMIN_ID,
            "📝 Номи таоми навро ворид кунед:",
            reply_markup=types.ReplyKeyboardRemove()
        )

    elif txt == "🗑️ Нест кардани таом":
        conn = get_conn()
        c    = conn.cursor()
        c.execute("SELECT id, name, price FROM menu ORDER BY category, name")
        items = c.fetchall()
        conn.close()
        if not items:
            bot.send_message(ADMIN_ID, "📭 Меню холӣ аст.", reply_markup=admin_kb())
            return
        mk = types.InlineKeyboardMarkup(row_width=1)
        for fid, fname, fprice in items:
            mk.add(types.InlineKeyboardButton(
                f"🗑️ {fname} — {fprice:.0f} смн",
                callback_data=f"delfood|{fid}"
            ))
        bot.send_message(ADMIN_ID, "Таоми дилхоҳро барои нест кардан интихоб кунед:", reply_markup=mk)

    elif txt == "📨 Тағйир додани статус":
        conn = get_conn()
        c    = conn.cursor()
        c.execute(
            "SELECT code, status, type FROM orders "
            "WHERE status != '✔️ Расид' "
            "ORDER BY date_time DESC LIMIT 15"
        )
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(ADMIN_ID, "✅ Ҳамаи фармоишҳо иҷро шудааст.", reply_markup=admin_kb())
            return
        mk = types.InlineKeyboardMarkup(row_width=1)
        for code, status, otype in rows:
            mk.add(types.InlineKeyboardButton(
                f"📦 {code} | {status} | {otype}",
                callback_data=f"chst|{code}"
            ))
        bot.send_message(ADMIN_ID, "Статусини тағйир додан учун фармоишро интихоб кунед:", reply_markup=mk)


# ── Таомро нест кардан ─────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("delfood|"))
def cb_delete_food(call):
    if call.message.chat.id != ADMIN_ID:
        return
    fid  = int(call.data.split("|")[1])
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT name FROM menu WHERE id = ?", (fid,))
    row = c.fetchone()
    if row:
        c.execute("DELETE FROM menu WHERE id = ?", (fid,))
        conn.commit()
        bot.answer_callback_query(call.id, f"✅ {row[0]} нест карда шуд!")
        c.execute("SELECT id, name, price FROM menu ORDER BY category, name")
        items = c.fetchall()
        if not items:
            bot.edit_message_text(
                "📭 Меню пурра холӣ шуд.",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            mk = types.InlineKeyboardMarkup(row_width=1)
            for fi, fn, fp in items:
                mk.add(types.InlineKeyboardButton(
                    f"🗑️ {fn} — {fp:.0f} смн",
                    callback_data=f"delfood|{fi}"
                ))
            bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=mk
            )
    else:
        bot.answer_callback_query(call.id, "❌ Таом ёфт нашуд.")
    conn.close()


# ── Статус тағйир додан ────────────────────────────────────
STATUS_LIST = [
    "🆕 Нав",
    "👨‍🍳 Тайёр карда мешавад",
    "✅ Тайёр аст",
    "🛵 Дар роҳ аст",
    "✔️ Расид",
]

@bot.callback_query_handler(func=lambda c: c.data.startswith("chst|"))
def cb_choose_status(call):
    if call.message.chat.id != ADMIN_ID:
        return
    code = call.data.split("|")[1]
    mk   = types.InlineKeyboardMarkup(row_width=1)
    for s in STATUS_LIST:
        mk.add(types.InlineKeyboardButton(s, callback_data=f"setst|{code}|{s}"))
    try:
        bot.edit_message_text(
            f"📦 `{code}` — янги статусро интихоб кунед:",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=mk
        )
    except:
        bot.send_message(
            ADMIN_ID,
            f"📦 `{code}` — янги статусро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=mk
        )

@bot.callback_query_handler(func=lambda c: c.data.startswith("setst|"))
def cb_set_status(call):
    if call.message.chat.id != ADMIN_ID:
        return
    parts      = call.data.split("|", 2)
    code       = parts[1]
    new_status = parts[2]

    conn = get_conn()
    c    = conn.cursor()
    c.execute("UPDATE orders SET status = ? WHERE code = ?", (new_status, code))
    c.execute("SELECT user_id FROM orders WHERE code = ?", (code,))
    row = c.fetchone()
    conn.commit()
    conn.close()

    bot.answer_callback_query(call.id, f"✅ Статус: {new_status}")
    try:
        bot.edit_message_text(
            f"✅ `{code}` — {new_status}",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
    except:
        pass

    if row:
        try:
            bot.send_message(
                row[0],
                f"🔔 *Фармоиши шумо навсозӣ шуд!*\n\n"
                f"🆔 Код: `{code}`\n"
                f"📊 Ҳолат: *{new_status}*",
                parse_mode="Markdown"
            )
        except:
            pass


# ── Таом илова кардан — қадамҳо ───────────────────────────
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and ADMIN_ID in admin_state)
def admin_add_steps(msg):
    state = admin_state[ADMIN_ID]
    step  = state.get("step")

    if step == "add_name":
        name = msg.text.strip()
        if len(name) < 2:
            bot.send_message(ADMIN_ID, "❌ Ном хеле кӯтоҳ аст. Дубора ворид кунед:")
            return
        state["name"] = name
        state["step"] = "add_price"
        bot.send_message(ADMIN_ID, "💰 Нархи таомро ворид кунед (масалан: 35.5):")

    elif step == "add_price":
        try:
            price = float(msg.text.strip().replace(",", "."))
            if price <= 0:
                raise ValueError
            state["price"] = price
            state["step"]  = "add_category"
            mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            for cat in CATEGORIES:
                mk.add(cat)
            bot.send_message(ADMIN_ID, "📁 Категорияро интихоб кунед:", reply_markup=mk)
        except ValueError:
            bot.send_message(ADMIN_ID, "❌ Нархи нодуруст! Масалан: 35.5")

    elif step == "add_category":
        if msg.text not in CATEGORIES:
            bot.send_message(ADMIN_ID, "❌ Лутфан аз рӯйхат интихоб кунед!")
            return
        conn = get_conn()
        c    = conn.cursor()
        try:
            c.execute(
                "INSERT INTO menu (name, price, category, image_id) VALUES (?, ?, ?, ?)",
                (state["name"], state["price"], msg.text, None)
            )
            conn.commit()
            bot.send_message(
                ADMIN_ID,
                f"✅ *{state['name']}* ба меню илова шуд!\n"
                f"💰 Нарх: {state['price']:.2f} смн\n"
                f"📁 Категория: {msg.text}",
                parse_mode="Markdown",
                reply_markup=admin_kb()
            )
        except sqlite3.IntegrityError:
            bot.send_message(
                ADMIN_ID,
                "❌ Ин таом аллакай дар меню мавҷуд аст!",
                reply_markup=admin_kb()
            )
        finally:
            conn.close()
        del admin_state[ADMIN_ID]


# ── ⬅️ Ба менюи асосӣ ─────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "⬅️ Ба менюи асосӣ")
def back_to_main(msg):
    if msg.chat.id != ADMIN_ID:
        return
    bot.send_message(msg.chat.id, "🏠 Менюи асосӣ:", reply_markup=main_kb())

# ============================================================
#  📱  КЛИЕНТ РОУТИНГ
# ============================================================
CLIENT_BTNS = {
    "📋 Менюи таомҳо",
    "🛒 Сабади харид",
    "📅 Брон кардани стол",
    "👤 Профили ман",
    "👑 Саҳифаи Админ",
}

@bot.message_handler(func=lambda m: m.text in CLIENT_BTNS)
def client_router(msg):
    uid = msg.chat.id

    if msg.text == "👑 Саҳифаи Админ":
        if uid == ADMIN_ID:
            bot.send_message(uid, "👑 *Панели Админ:*", parse_mode="Markdown", reply_markup=admin_kb())
        else:
            bot.send_message(uid, "❌ Танҳо Админ дастрасӣ дорад!", reply_markup=main_kb())
        return

    if not check_session(uid):
        return

    if msg.text == "📋 Менюи таомҳо":
        show_categories(uid)

    elif msg.text == "🛒 Сабади харид":
        if not is_open():
            bot.send_message(
                uid,
                f"🔒 *Ресторан баста аст!*\n\n"
                f"Соатҳои кор: ҳар рӯз *{OPEN_HOUR:02d}:00 — {CLOSE_HOUR:02d}:00*\n"
                "Фардо субҳ биед 😊",
                parse_mode="Markdown",
                reply_markup=main_kb()
            )
            return
        show_cart(uid)

    elif msg.text == "📅 Брон кардани стол":
        if not is_open():
            bot.send_message(
                uid,
                f"🔒 *Низоми брон баста аст!*\n\n"
                f"Соатҳои кор: *{OPEN_HOUR:02d}:00 — {CLOSE_HOUR:02d}:00*",
                parse_mode="Markdown",
                reply_markup=main_kb()
            )
            return
        start_booking(uid)

    elif msg.text == "👤 Профили ман":
        show_profile(msg)

# ============================================================
#  📋  МЕНЮ — КАТЕГОРИЯҲО ВА ТАОМҲО
# ============================================================
def show_categories(uid: int):
    mk = types.InlineKeyboardMarkup(row_width=1)
    for cat in CATEGORIES:
        mk.add(types.InlineKeyboardButton(cat, callback_data=f"cat|{cat}"))
    bot.send_message(uid, "📋 *Категорияро интихоб кунед:*", parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cat|") or c.data == "back_cats")
def cb_category(call):
    uid = call.message.chat.id
    if not check_session(uid):
        return

    if call.data == "back_cats":
        mk = types.InlineKeyboardMarkup(row_width=1)
        for cat in CATEGORIES:
            mk.add(types.InlineKeyboardButton(cat, callback_data=f"cat|{cat}"))
        try:
            bot.edit_message_text(
                "📋 *Категорияро интихоб кунед:*",
                uid, call.message.message_id,
                parse_mode="Markdown",
                reply_markup=mk
            )
        except:
            show_categories(uid)
        return

    cat_name = call.data.split("|", 1)[1]
    conn     = get_conn()
    c        = conn.cursor()
    c.execute("SELECT name, price, image_id FROM menu WHERE category = ?", (cat_name,))
    items = c.fetchall()
    conn.close()

    if not items:
        bot.answer_callback_query(call.id, "Дар ин категория таом мавҷуд нест.")
        return

    bot.answer_callback_query(call.id)

    for name, price, img_id in items:
        mk = types.InlineKeyboardMarkup(row_width=2)
        mk.add(
            types.InlineKeyboardButton("➖ ...", callback_data=f"rem|{name}"),
            types.InlineKeyboardButton("➕ Илова",    callback_data=f"add|{name}"),
        )
        caption = f"🍽 *{name}*\n💰 Нарх: {price:.2f} сомонӣ"
        if img_id:
            try:
                bot.send_photo(uid, img_id, caption=caption, parse_mode="Markdown", reply_markup=mk)
                continue
            except:
                pass
        bot.send_message(uid, caption, parse_mode="Markdown", reply_markup=mk)

    back_mk = types.InlineKeyboardMarkup()
    back_mk.add(types.InlineKeyboardButton("⬅️ Ба қафо", callback_data="back_cats"))
    bot.send_message(uid, "──────────────────", reply_markup=back_mk)


# ── Сабад: илова / гирифтан ───────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("add|") or c.data.startswith("rem|"))
def cb_cart(call):
    uid = call.message.chat.id
    if not check_session(uid):
        return
    action, food_name = call.data.split("|", 1)
    conn = get_conn()
    c    = conn.cursor()

    if action == "add":
        c.execute("SELECT price FROM menu WHERE name = ?", (food_name,))
        row = c.fetchone()
        if row:
            c.execute(
                "INSERT INTO cart (user_id, food, qty, price) VALUES (?, ?, 1, ?)",
                (uid, food_name, row[0])
            )
            conn.commit()
            bot.answer_callback_query(call.id, f"✅ {food_name} ба сабад илова шуд!")
        else:
            bot.answer_callback_query(call.id, "❌ Таом ёфт нашуд.")
    else:
        c.execute(
            "SELECT rowid FROM cart WHERE user_id = ? AND food = ? LIMIT 1",
            (uid, food_name)
        )
        row = c.fetchone()
        if row:
            c.execute("DELETE FROM cart WHERE rowid = ?", (row[0],))
            conn.commit()
            bot.answer_callback_query(call.id, f"➖ {food_name} аз сабад гирифта шуд.")
        else:
            bot.answer_callback_query(call.id, "🛒 Ин таом дар сабади шумо нест!")
    conn.close()

# ============================================================
#  🛒  САБАДИ ХАРИД
# ============================================================
def show_cart(uid: int):
    conn = get_conn()
    c    = conn.cursor()
    c.execute(
        "SELECT food, SUM(qty), price FROM cart WHERE user_id = ? GROUP BY food, price",
        (uid,)
    )
    items = c.fetchall()
    conn.close()

    if not items:
        bot.send_message(uid, "🛒 Сабади харидатон холӣ аст.", reply_markup=main_kb())
        return

    txt   = "🛒 *Сабади харидатон:*\n\n"
    total = 0
    for food, qty, price in items:
        sub    = qty * price
        total += sub
        txt   += f"• {food}  ×{qty}  =  {sub:.2f} смн\n"
    txt += f"\n💰 *Ҷамъ: {total:.2f} сомонӣ*"

    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(
        types.InlineKeyboardButton("🙋 Барои худам",   callback_data="co_self"),
        types.InlineKeyboardButton("🎁 Ҳамчун тӯҳфа", callback_data="co_gift"),
        types.InlineKeyboardButton("🗑️ Тоза кардан",  callback_data="co_clear"),
    )
    bot.send_message(uid, txt, parse_mode="Markdown", reply_markup=mk)


@bot.callback_query_handler(func=lambda c: c.data in ("co_self", "co_gift", "co_clear"))
def cb_checkout(call):
    uid = call.message.chat.id
    if not check_session(uid):
        return
    if not is_open():
        bot.answer_callback_query(
            call.id,
            f"🔒 Ресторан баста аст! {OPEN_HOUR:02d}:00 — {CLOSE_HOUR:02d}:00",
            show_alert=True
        )
        return

    if call.data == "co_clear":
        conn = get_conn()
        c    = conn.cursor()
        c.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
        conn.commit()
        conn.close()
        try:
            bot.delete_message(uid, call.message.message_id)
        except:
            pass
        bot.send_message(uid, "🗑️ Сабади харид тоза карда шуд.", reply_markup=main_kb())
        return

    order_mode[uid] = "self" if call.data == "co_self" else "gift"
    try:
        bot.delete_message(uid, call.message.message_id)
    except:
        pass
    ask_phone(uid)


# ── Телефон сӯрастан ──────────────────────────────────────
def ask_phone(uid: int):
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT phone FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        after_phone(uid)
        return
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(types.KeyboardButton("📱 Тасдиқи рақами телефон", request_contact=True))
    m = bot.send_message(uid, "📱 Лутфан рақами телефони худро тасдиқ кунед:", reply_markup=mk)
    bot.register_next_step_handler(m, save_phone)

def save_phone(msg):
    uid = msg.chat.id
    if not msg.contact:
        bot.send_message(uid, "❌ Тасдиқ нашуд. Лутфан /start -ро пахш кунед.", reply_markup=main_kb())
        return
    conn = get_conn()
    c    = conn.cursor()
    c.execute("UPDATE users SET phone = ? WHERE id = ?", (msg.contact.phone_number, uid))
    conn.commit()
    conn.close()
    after_phone(uid)

def after_phone(uid: int):
    if order_mode.get(uid) == "gift":
        m = bot.send_message(uid, "👤 Рақами телефони қабулкунандаи тӯҳфаро ворид кунед:")
        bot.register_next_step_handler(m, process_gift_receiver)
    else:
        ask_service(uid)

# ── Тӯҳфа: қабулкунандаро муайян кардан ──────────────────
def process_gift_receiver(msg):
    uid   = msg.chat.id
    phone = (msg.text or "").strip()

    phone_clean = re.sub(r"[^\d+]", "", phone)
    if len(phone_clean) < 9:
        m = bot.send_message(uid, "❌ Рақами телефон нодуруст! Дубора ворид кунед:")
        bot.register_next_step_handler(m, process_gift_receiver)
        return

    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT id FROM users WHERE phone = ? OR phone = ?", (phone, phone_clean))
    row = c.fetchone()
    conn.close()

    if not row:
        bot.send_message(
            uid,
            "❌ Ин рақам дар боти мо рӯйхат нашудааст!\n"
            "Фармоиш бекор карда шуд.",
            reply_markup=main_kb()
        )
        return

    receiver_id = row[0]

    if receiver_id == uid:
        bot.send_message(uid, "❌ Шумо наметавонед ба худатон тӯҳфа фиристед!", reply_markup=main_kb())
        return

    code = gen_code()
    pending_orders[receiver_id] = {"sender_id": uid, "code": code}

    bot.send_message(uid, "⏳ Тасдиқ шуд. Мунтазири локатсияи қабулкунанда...", reply_markup=main_kb())

    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(types.KeyboardButton("📍 Фиристодани Жонли Локатсия (Live)", request_location=True))
    bot.send_message(
        receiver_id,
        "🎁 Салом! Дӯстатон мехоҳад ба шумо тӯҳфа фиристад.\n\n"
        "⚠️ *МУҲИМ:* Илтимос, фақат **Жонли жойлашувни (Share My Live Location)** юборинг. "
        "Харитадан нуқта белгилаб юборилса бот қабул қилмайди!",
        reply_markup=mk
    )

# ── Намуди хизмат ─────────────────────────────────────────
def ask_service(uid: int):
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add("🛵 Дастраскунӣ (Доставка)", "🍽️ Дар зали ресторан")
    m = bot.send_message(uid, "Намуди хизматрасониро интихоб кунед:", reply_markup=mk)
    bot.register_next_step_handler(m, save_service)

def save_service(msg):
    uid = msg.chat.id
    if not check_session(uid):
        return
    if msg.text not in ("🛵 Дастраскунӣ (Доставка)", "🍽️ Дар зали ресторан"):
        bot.send_message(uid, "❌ Лутфан аз тугмаҳо интихоб кунед.", reply_markup=main_kb())
        return
    service_type[uid] = msg.text
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(types.KeyboardButton("📍 Фиристодани Жонли Локатсия (Live)", request_location=True))
    bot.send_message(
        uid, 
        "📍 Жонли жойлашувингизни (**Share My Live Location**) юборинг:\n\n"
        "⚠️ *Эслатма:* Харитадан нуқта танлаб юборилган оддий локациялар рад этилади!", 
        reply_markup=mk
    )

# ============================================================
#  📍  ЛОКАТСИЯ (АЛДОВГА ҚАРШИ ТЕКШИРУВ БИЛАН)
# ============================================================
@bot.message_handler(content_types=["location"])
def handle_location(msg):
    uid = msg.chat.id
    lat = msg.location.latitude
    lon = msg.location.longitude

    # 🛑 ХАВФСИЗЛИК ТЕКШИРУВИ: Паёми жонли локация (Live Location) эканлигини аниқлаш
    # Агар жонли локация бўлмаса, унда 'live_period' ёки 'heading' параметрлари бўлмайди.
    # Шунингдек, фойдаланувчи ҳақиқий телефондан "Share Live" қилганда ботга келадиган 
    # хабар объектида сохта жойлашувлардан ҳимоя созламалари бўлади.
    is_live = msg.location.live_period is not None

    if not is_live:
        bot.send_message(
            uid,
            "❌ *РАД ЭТИЛДИ! (ОДДИЙ ЛОКАЦИЯ)*\n\n"
            "Харитадан нуқта белгилаб юбориш тақиқланган. "
            "Илтимос, тугмани босиб **Жонли Жойлашув (Share My Live Location)** юборинг!",
            parse_mode="Markdown"
        )
        return

    # ── Тӯҳфа: қабулкунандаи локатсия ────────────────────
    if uid in pending_orders:
        info = pending_orders.pop(uid)

        if not in_dushanbe(lat, lon):
            bot.send_message(
                uid,
                "❌ Шумо берун аз ҳудуди Душанбе ҳастед!\n"
                "Хизматрасонӣ дар ин минтақа мавҷуд нест.",
                reply_markup=main_kb()
            )
            bot.send_message(
                info["sender_id"],
                "❌ Қабулкунанда берун аз ҳудуди хизматрасонӣ аст.\n"
                "Фармоиш бекор карда шуд.",
                reply_markup=main_kb()
            )
            return

        finalize_order(
            sender_id   = info["sender_id"],
            receiver_id = uid,
            o_type      = "🎁 Тӯҳфа",
            details     = f"Локатсия (Жонли): {lat:.5f}, {lon:.5f}",
            code        = info["code"]
        )
        return

    # ── Одди фармоиш ──────────────────────────────────────
    stype = service_type.pop(uid, None)
    if not stype:
        return

    # 1. Душанбе ҳудуди текшируви
    if not in_dushanbe(lat, lon):
        conn = get_conn()
        c    = conn.cursor()
        c.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
        conn.commit()
        conn.close()
        bot.send_message(
            uid,
            "❌ *ФИРЕБ ОШКОР ШУД!*\n\n"
            "Сиз жонли локация юбордингиз, аммо ҳозирда Душанбе ҳудудидан ташқаридасиз!\n"
            "Сабади харидатон автоматӣ тоза карда шуд.",
            parse_mode="Markdown",
            reply_markup=main_kb()
        )
        return

    # 2. Дар зал — масофа текшируви
    if stype == "🍽️ Дар зали ресторан":
        dist = haversine(lat, lon, RESTAURANT_LAT, RESTAURANT_LON)
        if dist > 150:
            conn = get_conn()
            c    = conn.cursor()
            c.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
            conn.commit()
            conn.close()
            bot.send_message(
                uid,
                f"❌ *ФИРЕБ ОШКОР ШУД!*\n\n"
                f"Шумо дар зали ресторан нестед!\n"
                f"Масофа: {dist:.0f} метр (иҷозат: 150м)\n"
                "Сабади харидатон тоза карда шуд.",
                parse_mode="Markdown",
                reply_markup=main_kb()
            )
            return
        finalize_order(uid, uid, "🍽️ Дар зал", f"Зал (Жонли масофа: {dist:.0f}м)")

    # 3. Доставка
    else:
        finalize_order(uid, uid, "🛵 Доставка", f"Локатсия (Жонли): {lat:.5f}, {lon:.5f}")


def finalize_order(sender_id, receiver_id, o_type, details, code=None):
    code     = code or gen_code()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT food, qty, price FROM cart WHERE user_id = ?", (sender_id,))
    cart = c.fetchall()

    if not cart:
        conn.close()
        bot.send_message(sender_id, "🛒 Сабади харид холӣ аст.", reply_markup=main_kb())
        return

    total    = sum(q * p for _, q, p in cart)
    cart_txt = "\n".join(f"  • {f} ×{q} = {q*p:.2f} смн" for f, q, p in cart)

    c.execute("SELECT phone FROM users WHERE id = ?", (sender_id,))
    pr    = c.fetchone()
    phone = pr[0] if pr else "Номаълум"

    c.execute(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, '🆕 Нав', ?)",
        (code, sender_id, receiver_id, o_type, details, total, date_str)
    )
    c.execute("DELETE FROM cart WHERE user_id = ?", (sender_id,))
    conn.commit()
    conn.close()

    bot.send_message(
        sender_id,
        f"✅ *Фармоиши шумо қабул шуд!*\n\n"
        f"🆔 Код: `{code}`\n"
        f"📦 Намуд: {o_type}\n\n"
        f"{cart_txt}\n\n"
        f"💰 *Ҷамъ: {total:.2f} сомонӣ*\n\n"
        "Админ ба зудӣ бо шумо тамос мегирад. 😊",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

    bot.send_message(
        ADMIN_ID,
        f"🔔 *ФАРМОИШИ НАВ!*\n\n"
        f"🕐 {date_str}\n"
        f"👤 ID: `{sender_id}` | 📱 {phone}\n"
        f"📦 Намуд: {o_type}\n"
        f"📍 {details}\n\n"
        f"{cart_txt}\n\n"
        f"💰 Ҷамъ: *{total:.2f} сомонӣ*\n"
        f"🆔 Код: `{code}`",
        parse_mode="Markdown"
    )

# ============================================================
#  📅  БРОН КАРДАНИ СТОЛ
# ============================================================
def start_booking(uid: int):
    booking_state[uid] = {}
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT phone FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    conn.close()

    if row and row[0]:
        booking_state[uid]["phone"] = row[0]
        ask_booking_guests(uid)
    else:
        mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        mk.add(types.KeyboardButton("📱 Тасдиқи рақами телефон", request_contact=True))
        m = bot.send_message(uid, "📱 Барои брон аввал рақами телефонатонро тасдиқ кунед:", reply_markup=mk)
        bot.register_next_step_handler(m, save_phone_booking)

def save_phone_booking(msg):
    uid = msg.chat.id
    if not msg.contact:
        bot.send_message(uid, "❌ Тасдиқ нашуд. /start -ро пахш кунед.", reply_markup=main_kb())
        return
    phone = msg.contact.phone_number
    conn  = get_conn()
    c     = conn.cursor()
    c.execute("UPDATE users SET phone = ? WHERE id = ?", (phone, uid))
    conn.commit()
    conn.close()
    booking_state[uid]["phone"] = phone
    ask_booking_guests(uid)

def ask_booking_guests(uid: int):
    m = bot.send_message(
        uid,
        "👥 Шумораи меҳмононро ворид кунед (танҳо рақам):",
        reply_markup=types.ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(m, step_guests)

def step_guests(msg):
    uid = msg.chat.id
    if not msg.text or not msg.text.strip().isdigit() or int(msg.text.strip()) < 1:
        m = bot.send_message(uid, "❌ Хато! Танҳо мусбат рақам ворид кунед:")
        bot.register_next_step_handler(m, step_guests)
        return
    guests = int(msg.text.strip())
    if guests > 50:
        m = bot.send_message(uid, "❌ Барои гурӯҳи бузург бо администратор тамос гиред. Максимум 50 нафар:")
        bot.register_next_step_handler(m, step_guests)
        return
    booking_state[uid]["guests"] = guests
    m = bot.send_message(uid, "📅 Рӯзи бронро ворид кунед (масалан: 15):")
    bot.register_next_step_handler(m, step_day)

def step_day(msg):
    uid = msg.chat.id
    if not msg.text or not msg.text.strip().isdigit():
        m = bot.send_message(uid, "❌ Танҳо рақам! Масалан: 15")
        bot.register_next_step_handler(m, step_day)
        return
    day = int(msg.text.strip())
    if not 1 <= day <= 31:
        m = bot.send_message(uid, "❌ Рӯз байни 1 ва 31 бошад:")
        bot.register_next_step_handler(m, step_day)
        return
    booking_state[uid]["day"] = day
    m = bot.send_message(uid, "🗓️ Моҳро бо рақам ворид кунед (масалан: июн = 6):")
    bot.register_next_step_handler(m, step_month)

def step_month(msg):
    uid = msg.chat.id
    if not msg.text or not msg.text.strip().isdigit():
        m = bot.send_message(uid, "❌ Танҳо рақам! Масалан: 6")
        bot.register_next_step_handler(m, step_month)
        return

    month = int(msg.text.strip())
    if not 1 <= month <= 12:
        m = bot.send_message(uid, "❌ Моҳ байни 1 ва 12 бошад:")
        bot.register_next_step_handler(m, step_month)
        return

    day  = booking_state[uid]["day"]
    now  = datetime.now()
    year = now.year

    if month < now.month or (month == now.month and day < now.day):
        year += 1

    max_day = calendar.monthrange(year, month)[1]
    if day > max_day:
        bot.send_message(
            uid,
            f"❌ Дар моҳи {month} рӯзи {day} мавҷуд нест (максимум {max_day})!\n"
            "Аз нав /start -ро пахш кунед.",
            reply_markup=main_kb()
        )
        booking_state.pop(uid, None)
        return

    try:
        b_date = datetime(year, month, day)
    except ValueError:
        bot.send_message(uid, "❌ Санаи нодуруст. /start -ро пахш кунед.", reply_markup=main_kb())
        booking_state.pop(uid, None)
        return

    booking_state[uid]["valid_date"] = b_date.strftime("%Y-%m-%d")
    m = bot.send_message(uid, "⏱️ Вақти омаданро ворид кунед (масалан: 18:00):")
    bot.register_next_step_handler(m, step_time)

def step_time(msg):
    uid = msg.chat.id
    ts  = (msg.text or "").strip()

    if not valid_time(ts):
        m = bot.send_message(uid, "❌ Формати вақт нодуруст аст! Масалан: 18:00")
        bot.register_next_step_handler(m, step_time)
        return

    data = booking_state.pop(uid, None)
    if not data:
        bot.send_message(uid, "❌ Сессия ба охир расид. /start -ро пахш кунед.", reply_markup=main_kb())
        return

    conn = get_conn()
    c    = conn.cursor()
    c.execute(
        "INSERT INTO bookings (user_id, guests, booking_date, time_slot, phone, status) "
        "VALUES (?, ?, ?, ?, ?, 'Интизор 🟡')",
        (uid, data["guests"], data["valid_date"], ts, data["phone"])
    )
    conn.commit()
    conn.close()

    bot.send_message(
        uid,
        f"✅ *Дархости брон қабул шуд!*\n\n"
        f"👥 Меҳмонон: {data['guests']} нафар\n"
        f"📅 Сана: {data['valid_date']}\n"
        f"⏱️ Вақт: {ts}\n"
        f"📱 Телефон: {data['phone']}\n\n"
        "Администратор ба зудӣ бо шумо тамос мегирад. 😊",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

    bot.send_message(
        ADMIN_ID,
        f"📅 *ДАРХОСТИ БРОНИИ НАВ!*\n\n"
        f"👤 ID: `{uid}`\n"
        f"📱 Телефон: {data['phone']}\n"
        f"👥 Меҳмонон: {data['guests']} нафар\n"
        f"📅 Сана: {data['valid_date']}\n"
        f"⏱️ Вақт: {ts}",
        parse_mode="Markdown"
    )

# ============================================================
#  👤  ПРОФИЛ
# ============================================================
def show_profile(msg):
    uid  = msg.chat.id
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT phone FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    conn.close()
    phone = row[0] if row and row[0] else "Рӯйхат нашудааст ❌"
    name  = msg.from_user.first_name or "—"
    bot.send_message(
        uid,
        f"👤 *Профили шумо:*\n\n"
        f"📛 Ном: {name}\n"
        f"🆔 ID: `{uid}`\n"
        f"📱 Телефон: {phone}",
        parse_mode="Markdown"
    )

# ============================================================
#  📊  ҲИСОБОТИ РӮЗОНА — ҳар кеч соат 21:00
# ============================================================
def daily_report_loop():
    while True:
        now      = datetime.now()
        next_run = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        wait_sec = (next_run - now).total_seconds()
        time.sleep(wait_sec)

        try:
            conn  = get_conn()
            c     = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")

            c.execute(
                "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders WHERE date_time LIKE ?",
                (f"{today}%",)
            )
            cnt, earned = c.fetchone()

            c.execute(
                "SELECT type, COUNT(*) FROM orders WHERE date_time LIKE ? GROUP BY type",
                (f"{today}%",)
            )
            by_type = c.fetchall()
            conn.close()

            txt = (
                f"📊 *Ҳисоботи рӯзонаи {today}:*\n\n"
                f"📦 Фармоишҳо: *{cnt}* та\n"
                f"💰 Даромад: *{earned:.2f}* сомонӣ\n"
            )
            if by_type:
                txt += "\n📋 *Аз рӯи намуд:*\n"
                for otype, ocnt in by_type:
                    txt += f"  • {otype}: {ocnt} та\n"

            txt += "\n✅ Рӯзи хуб!" if cnt > 0 else "\n😕 Имрӯз фармоиш набуд."
            bot.send_message(ADMIN_ID, txt, parse_mode="Markdown")

        except Exception as e:
            print(f"[Хатои ҳисобот]: {e}")

# ============================================================
#  🚫  ФИЛТРИ ПАЁМҲОИ БЕҲУДА
# ============================================================
SPAM_TYPES = ["voice", "video", "photo", "document", "sticker", "audio", "video_note"]

@bot.message_handler(content_types=SPAM_TYPES)
def handle_spam(msg):
    try:
        bot.delete_message(msg.chat.id, msg.message_id)
    except:
        pass
    bot.send_message(
        msg.chat.id,
        "⚠️ Лутфан танҳо аз тугмаҳои мавҷуда истифода баред!",
        reply_markup=main_kb()
    )

@bot.message_handler(func=lambda m: True)
def handle_unknown(msg):
    uid = msg.chat.id

    if uid == ADMIN_ID and ADMIN_ID in admin_state:
        admin_add_steps(msg)
        return

    try:
        bot.delete_message(uid, msg.message_id)
    except:
        pass

    mk = admin_kb() if uid == ADMIN_ID else main_kb()
    bot.send_message(uid, "⚠️ Лутфан аз тугмаҳои мавҷуда истифода баред!", reply_markup=mk)

# ============================================================
#  🚀  ИШГА ТУШИРИШ
# ============================================================
if __name__ == "__main__":
    print("✅ Боти ресторан оғоз шуд!")

    t = threading.Thread(target=daily_report_loop, daemon=True)
    t.start()

    bot.infinity_polling(timeout=30, long_polling_timeout=20)
