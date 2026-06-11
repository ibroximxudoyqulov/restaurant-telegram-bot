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
TOKEN    = os.environ.get("BOT_TOKEN")
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

STATUS_LIST = [
    "🆕 Дар навбат",
    "👨‍🍳 Тайёр карда мешавад",
    "✅ Тайёр аст",
    "🛵 Дар роҳ аст",
    "✔️ Расид",
]

# ============================================================
#  🗄️  БАЗА МАЪЛУМОТ
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
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
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
            status      TEXT DEFAULT '🆕 Дар навбат',
            date_time   TEXT
        )
    """)

    c.execute("SELECT COUNT(*) FROM menu")
    if c.fetchone()[0] == 0:
        default_menu = [
            ("Оши палови тоҷикӣ",  40.0, "🍲 Таомҳои миллии гарм", None),
            ("Шӯрбои гӯсфандӣ",    35.0, "🍲 Таомҳои миллии гарм", None),
            ("Қорутоб",            45.0, "🍲 Таомҳои миллии гарм", None),
            ("Сихкабоби говӣ",     25.0, "🍢 Кабобҳо",             None),
            ("Хӯриши Шакароб",     15.0, "🥗 Хӯришҳо ва Газакҳо", None),
            ("Чои кабуд бо лимӯ",   5.0, "🥤 Нӯшокиҳои миллӣ",   None),
        ]
        c.executemany(
            "INSERT INTO menu (name, price, category, image_id) VALUES (?, ?, ?, ?)",
            default_menu
        )

    conn.commit()
    conn.close()

init_db()

# ============================================================
#  📦  ҲОЛАТҲОИ МУВАҚҚАТӢ
# ============================================================
pending_orders = {}   # тӯҳфа: receiver_id -> {sender_id, code}
admin_state    = {}   # admin қадамлари
booking_state  = {}   # брон кардан: user_id -> {...}
order_mode     = {}   # "self" ё "gift"
service_type   = {}   # "dostavka" ё "zal"

# ============================================================
#  🛠️  ЁРДАМЧИ ФУНКСИЯҲО
# ============================================================
def is_open() -> bool:
    return OPEN_HOUR <= datetime.now().hour < CLOSE_HOUR

def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def in_dushanbe(lat, lon) -> bool:
    return 38.48 <= lat <= 38.65 and 68.68 <= lon <= 68.90

def gen_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def valid_time(ts: str) -> bool:
    return bool(re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", ts.strip()))

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
    if row and (now - row[0]) > SESSION_TIMEOUT:
        c.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
        c.execute("UPDATE users SET last_activity = ? WHERE id = ?", (now, uid))
        conn.commit()
        conn.close()
        bot.send_message(
            uid,
            "⏱️ *Сессия ба охир расид.*\n"
            "Шумо 10 дақиқа фаъол набудед.\n"
            "Сабади харид автоматӣ тоза карда шуд.\n"
            "Лутфан аз нав /start пахш кунед.",
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

def get_phone(uid: int):
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT phone FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else None

# ============================================================
#  ⌨️  КЛАВИАТУРАҲО
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
    m.add("🗑️ Нест кардани таом", "📨 Тағйири статус")
    m.add("⬅️ Ба менюи асосӣ")
    return m

# ============================================================
#  /start
# ============================================================
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.chat.id
    clear_state(uid)
    admin_state.pop(uid, None)
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
        "Ба боти расмии ресторани мо хуш омадед.\n"
        "Лутфан хизматро интихоб кунед 👇",
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
    "📨 Тағйири статус",
    "⬅️ Ба менюи асосӣ",
}

@bot.message_handler(func=lambda m: m.text in ADMIN_BTNS)
def admin_router(msg):
    uid = msg.chat.id
    if uid != ADMIN_ID:
        bot.send_message(uid, "❌ Танҳо Админ дастрасӣ дорад!", reply_markup=main_kb())
        return

    txt = msg.text

    if txt == "👑 Саҳифаи Админ":
        bot.send_message(uid, "👑 *Панели Админ:*", parse_mode="Markdown", reply_markup=admin_kb())

    elif txt == "⬅️ Ба менюи асосӣ":
        bot.send_message(uid, "🏠 Менюи асосӣ:", reply_markup=main_kb())

    elif txt == "📊 Омори умумӣ":
        conn = get_conn()
        c    = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders")
        cnt, earned = c.fetchone()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders WHERE date_time LIKE ?", (f"{today}%",))
        t_cnt, t_earn = c.fetchone()
        c.execute("SELECT COUNT(*) FROM bookings")
        bk = c.fetchone()[0]
        conn.close()
        bot.send_message(
            uid,
            f"📊 *Омори умумии ресторан:*\n\n"
            f"👤 Мизоҷон: *{users}* нафар\n"
            f"📦 Ҷамъи фармоишҳо: *{cnt}* та\n"
            f"💰 Ҷамъи даромад: *{earned:.2f}* сомонӣ\n\n"
            f"📅 Имрӯз фармоишҳо: *{t_cnt}* та\n"
            f"💵 Имрӯз даромад: *{t_earn:.2f}* сомонӣ\n"
            f"🪑 Ҷамъи бронҳо: *{bk}* та",
            parse_mode="Markdown",
            reply_markup=admin_kb()
        )

    elif txt == "📦 Рӯйхати фармоишҳо":
        conn = get_conn()
        c    = conn.cursor()
        c.execute(
            "SELECT code, total, status, type, date_time "
            "FROM orders ORDER BY date_time DESC LIMIT 10"
        )
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(uid, "📭 Ҳоло фармоиш мавҷуд нест.", reply_markup=admin_kb())
            return
        text = "📦 *10 фармоиши охирин:*\n\n"
        for code, total, status, otype, dt in rows:
            text += f"• `{code}` | {total:.0f} смн | {status}\n  📦{otype} | 🕐{dt}\n\n"
        bot.send_message(uid, text, parse_mode="Markdown", reply_markup=admin_kb())

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
            bot.send_message(uid, "📭 Ҳоло брон мавҷуд нест.", reply_markup=admin_kb())
            return
        text = "📅 *Рӯйхати бронҳо:*\n\n"
        for bid, bdate, btime, guests, phone, status in rows:
            text += (
                f"• ID:{bid} | 📅{bdate} ⏱️{btime}\n"
                f"  👥{guests} нафар | 📱{phone}\n"
                f"  {status}\n\n"
            )
        bot.send_message(uid, text, parse_mode="Markdown", reply_markup=admin_kb())

    elif txt == "➕ Илова кардани таом":
        admin_state[uid] = {"step": "add_name"}
        bot.send_message(uid, "📝 Номи таоми навро ворид кунед:", reply_markup=types.ReplyKeyboardRemove())

    elif txt == "🗑️ Нест кардани таом":
        conn = get_conn()
        c    = conn.cursor()
        c.execute("SELECT id, name, price FROM menu ORDER BY category, name")
        items = c.fetchall()
        conn.close()
        if not items:
            bot.send_message(uid, "📭 Меню холӣ аст.", reply_markup=admin_kb())
            return
        mk = types.InlineKeyboardMarkup(row_width=1)
        for fid, fname, fprice in items:
            mk.add(types.InlineKeyboardButton(
                f"🗑️ {fname} — {fprice:.0f} смн",
                callback_data=f"delfood|{fid}"
            ))
        bot.send_message(uid, "Нест кардани таомро интихоб кунед:", reply_markup=mk)

    elif txt == "📨 Тағйири статус":
        conn = get_conn()
        c    = conn.cursor()
        c.execute(
            "SELECT code, status, total FROM orders "
            "WHERE status != '✔️ Расид' "
            "ORDER BY date_time DESC LIMIT 15"
        )
        rows = c.fetchall()
        conn.close()
        if not rows:
            bot.send_message(uid, "✅ Ҳамаи фармоишҳо иҷро шудаанд.", reply_markup=admin_kb())
            return
        mk = types.InlineKeyboardMarkup(row_width=1)
        for code, status, total in rows:
            mk.add(types.InlineKeyboardButton(
                f"📦 {code} | {total:.0f}смн | {status}",
                callback_data=f"chst|{code}"
            ))
        bot.send_message(uid, "Статусро тағйир диҳед:", reply_markup=mk)


# ── Таом нест кардан ─────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("delfood|"))
def cb_delete_food(call):
    if call.message.chat.id != ADMIN_ID:
        return
    fid  = int(call.data.split("|")[1])
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT name FROM menu WHERE id = ?", (fid,))
    row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "❌ Таом ёфт нашуд.")
        conn.close()
        return
    fname = row[0]
    c.execute("DELETE FROM menu WHERE id = ?", (fid,))
    conn.commit()
    bot.answer_callback_query(call.id, f"✅ {fname} нест карда шуд!")
    c.execute("SELECT id, name, price FROM menu ORDER BY category, name")
    items = c.fetchall()
    conn.close()
    if not items:
        try:
            bot.edit_message_text("📭 Меню холӣ шуд.", call.message.chat.id, call.message.message_id)
        except:
            pass
        return
    mk = types.InlineKeyboardMarkup(row_width=1)
    for fi, fn, fp in items:
        mk.add(types.InlineKeyboardButton(f"🗑️ {fn} — {fp:.0f} смн", callback_data=f"delfood|{fi}"))
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=mk)
    except:
        pass


# ── Статус тағйир додан ──────────────────────────────────────
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
            f"📦 Фармоиш `{code}` барои статуси нав:",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=mk
        )
    except:
        pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("setst|"))
def cb_set_status(call):
    if call.message.chat.id != ADMIN_ID:
        return
    parts      = call.data.split("|", 2)
    code       = parts[1]
    new_status = parts[2]
    conn       = get_conn()
    c          = conn.cursor()
    c.execute("UPDATE orders SET status = ? WHERE code = ?", (new_status, code))
    c.execute("SELECT user_id FROM orders WHERE code = ?", (code,))
    row = c.fetchone()
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, f"✅ Статус: {new_status}")
    try:
        bot.edit_message_text(
            f"✅ `{code}` — *{new_status}*",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown"
        )
    except:
        pass
    # Мизоҷга хабар
    if row:
        try:
            bot.send_message(
                row[0],
                f"📦 *Ҳолати фармоиши шумо тағйир ёфт!*\n\n"
                f"🆔 Код: `{code}`\n"
                f"📊 Ҳолати нав: *{new_status}*",
                parse_mode="Markdown"
            )
        except:
            pass


# ── Таом илова кардан — қадамҳо ─────────────────────────────
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID and m.chat.id in admin_state)
def admin_add_steps(msg):
    state = admin_state.get(ADMIN_ID, {})
    step  = state.get("step")

    if step == "add_name":
        name = msg.text.strip()
        if len(name) < 2:
            bot.send_message(ADMIN_ID, "❌ Ном хеле кӯтоҳ аст. Аз нав ворид кунед:")
            return
        state["name"] = name
        state["step"] = "add_price"
        bot.send_message(ADMIN_ID, "💰 Нархро ворид кунед (масалан: 35.5):")

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
            bot.send_message(ADMIN_ID, "❌ Нарх нодуруст! Масалан: 35.5")

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
            bot.send_message(ADMIN_ID, "❌ Ин таом аллакай мавҷуд аст!", reply_markup=admin_kb())
        finally:
            conn.close()
        admin_state.pop(ADMIN_ID, None)

# ============================================================
#  📋  РОУТИНГИ МИЗОҶ
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
    if not check_session(uid):
        return

    txt = msg.text

    if txt == "👑 Саҳифаи Админ":
        if uid == ADMIN_ID:
            bot.send_message(uid, "👑 *Панели Админ:*", parse_mode="Markdown", reply_markup=admin_kb())
        else:
            bot.send_message(uid, "❌ Танҳо Админ дастрасӣ дорад!")
        return

    if txt == "📋 Менюи таомҳо":
        show_categories(uid)

    elif txt == "🛒 Сабади харид":
        if not is_open():
            bot.send_message(
                uid,
                f"🔒 *Ресторан баста аст!*\n\n"
                f"Вақти кор: ҳар рӯз аз *{OPEN_HOUR:02d}:00* то *{CLOSE_HOUR:02d}:00*\n"
                "Фардо баргардед 😊",
                parse_mode="Markdown", reply_markup=main_kb()
            )
            return
        show_cart(uid)

    elif txt == "📅 Брон кардани стол":
        if not is_open():
            bot.send_message(
                uid,
                f"🔒 *Системаи брон баста аст!*\n\n"
                f"Вақти кор: аз *{OPEN_HOUR:02d}:00* то *{CLOSE_HOUR:02d}:00*",
                parse_mode="Markdown", reply_markup=main_kb()
            )
            return
        start_booking(uid)

    elif txt == "👤 Профили ман":
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
                parse_mode="Markdown", reply_markup=mk
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
        bot.answer_callback_query(call.id, "Ин категория холӣ аст.")
        return

    bot.answer_callback_query(call.id)

    for name, price, img_id in items:
        mk = types.InlineKeyboardMarkup(row_width=2)
        mk.add(
            types.InlineKeyboardButton("➖ Кам", callback_data=f"rem|{name}"),
            types.InlineKeyboardButton("➕ Илова", callback_data=f"add|{name}"),
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
    back_mk.add(types.InlineKeyboardButton("⬅️ Ба категорияҳо", callback_data="back_cats"))
    bot.send_message(uid, "─────────────────────", reply_markup=back_mk)


@bot.callback_query_handler(func=lambda c: c.data.startswith("add|") or c.data.startswith("rem|"))
def cb_cart_update(call):
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
            "SELECT id FROM cart WHERE user_id = ? AND food = ? LIMIT 1",
            (uid, food_name)
        )
        row = c.fetchone()
        if row:
            c.execute("DELETE FROM cart WHERE id = ?", (row[0],))
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
        bot.send_message(uid, "🛒 Сабади харидии шумо холӣ аст.", reply_markup=main_kb())
        return

    text  = "🛒 *Сабади харидии шумо:*\n\n"
    total = 0
    for food, qty, price in items:
        sub    = qty * price
        total += sub
        text  += f"• {food}  ×{qty}  =  {sub:.2f} смн\n"
    text += f"\n💰 *Ҷамъи умумӣ: {total:.2f} сомонӣ*"

    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(
        types.InlineKeyboardButton("🙋 Барои худам",    callback_data="co_self"),
        types.InlineKeyboardButton("🎁 Ҳамчун тӯҳфа",  callback_data="co_gift"),
        types.InlineKeyboardButton("🗑️ Тоза кардан",   callback_data="co_clear"),
    )
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=mk)


@bot.callback_query_handler(func=lambda c: c.data in ("co_self", "co_gift", "co_clear"))
def cb_checkout(call):
    uid = call.message.chat.id
    if not check_session(uid):
        return
    if not is_open():
        bot.answer_callback_query(
            call.id,
            f"🔒 Ресторан баста аст! Вақти кор: {OPEN_HOUR:02d}:00–{CLOSE_HOUR:02d}:00",
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
        bot.send_message(uid, "🗑️ Сабад тоза карда шуд.", reply_markup=main_kb())
        return

    order_mode[uid] = "self" if call.data == "co_self" else "gift"
    try:
        bot.delete_message(uid, call.message.message_id)
    except:
        pass
    ask_phone_order(uid)


def ask_phone_order(uid: int):
    phone = get_phone(uid)
    if phone:
        after_phone(uid)
        return
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(types.KeyboardButton("📱 Тасдиқи рақам", request_contact=True))
    m = bot.send_message(uid, "📱 Лутфан рақами телефони худро тасдиқ кунед:", reply_markup=mk)
    bot.register_next_step_handler(m, save_phone_order)


def save_phone_order(msg):
    uid = msg.chat.id
    if not msg.contact:
        bot.send_message(uid, "❌ Рақам тасдиқ нашуд. /start пахш кунед.", reply_markup=main_kb())
        return
    # Муҳофизат: рақами тасдиқшуда бояд ба ҳамин корбар тааллуқ дошта бошад
    if msg.contact.user_id and msg.contact.user_id != uid:
        bot.send_message(uid, "❌ Рақами худатонро тасдиқ кунед!", reply_markup=main_kb())
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


def process_gift_receiver(msg):
    uid   = msg.chat.id
    phone = (msg.text or "").strip()

    # Муҳофизат: корбар рақами худашро ворид карда наметавонад
    my_phone = get_phone(uid)
    if my_phone and phone == my_phone:
        bot.send_message(
            uid,
            "❌ Шумо рақами худатонро ворид кардед!\n"
            "Тӯҳфа бояд ба шахси дигар фиристода шавад.",
            reply_markup=main_kb()
        )
        return

    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT id FROM users WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()

    if not row:
        bot.send_message(
            uid,
            "❌ Ин рақам дар бот рӯйхат нашудааст!\n"
            "Фармоиш бекор карда шуд.",
            reply_markup=main_kb()
        )
        return

    receiver_id = row[0]
    code        = gen_code()
    pending_orders[receiver_id] = {"sender_id": uid, "code": code}

    bot.send_message(uid, "⏳ Тасдиқ шуд. Мунтазири локатсияи қабулкунанда...", reply_markup=main_kb())

    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(types.KeyboardButton("📍 Фиристодани локатсия", request_location=True))
    bot.send_message(
        receiver_id,
        "🎁 *Дӯсти шумо тӯҳфа мефиристад!*\n\n"
        "Лутфан локатсияи воқеии худро бифиристед:",
        parse_mode="Markdown",
        reply_markup=mk
    )


def ask_service(uid: int):
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add("🛵 Дастраскунӣ (Доставка)", "🍽️ Дар дохили ресторан")
    m = bot.send_message(uid, "Намуди хизматро интихоб кунед:", reply_markup=mk)
    bot.register_next_step_handler(m, save_service)


def save_service(msg):
    uid = msg.chat.id
    if not check_session(uid):
        return
    if msg.text not in ("🛵 Дастраскунӣ (Доставка)", "🍽️ Дар дохили ресторан"):
        bot.send_message(uid, "❌ Лутфан аз тугмаҳо интихоб кунед.", reply_markup=main_kb())
        return
    service_type[uid] = msg.text
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    mk.add(types.KeyboardButton("📍 Фиристодани локатсия", request_location=True))
    bot.send_message(uid, "📍 Локатсияи воқеии худро бифиристед:", reply_markup=mk)

# ============================================================
#  📍  ЛОКАТСИЯ — МУҲОФИЗАТ БО ЗИНАҲОИ ЗИЁД
# ============================================================
@bot.message_handler(content_types=["location"])
def handle_location(msg):
    uid = msg.chat.id
    lat = msg.location.latitude
    lon = msg.location.longitude

    # ── ТӮҲФА: локатсияи қабулкунанда ────────────────────────
    if uid in pending_orders:
        info = pending_orders.pop(uid)

        # 1. Ҳудуди шаҳр
        if not in_dushanbe(lat, lon):
            bot.send_message(
                uid,
                "❌ Шумо берун аз ҳудуди Душанбе ҳастед!\n"
                "Тӯҳфа қабул карда намешавад.",
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
            sender_id=info["sender_id"],
            receiver_id=uid,
            o_type="Тӯҳфа 🎁",
            details=f"Локатсия: {lat:.5f}, {lon:.5f}",
            code=info["code"]
        )
        return

    # ── ФАРМОИШИ ОДДӢ ──────────────────────────────────────────
    stype = service_type.pop(uid, None)
    if not stype:
        return

    # 1. Ҳудуди шаҳр
    if not in_dushanbe(lat, lon):
        conn = get_conn()
        c    = conn.cursor()
        c.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
        conn.commit()
        conn.close()
        bot.send_message(
            uid,
            "❌ *Шумо берун аз ҳудуди Душанбе ҳастед!*\n\n"
            "Мо танҳо дар дохили шаҳри Душанбе хизмат мерасонем.\n"
            "Сабади харид автоматӣ тоза карда шуд.",
            parse_mode="Markdown",
            reply_markup=main_kb()
        )
        return

    # 2. Дар дохили ресторан — масофа
    if stype == "🍽️ Дар дохили ресторан":
        dist = haversine(lat, lon, RESTAURANT_LAT, RESTAURANT_LON)
        if dist > 150:
            conn = get_conn()
            c    = conn.cursor()
            c.execute("DELETE FROM cart WHERE user_id = ?", (uid,))
            conn.commit()
            conn.close()
            bot.send_message(
                uid,
                f"❌ *ФИРЕБ АНИҚ ШУД!*\n\n"
                f"Шумо дар дохили ресторан нестед.\n"
                f"Масофа: *{dist:.0f} метр* (ҳадди иҷозат: 150м)\n\n"
                "Сабади харид тоза карда шуд.",
                parse_mode="Markdown",
                reply_markup=main_kb()
            )
            return
        finalize_order(uid, uid, "Дар ресторан 🍽️", f"Зал (масофа {dist:.0f}м)")

    # 3. Доставка
    else:
        finalize_order(uid, uid, "Доставка 🛵", f"Локатсия: {lat:.5f}, {lon:.5f}")


def finalize_order(sender_id, receiver_id, o_type, details, code=None):
    code     = code or gen_code()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT food, qty, price FROM cart WHERE user_id = ?", (sender_id,))
    cart = c.fetchall()

    if not cart:
        conn.close()
        bot.send_message(sender_id, "🛒 Сабад холӣ аст.", reply_markup=main_kb())
        return

    total    = sum(q * p for _, q, p in cart)
    cart_txt = "\n".join(f"  • {f} ×{q} = {q*p:.2f} смн" for f, q, p in cart)

    c.execute("SELECT phone FROM users WHERE id = ?", (sender_id,))
    pr    = c.fetchone()
    phone = pr[0] if pr and pr[0] else "Номаълум"

    c.execute(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, '🆕 Дар навбат', ?)",
        (code, sender_id, receiver_id, o_type, details, total, date_str)
    )
    c.execute("DELETE FROM cart WHERE user_id = ?", (sender_id,))
    conn.commit()
    conn.close()

    # Мизоҷга
    bot.send_message(
        sender_id,
        f"✅ *Фармоиши шумо қабул шуд!*\n\n"
        f"🆔 Код: `{code}`\n"
        f"📦 Намуд: {o_type}\n\n"
        f"{cart_txt}\n\n"
        f"💰 *Ҷамъ: {total:.2f} сомонӣ*\n\n"
        "Мо ба зудӣ бо шумо тамос мегирем 😊",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

    # Adminга
    bot.send_message(
        ADMIN_ID,
        f"🔔 *ФАРМОИШИ НАВ!*\n\n"
        f"🕐 {date_str}\n"
        f"👤 ID: `{sender_id}` | 📱 {phone}\n"
        f"📦 {o_type}\n"
        f"📍 {details}\n\n"
        f"{cart_txt}\n\n"
        f"💰 *Ҷамъ: {total:.2f} сомонӣ*\n"
        f"🆔 Код: `{code}`",
        parse_mode="Markdown"
    )

# ============================================================
#  📅  СИСТЕМАИ БРОН КАРДАНИ СТОЛ
# ============================================================
def start_booking(uid: int):
    booking_state[uid] = {}
    phone = get_phone(uid)
    if phone:
        booking_state[uid]["phone"] = phone
        ask_booking_guests(uid)
    else:
        mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        mk.add(types.KeyboardButton("📱 Тасдиқи рақам", request_contact=True))
        m = bot.send_message(uid, "📱 Аввал рақами телефони худро тасдиқ кунед:", reply_markup=mk)
        bot.register_next_step_handler(m, save_phone_booking)


def save_phone_booking(msg):
    uid = msg.chat.id
    if not msg.contact:
        bot.send_message(uid, "❌ Тасдиқ нашуд. /start пахш кунед.", reply_markup=main_kb())
        booking_state.pop(uid, None)
        return
    if msg.contact.user_id and msg.contact.user_id != uid:
        bot.send_message(uid, "❌ Рақами худатонро тасдиқ кунед!", reply_markup=main_kb())
        booking_state.pop(uid, None)
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
    m = bot.send_message(uid, "👥 Шумораи меҳмононро ворид кунед:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(m, step_guests)


def step_guests(msg):
    uid = msg.chat.id
    if not msg.text or not msg.text.strip().isdigit() or int(msg.text.strip()) < 1:
        m = bot.send_message(uid, "❌ Танҳо рақами мусбат ворид кунед!")
        bot.register_next_step_handler(m, step_guests)
        return
    g = int(msg.text.strip())
    if g > 50:
        m = bot.send_message(uid, "❌ Ҳадди аксар 50 нафар. Аз нав ворид кунед:")
        bot.register_next_step_handler(m, step_guests)
        return
    booking_state[uid]["guests"] = g
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
        m = bot.send_message(uid, "❌ Рӯз байни 1 ва 31 бояд бошад:")
        bot.register_next_step_handler(m, step_day)
        return
    booking_state[uid]["day"] = day
    m = bot.send_message(uid, "🗓️ Моҳро бо рақам ворид кунед (масалан: 6 = июн):")
    bot.register_next_step_handler(m, step_month)


def step_month(msg):
    uid = msg.chat.id
    if not msg.text or not msg.text.strip().isdigit():
        m = bot.send_message(uid, "❌ Танҳо рақам! Масалан: 6")
        bot.register_next_step_handler(m, step_month)
        return
    month = int(msg.text.strip())
    if not 1 <= month <= 12:
        m = bot.send_message(uid, "❌ Моҳ байни 1 ва 12 бояд бошад:")
        bot.register_next_step_handler(m, step_month)
        return

    day  = booking_state[uid]["day"]
    now  = datetime.now()
    year = now.year

    # Агар моҳ гузашта бошад — соли оянда
    if month < now.month or (month == now.month and day < now.day):
        year += 1

    # Рӯз ба моҳ мувофиқ аст ё не
    max_day = calendar.monthrange(year, month)[1]
    if day > max_day:
        bot.send_message(
            uid,
            f"❌ Дар моҳи {month} рӯзи {day} вуҷуд надорад (ҳадди аксар: {max_day})!\n"
            "Брон аз нав оғоз мешавад. /start пахш кунед.",
            reply_markup=main_kb()
        )
        booking_state.pop(uid, None)
        return

    try:
        b_date = datetime(year, month, day)
    except ValueError:
        bot.send_message(uid, "❌ Санаи нодуруст. /start пахш кунед.", reply_markup=main_kb())
        booking_state.pop(uid, None)
        return

    booking_state[uid]["valid_date"] = b_date.strftime("%Y-%m-%d")
    m = bot.send_message(uid, "⏱️ Вақти омаданро ворид кунед (масалан: 18:00):")
    bot.register_next_step_handler(m, step_time)


def step_time(msg):
    uid = msg.chat.id
    ts  = (msg.text or "").strip()
    if not valid_time(ts):
        m = bot.send_message(uid, "❌ Формати вақт нодуруст аст. Масалан: 18:00")
        bot.register_next_step_handler(m, step_time)
        return

    data = booking_state.pop(uid, None)
    if not data:
        bot.send_message(uid, "❌ Сессия тамом шуд. /start пахш кунед.", reply_markup=main_kb())
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

    # Мизоҷга тасдиқ
    bot.send_message(
        uid,
        f"✅ *Дархости брони стол қабул шуд!*\n\n"
        f"👥 Меҳмонон: *{data['guests']}* нафар\n"
        f"📅 Сана: *{data['valid_date']}*\n"
        f"⏱️ Вақт: *{ts}*\n"
        f"📱 Телефон: {data['phone']}\n\n"
        "Маъмур бо шумо тамос мегирад 😊",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

    # Adminга хабар
    bot.send_message(
        ADMIN_ID,
        f"📅 *ДАРХОСТИ БРОНИ НАВ:*\n\n"
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
#  📊  ҲИСОБОТИ РӮЗОНА — ҳар шаб соат 21:00
# ============================================================
def daily_report_thread():
    while True:
        now      = datetime.now()
        next_run = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        time.sleep((next_run - now).total_seconds())

        try:
            today = datetime.now().strftime("%Y-%m-%d")
            conn  = get_conn()
            c     = conn.cursor()
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
            c.execute(
                "SELECT COUNT(*) FROM bookings WHERE booking_date = ?",
                (today,)
            )
            bk_today = c.fetchone()[0]
            conn.close()

            text = (
                f"📊 *Ҳисоботи рӯзона — {today}*\n\n"
                f"📦 Фармоишҳо: *{cnt}* та\n"
                f"💰 Даромад: *{earned:.2f}* сомонӣ\n"
                f"🪑 Бронҳо: *{bk_today}* та\n"
            )
            if by_type:
                text += "\n📋 *Аз рӯи намуд:*\n"
                for otype, ocnt in by_type:
                    text += f"  • {otype}: {ocnt} та\n"
            text += "\n✅ Шаби хуш!" if cnt > 0 else "\n😕 Имрӯз фармоиш набуд."

            bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
        except Exception as e:
            print(f"[Хатои ҳисобот]: {e}")

# ============================================================
#  🚫  ФИЛТРИ СПАМ
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
        "⚠️ Лутфан танҳо аз тугмаҳо истифода баред!",
        reply_markup=main_kb()
    )


@bot.message_handler(func=lambda m: True)
def handle_unknown(msg):
    uid = msg.chat.id

    # Агар admin дар ҷараёни илова кардани таом бошад
    if uid == ADMIN_ID and uid in admin_state:
        admin_add_steps(msg)
        return

    try:
        bot.delete_message(uid, msg.message_id)
    except:
        pass

    mk = admin_kb() if uid == ADMIN_ID else main_kb()
    bot.send_message(uid, "⚠️ Лутфан аз тугмаҳо истифода баред!", reply_markup=mk)

# ============================================================
#  🚀  ОҒОЗ
# ============================================================
if __name__ == "__main__":
    print("✅ Боти ресторан оғоз ёфт!")
    t = threading.Thread(target=daily_report_thread, daemon=True)
    t.start()
    bot.infinity_polling(timeout=30, long_polling_timeout=20)
