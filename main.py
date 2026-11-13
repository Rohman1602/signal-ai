import os
import json
import time
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
        "strategy": "1. Trending: Gunakan EMA 9 dynamic support/resistance dan momentum volume (Pullback Rejection atau Pivot Breakout). 2. Sideways/Ranging: Gunakan pantulan Bollinger Bands dan area ekstrem Stochastic Momentum Index (SMI). 3. Konfirmasi Market Structure (HH/HL untuk LONG, LH/LL untuk SHORT). Jika di zona tanggung/tidak jelas, pilih WAIT.",
        "last_update_id": 0
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                default_cfg.update(json.load(f))
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
        f"_(Catatan: Karena memakai server terjadwal GitHub, klik tombol akan direspons saat siklus 5 menit berikutnya berjalan)_"
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
        
        if "callback_query" in update:
            cb = update["callback_query"]
            if str(cb["from"]["id"]) != TELEGRAM_CHAT_ID:
                continue
                
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                    json={"callback_query_id": cb["id"]}, timeout=10
                )
            except Exception:
                pass
            
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
                    "_Perintah diproses otomatis pada siklus jadwal 5 menit berikutnya._"
                )
                send_telegram(help_text)
            elif action == "scan_now":
                send_telegram("⏳ *Memproses permintaan Cek Sinyal...*")

        elif "message" in update and "text" in update["message"]:
            msg = update["message"]
            if str(msg["chat"]["id"]) != TELEGRAM_CHAT_ID:
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

def calc_ema(values, period):
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return round(ema, 3)

def fetch_market_data():
    headers = {'Accept': 'application/json', 'User-Agent': 'Argon-Bot/1.0'}
    
    # 1. Jalur Utama: Binance Public Market Data (Bebas blokir US & menyediakan candle 5m asli)
    try:
        b_url = "https://data-api.binance.vision/api/v3/klines?symbol=SOLUSDT&interval=5m&limit=35"
        res = requests.get(b_url, headers=headers, timeout=15)
        if res.status_code == 200:
            klines = res.json()
            if isinstance(klines, list) and len(klines) >= 20:
                highs = [float(k[2]) for k in klines]
                lows = [float(k[3]) for k in klines]
                closes = [float(k[4]) for k in klines]
                vols = [round(float(k[5]), 1) for k in klines]
                
                current_price = closes[-1]
                ema9 = calc_ema(closes, 9)
                ema21 = calc_ema(closes, 21)
                
                # Bollinger Bands (20, 2)
                win20 = closes[-20:]
                bb_mid = sum(win20) / 20
                std_dev = (sum((x - bb_mid) ** 2 for x in win20) / 20) ** 0.5
                bb_upper = round(bb_mid + 2 * std_dev, 3)
                bb_lower = round(bb_mid - 2 * std_dev, 3)
                bb_mid = round(bb_mid, 3)
                
                # Stochastic Momentum Index (14)
                hh14 = max(highs[-14:])
                ll14 = min(lows[-14:])
                hl_range = hh14 - ll14
                smi = round(((current_price - (hh14 + ll14) / 2) / (hl_range / 2)) * 100, 1) if hl_range > 0 else 0.0
                
                last_candles = [
                    {"o": round(float(k[1]), 2), "h": round(float(k[2]), 2), "l": round(float(k[3]), 2), "c": round(float(k[4]), 2), "v": round(float(k[5]), 0)}
                    for k in klines[-8:]
                ]
                
                summary = (
                    f"Source: Binance 5m Real-Time | Price: ${current_price}\n"
                    f"Indicators -> EMA 9: ${ema9} | EMA 21: ${ema21} | BB Upper: ${bb_upper}, Mid: ${bb_mid}, Lower: ${bb_lower} | SMI(14): {smi}\n"
                    f"Last 8 Candles (5m): {json.dumps(last_candles)}"
                )
                return current_price, summary
    except Exception as e:
        print(f"Binance Vision fallback ke CoinGecko: {e}")

    # 2. Jalur Cadangan: CoinGecko
    price_url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd&include_24hr_vol=true"
    res_price = requests.get(price_url, headers=headers, timeout=15)
    if res_price.status_code != 200:
        raise Exception(f"Gagal mengambil data harga market: {res_price.status_code}")
    pdata = res_price.json()
    current_price = pdata['solana']['usd']
    vol24 = pdata['solana']['usd_24h_vol']
    summary = f"Source: CoinGecko | Price: ${current_price} | 24h Volume: ${vol24:,.0f}"
    return current_price, summary

def build_prompt(current_price, market_summary, cfg):
    return f"""
    You are an autonomous 5-minute timeframe quantitative trading AI agent for SOL/USDT.
    {market_summary}

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
    clean_name = model_name.replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_name}:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    data = response.json()
    
    if response.status_code != 200:
        error_msg = data.get('error', {}).get('message', str(data))
        raise Exception(f"[{clean_name}] HTTP {response.status_code}: {error_msg}")
        
    return data['candidates'][0]['content']['parts'][0]['text']

def discover_valid_google_models():
    """Mengambil daftar model yang benar-benar aktif & mendukung generateContent pada API Key Anda"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    blocked_keywords = ["embedding", "imagen", "veo", "tts", "aqa", "robotics", "computer-use", "deep-research"]
    preferred = ["gemini-3.8-flash", "gemini-2.5-pro", "gemma-3-27b-it", "gemma-3-12b-it", "gemini-flash-latest"]
    
    try:
        res = requests.get(url, timeout=15).json()
        available = []
        for m in res.get("models", []):
            name = m.get("name", "").replace("models/", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods and not any(b in name.lower() for b in blocked_keywords):
                available.append(name)
        
        ordered = [p for p in preferred if p in available]
        for a in available:
            if a not in ordered:
                ordered.append(a)
        return ordered[:6]
    except Exception:
        return preferred

def call_backup_ai(prompt):
    if not BACKUP_AI_API_KEY:
        raise Exception("BACKUP_AI_API_KEY belum diisi.")
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {BACKUP_AI_API_KEY}'}
    payload = {"model": BACKUP_AI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
    response = requests.post(BACKUP_AI_URL, headers=headers, json=payload, timeout=60)
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"[Backup AI] HTTP {response.status_code}: {data}")
    return data['choices'][0]['message']['content']

def analyze_market_with_fallback(current_price, market_summary, cfg):
    prompt = build_prompt(current_price, market_summary, cfg)
    errors = []

    # 1. Coba model utama (gemini-3.8-flash) dengan 1x retry jika 503 High Demand
    for attempt in range(2):
        try:
            result = call_gemini("gemini-3.8-flash", prompt)
            return result, "gemini-3.8-flash"
        except Exception as e:
            err_str = str(e)
            if "503" in err_str and attempt == 0:
                print("3.8-flash sedang sibuk (503), mencoba ulang dalam 8 detik...")
                time.sleep(8)
                continue
            errors.append(err_str)
            break

    # 2. Auto-discovery model lain yang aktif di API Key Anda (termasuk Gemma 3 / Gemini lain)
    candidate_models = discover_valid_google_models()
    for model_name in candidate_models:
        if model_name == "gemini-3.8-flash":
            continue
        try:
            result = call_gemini(model_name, prompt)
            return result, model_name
        except Exception as e:
            errors.append(str(e))

    # 3. Cadangan luar Google (jika BACKUP_AI_API_KEY diisi)
    if BACKUP_AI_API_KEY:
        try:
            result = call_backup_ai(prompt)
            return result, f"Backup ({BACKUP_AI_MODEL})"
        except Exception as e:
            errors.append(str(e))

    raise Exception("Semua model AI sedang sibuk:\n" + "\n".join(errors[:4]))

if __name__ == "__main__":
    config = load_config()
    config = process_telegram_commands(config)
    save_config(config)
    
    try:
        price, market_summary = fetch_market_data()
        ai_result, used_model = analyze_market_with_fallback(price, market_summary, config)
        clean_result = ai_result.replace("```json", "").replace("```", "").strip()
        
        status_trade = "ON (LIVE)" if config["live_trading"] else "OFF (Dry Run)"
        msg = (
            f"🚨 *Argon Signal Update*\n"
            f"🤖 Engine: `{used_model}` | Trading: `{status_trade}`\n\n"
            f"```json\n{clean_result}\n```\n"
            f"_(Ketik /menu untuk panel kontrol)_"
        )
        send_telegram(msg)
        
    except Exception as e:
        error_msg = f"⚠️ *Argon System Warning*\n\n`{str(e)}`"
        send_telegram(error_msg)
