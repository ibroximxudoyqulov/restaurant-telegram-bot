import sqlite3
import telebot
from telebot import types

# 🔒 SECURITY NOTE: Your token must be hidden on GitHub. 
# Buyers will replace this placeholder with their own official token.
TOKEN = "YOUR_BOT_TOKEN_HERE"
bot = telebot.TeleBot(TOKEN)
DB_NAME = "restaurant_basic.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS cart (user_id INTEGER, food TEXT, qty INTEGER, price REAL)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS menu (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, price REAL)""")
    
    cursor.execute("SELECT COUNT(*) FROM menu")
    if cursor.fetchone()[0] == 0:
        default_menu = [("Burger", 6.0), ("Pizza", 9.0), ("Fries", 3.0), ("Soda", 2.0)]
        cursor.executemany("INSERT INTO menu (name, price) VALUES (?, ?)", default_menu)
    conn.commit()
    conn.close()

init_db()

def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("Menu 🍔", "Cart 🛒")
    return markup

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.send_message(message.chat.id, "Welcome to the Restaurant Ordering Bot! 🛒\nChoose an option from the menu below:", reply_markup=get_main_menu())

@bot.message_handler(func=lambda msg: msg.text in ["Menu 🍔", "Cart 🛒", "Back to Menu ↩️"])
def main_menu_routing(message):
    text = message.text
    if text == "Menu 🍔" or text == "Back to Menu ↩️":
        show_menu(message)
    elif text == "Cart 🛒":
        show_cart(message)

def show_menu(message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT name, price FROM menu")
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        bot.send_message(message.chat.id, "The menu is currently empty.")
        return
        
    markup = types.InlineKeyboardMarkup(row_width=1)
    for name, price in items:
        markup.add(types.InlineKeyboardButton(text=f"{name} - ${price:.2f}", callback_data=f"buy_{name}"))
    bot.send_message(message.chat.id, "🍔 *Our Delicious Menu:* \nSelect an item to add to your cart:", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_buy_callback(call):
    food_name = call.data.split("_")[1]
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT price FROM menu WHERE name = ?", (food_name,))
    item = cursor.fetchone()
    conn.close()
    
    if item:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("Cancel")
        msg = bot.send_message(call.message.chat.id, f"Enter quantity for {food_name} (1-50):", reply_markup=markup)
        bot.register_next_step_handler(msg, process_quantity, food_name, item[0])

def process_quantity(message, food_name, price):
    if message.text == "Cancel":
        bot.send_message(message.chat.id, "Selection cancelled.", reply_markup=get_main_menu())
        return
    if not message.text or not message.text.isdigit() or not (1 <= int(message.text) <= 50):
        msg = bot.send_message(message.chat.id, "❌ Invalid input. Please enter a valid number between 1 and 50:")
        bot.register_next_step_handler(msg, process_quantity, food_name, price)
        return
        
    qty = int(message.text)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT qty FROM cart WHERE user_id = ? AND food = ?", (message.chat.id, food_name))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("UPDATE cart SET qty = ? WHERE user_id = ? AND food = ?", (existing[0] + qty, message.chat.id, food_name))
    else:
        cursor.execute("INSERT INTO cart (user_id, food, qty, price) VALUES (?, ?, ?, ?)", (message.chat.id, food_name, qty, price))
    conn.commit()
    conn.close()
    bot.send_message(message.chat.id, f"Added {qty}x {food_name} to your cart! ✅", reply_markup=get_main_menu())

def show_cart(message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT food, qty, price FROM cart WHERE user_id = ?", (message.chat.id,))
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        bot.send_message(message.chat.id, "Your cart is empty 🛒")
        return
        
    text = "🛒 *Your Current Cart:*\n\n"
    total = 0
    for food, qty, price in items:
        sub = qty * price
        total += sub
        text += f"• {food} x{qty} = ${sub:.2f}\n"
    text += f"\n*Grand Total:* ${total:.2f}"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("Checkout ➡️", callback_data="checkout"),
               types.InlineKeyboardButton("Clear Cart 🗑️", callback_data="clear_cart"))
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["clear_cart", "checkout"])
def handle_cart_actions(call):
    if call.data == "clear_cart":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart WHERE user_id = ?", (call.message.chat.id,))
        conn.commit()
        conn.close()
        bot.edit_message_text("Your cart has been cleared successfully.", call.message.chat.id, call.message.message_id)
    elif call.data == "checkout":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart WHERE user_id = ?", (call.message.chat.id,))
        conn.commit()
        conn.close()
        
        bot.send_message(call.message.chat.id, "Thank you! Your order has been registered. (Upgrade to Premium for live notifications & tracking!) 🎉", reply_markup=get_main_menu())

if __name__ == "__main__":
    bot.infinity_polling()
