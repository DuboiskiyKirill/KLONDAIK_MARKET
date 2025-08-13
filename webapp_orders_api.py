
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, os, requests

app = Flask(__name__)
CORS(app)

DB_PATH = os.environ.get("ORDERS_DB_PATH", "orders.db")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
CHAT_ID  = os.environ.get("TG_CHAT_ID", "")

def send_telegram_message(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=5)
    except Exception as e:
        print("Telegram notify failed:", e)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute(\"""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                pickup_code TEXT NOT NULL,
                pvz TEXT NOT NULL,
                expires TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'created',
                paid INTEGER DEFAULT 0
            )
        \""")
        db.commit()

@app.route("/health")
def health():
    return {"ok": True}

@app.route("/create", methods=["POST"])
def create_order():
    data = request.json or {}
    for f in ("client_name","pickup_code","pvz"):
        if not data.get(f):
            return jsonify({"success": False, "error": f"'{f}' is required"}), 400
    with get_db() as db:
        cur = db.cursor()
        cur.execute(
            "INSERT INTO orders (client_name, pickup_code, pvz, expires) VALUES (?, ?, ?, ?)",
            (data["client_name"].strip(), data["pickup_code"].strip(), data["pvz"].strip(), (data.get("expires") or "").strip())
        )
        db.commit()
        order_id = cur.lastrowid
    send_telegram_message(f"📦 Новый заказ #{order_id}\nКлиент: {data['client_name']}\nПВЗ: {data['pvz']}\nКод: {data['pickup_code']}")
    qr_payload = {"id": order_id, "client_name": data["client_name"], "pickup_code": data["pickup_code"]}
    return jsonify({"success": True, "order_id": order_id, "qr_payload": qr_payload})

@app.route("/orders")
def orders():
    with get_db() as db:
        rows = db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
        return jsonify([dict(r) for r in rows])

@app.route("/order/<int:order_id>")
def get_order(order_id):
    with get_db() as db:
        r = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not r:
            return jsonify({"success": False, "error": "not_found"}), 404
        return jsonify(dict(r))

@app.route("/accept/<int:order_id>", methods=["POST"])
def accept(order_id):
    with get_db() as db:
        db.execute("UPDATE orders SET status = 'delivered' WHERE id = ?", (order_id,))
        db.commit()
    return jsonify({"success": True, "order_id": order_id, "status": "delivered"})

@app.route("/pickup/<int:order_id>", methods=["POST"])
def pickup(order_id):
    with get_db() as db:
        db.execute("UPDATE orders SET status = 'picked_up' WHERE id = ?", (order_id,))
        db.commit()
    send_telegram_message(f"📤 Выдан заказ #{order_id}")
    return jsonify({"success": True, "order_id": order_id, "status": "picked_up"})

@app.route("/payment_callback", methods=["POST"])
def payment_callback():
    data = request.json or {}
    order_id = data.get("order_id")
    if not order_id:
        return jsonify({"success": False, "error": "order_id missing"}), 400
    with get_db() as db:
        db.execute("UPDATE orders SET paid = 1 WHERE id = ?", (order_id,))
        db.commit()
    send_telegram_message(f"💳 Оплата получена за заказ #{order_id}")
    return jsonify({"success": True, "order_id": order_id, "status": "paid"})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
