import os
import requests

# Kredensial
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        # Timeout 10 detik
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def fetch_market_data():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd&include_24hr_vol=true"
    headers = {'Accept': 'application/json', 'User-Agent': 'Argon-Bot/1.0'}
    
    # Tambahkan timeout 10 detik agar tidak macet menunggu server
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        raise Exception(f"Gagal akses harga dari CoinGecko: {response.status_code}")
    data = response.json()
    return data['solana']['usd'], data['solana']['usd_24h_vol']

def analyze_market_with_ai(current_price, volume_24h):
    prompt = f"""
    You are a 5-minute timeframe trading AI agent for SOL/USDT.
    Current price is ${current_price}. The 24h Volume is ${volume_24h}.
    
    Apply your adaptive strategy logic based on typical volume momentum.
    Take Profit: +0.60 points from entry.
    Stop Loss: -0.23 points from entry.
    
    Output format strictly JSON:
    {{"signal": "WAIT" or "LONG" or "SHORT", "entry_price": {current_price}, "take_profit": <number>, "stop_loss": <number>, "reasoning": "<short text>"}}
    """
    
    # Menghubungi Gemini langsung via REST API (Tanpa pustaka Google lama)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    # Timeout 15 detik. Jika AI tidak menjawab dalam 15 detik, proses digagalkan bukan dibiarkan macet.
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    response_data = response.json()
    
    if response.status_code != 200:
        raise Exception(f"Gemini API Error: {response_data}")
        
    return response_data['candidates'][0]['content']['parts'][0]['text']

if __name__ == "__main__":
    print("Memulai pemindaian market (Mode Ringan REST API)...")
    try:
        price, vol = fetch_market_data()
        print(f"Harga didapat: ${price}")
        
        ai_result = analyze_market_with_ai(price, vol)
        
        msg = f"🚨 *Argon Signal Update*\n\n```json\n{ai_result}\n```\nLive Trading: `OFF`"
        send_telegram_message(msg)
        print("Selesai. Pesan berhasil dikirim ke Telegram.")
        
    except Exception as e:
        error_msg = f"⚠️ *Argon System Warning*\n\nTerjadi kendala sistem: `{str(e)}`"
        send_telegram_message(error_msg)
        print(f"Error: {e}")
