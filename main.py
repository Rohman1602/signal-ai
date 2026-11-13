import os
import json
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

BACKUP_AI_API_KEY = os.environ.get("BACKUP_AI_API_KEY", "")
BACKUP_AI_URL = os.environ.get("BACKUP_AI_URL", "https://api.groq.com/openai/v1/chat/completions")
BACKUP_AI_MODEL = os.environ.get("BACKUP_AI_MODEL", "llama-3.3-70b-versatile")

CONFIG_FILE = "config.json"

def load_config():
    default_cfg = {
        "live_trading": False,
        "tp": 0.60,
        "sl": 0.23,
        "strategy": "Trending: EMA 9 + Volume. Sideways: Bollinger Bands + SMI. Konfirmasi struktur HH/HL/LH/LL.",
        "last_update_id": 0
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                default_cfg.update(data)
        except Exception:
            pass
    return default_cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def send_telegram(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"Gagal kirim Telegram: {e}")

def send_control_menu(cfg, header="🎛️ *PANEL KENDALI ARGON BOT*"):
    status_trade = "🟢 ON (LIVE)" if cfg["live_trading"] else "🔴 OFF (Signal Only)"
    toggle_label = "🔴 Matikan Auto-Trading" if cfg["live_trading"] else "🟢 Aktifkan Auto-Trading"
    
    text = (
        f"{header}\n\n"
        f"• *Status Trading:* `{status_trade}`\n"
        f"• *Take Profit (TP):* `+{cfg['tp']} poin`\n"
        f"• *Stop Loss (SL):* `-{cfg['sl']} poin`\n"
        f"• *Strategi Aktif:*\n_{cfg['strategy']}_\n\n"
        f"Pilih tombol di bawah atau kirim perintah teks:"
    )
    
    keyboard = {
        "inline_keyboard": [
            [{"text": toggle_label, "callback_data": "toggle_trading"}],
            [
                {"text": "📊 Cek Sinyal Sekarang", "callback_data": "scan_now"},
                {"text": "✏️ Cara Ubah TP/SL/Strategi", "callback_data": "help_edit"}
            ],
            [{"text": "🔄 Refresh Menu", "callback_data": "show_menu"}]
        ]
    }
    send_telegram(text, reply_markup=keyboard)

def process_telegram_commands(cfg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": cfg.get("last_update_id", 0) + 1, "timeout": 5}
    
    try:
        res = requests.get(url, params=params, timeout=15).json()
    except Exception as e:
        print(f"Gagal cek perintah Telegram: {e}")
        return cfg

    if not res.get("ok"):
        return cfg

    menu_requested = False

    for update in res.get("result", []):
        cfg["last_update_id"] = update["update_id"]
        
        # 1. Cek jika user menekan Tombol Menu (Callback Query)
        if "callback_query" in update:
            cb = update["callback_query"]
            sender_id = str(cb["from"]["id"])
            if sender_id != TELEGRAM_CHAT_ID:
                continue
                
            # Hentikan animasi loading pada tombol Telegram
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                json={"callback_query_id": cb["id"]}, timeout=10
            )
            
            action = cb.get("data", "")
            if action == "toggle_trading":
                cfg["live_trading"] = not cfg["live_trading"]
                send_control_menu(cfg, header="✅ *Status Auto-Trading Diperbarui!*")
            elif action == "show_menu":
                send_control_menu(cfg)
            elif action == "help_edit":
                help_text = (
                    "📝 *PANDUAN PERINTAH TELEGRAM*\n\n"
                    "Kirim pesan teks berikut ke bot ini kapan saja:\n"
                    "• `/menu` — Membuka panel tombol kendali\n"
                    "• `/tp 0.80` — Mengubah target Take Profit\n"
                    "• `/sl 0.25` — Mengubah batas Stop Loss\n"
                    "• `/trading on` atau `/trading off` — Saklar Live Trading\n"
                    "• `/strategi [aturan baru]` — Mengganti logika indikator AI\n\n"
                    "_Catatan: Perintah diproses otomatis mengikuti jadwal cek server setiap 5 menit._"
                )
                send_telegram(help_text)
            elif action == "scan_now":
                send_telegram("⏳ *Memulai pemindaian market manual...*")

        # 2. Cek jika user mengirim Perintah Teks
        elif "message" in update and "text" in update["message"]:
            msg = update["message"]
            sender_id = str(msg["chat"]["id"])
            if sender_id != TELEGRAM_CHAT_ID:
                continue
                
            text = msg["text"].strip()
            lower_text = text.lower()
            
            if lower_text in ["/start", "/menu", "menu"]:
                menu_requested = True
            elif lower_text.startswith("/tp "):
                try:
                    val = float(text.split(" ", 1)[1].replace(",", "."))
                    cfg["tp"] = val
                    send_telegram(f"✅ Take Profit diubah menjadi *+{val} poin*.")
                except ValueError:
                    send_telegram("⚠️ Format salah. Contoh: `/tp 0.65`")
            elif lower_text.startswith("/sl "):
                try:
                    val = float(text.split(" ", 1)[1].replace(",", "."))
                    cfg["sl"] = val
                    send_telegram(f"✅ Stop Loss diubah menjadi *-{val} poin*.")
                except ValueError:
                    send_telegram("⚠️ Format salah. Contoh: `/sl 0.20`")
            elif lower_text == "/trading on":
                cfg["live_trading"] = True
                send_telegram("🟢 Mode Live Trading: *AKTIF (ON)*")
            elif lower_text == "/trading off":
                cfg["live_trading"] = False
                send_telegram("🔴 Mode Live Trading: *NONAKTIF (OFF / Dry Run)*")
            elif lower_text.startswith("/strategi "):
                new_strat = text.split(" ", 1)[1].strip()
                if new_strat:
                    cfg["strategy"] = new_strat
                    send_telegram(f"✅ *Strategi AI Diperbarui:*\n_{new_strat}_")

    if menu_requested:
        send_control_menu(cfg)

    return cfg

def fetch_market_data():
    headers = {'Accept': 'application/json', 'User-Agent': 'Argon-Bot/1.0'}
    
    price_url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd&include_24hr_vol=true"
    res_price = requests.get(price_url, headers=headers, timeout=15)
    if res_price.status_code != 200:
        raise Exception(f"Gagal akses harga CoinGecko: {res_price.status_code}")
    price_data = res_price.json()
    current_price = price_data['solana']['usd']
    volume_24h = price_data['solana']['usd_24h_vol']

    recent_prices = []
    try:
        chart_url = "https://api.coingecko.com/api/v3/coins/solana/market_chart?vs_currency=usd&days=1"
        res_chart = requests.get(chart_url, headers=headers, timeout=15)
        if res_chart.status_code == 200:
            prices_list = res_chart.json().get('prices', [])
            recent_prices = [round(p[1], 3) for p in prices_list[-24:]]
    except Exception:
        pass

    return current_price, volume_24h, recent_prices

def build_prompt(current_price, volume_24h, recent_prices, cfg):
    history_str = f"Last 24 price points (~5m intervals): {recent_prices}" if recent_prices else "No historical array available."
    return f"""
    You are an autonomous 5-minute timeframe quantitative trading AI agent for SOL/USDT.
    Current Price: ${current_price}
    24h Volume: ${volume_24h:,.0f}
    {history_str}

    Apply the user's active strategy:
    {cfg['strategy']}

    Strict Risk Management:
    - Take Profit (TP): +{cfg['tp']} points from entry price.
    - Stop Loss (SL): -{cfg['sl']} points from entry price.

    Output strictly in valid JSON format without markdown fences:
    {{
      "signal": "WAIT" | "LONG" | "SHORT",
      "market_regime": "TRENDING" | "SIDEWAYS",
      "entry_price": {current_price},
      "take_profit": <number>,
      "stop_loss": <number>,
      "reasoning": "<Penjelasan singkat Bahasa Indonesia kenapa entry/wait dan indikator apa yang dipakai>"
    }}
    """

def call_gemini(model_name, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    data = response.json()
    
    if response.status_code != 200:
        error_msg = data.get('error', {}).get('message', str(data))
        raise Exception(f"[{model_name}] Error {response.status_code}: {error_msg}")
        
    return data['candidates'][0]['content']['parts'][0]['text']

def call_backup_ai(prompt):
    if not BACKUP_AI_API_KEY:
        raise Exception("BACKUP_AI_API_KEY belum diisi.")
        
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {BACKUP_AI_API_KEY}'
    }
    payload = {
        "model": BACKUP_AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    
    response = requests.post(BACKUP_AI_URL, headers=headers, json=payload, timeout=60)
    data = response.json()
    
    if response.status_code != 200:
        raise Exception(f"[Backup AI] Error {response.status_code}: {data}")
        
    return data['choices'][0]['message']['content']

def analyze_market_with_fallback(current_price, volume_24h, recent_prices, cfg):
    prompt = build_prompt(current_price, volume_24h, recent_prices, cfg)
    errors = []

    gemini_models = [
        "gemini-3.8-flash",
        "gemini-3.8-flash-lite",
        "gemini-flash-latest"
    ]

    for model_name in gemini_models:
        try:
            result = call_gemini(model_name, prompt)
            return result, model_name
        except Exception as e:
            errors.append(str(e))

    if BACKUP_AI_API_KEY:
        try:
            result = call_backup_ai(prompt)
            return result, f"Backup ({BACKUP_AI_MODEL})"
        except Exception as e:
            errors.append(str(e))

    raise Exception("Semua model AI sibuk/gagal:\n" + "\n".join(errors))

if __name__ == "__main__":
    config = load_config()
    
    # 1. Baca semua perintah/tombol Telegram yang masuk & simpan langsung ke config.json
    config = process_telegram_commands(config)
    save_config(config)
    
    # 2. Jalankan analisa pasar
    try:
        price, vol, recent_prices = fetch_market_data()
        ai_result, used_model = analyze_market_with_fallback(price, vol, recent_prices, config)
        clean_result = ai_result.replace("```json", "").replace("```", "").strip()
        
        status_trade = "ON (LIVE)" if config["live_trading"] else "OFF (Dry Run)"
        msg = (
            f"🚨 *Argon Signal Update*\n"
            f"🤖 Engine: `{used_model}` | Trading: `{status_trade}`\n\n"
            f"```json\n{clean_result}\n```\n"
            f"_(Ketik /menu untuk membuka panel kontrol)_"
        )
        send_telegram(msg)
        
    except Exception as e:
        error_msg = f"⚠️ *Argon System Warning*\n\n`{str(e)}`"
        send_telegram(error_msg)
