import os
import requests
import google.generativeai as genai

# Konfigurasi Kunci
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.8-flash')

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def fetch_market_data():
    # Menggunakan CoinGecko API Publik (Anti-Blokir Server US)
    # Menarik harga Solana (SOL) terhadap USD
    url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd&include_24hr_vol=true"
    
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'Argon-Bot/1.0'
    }
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Gagal mengambil data market. Status: {response.status_code}")
        
    data = response.json()
    current_price = data['solana']['usd']
    volume_24h = data['solana']['usd_24h_vol']
    
    return current_price, volume_24h

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
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f'{{"signal": "ERROR", "reasoning": "Gemini API Error: {str(e)}"}}'

if __name__ == "__main__":
    print("Memulai pemindaian market (CoinGecko Route)...")
    try:
        # Menarik data harga
        price, vol = fetch_market_data()
        print(f"Berhasil mendapat harga: {price}")
        
        # Menganalisa dengan Gemini
        ai_result = analyze_market_with_ai(price, vol)
        
        # Mengirim ke Telegram
        msg = f"🚨 *Argon Signal Update*\n\n```json\n{ai_result}\n```\nLive Trading: `OFF`"
        send_telegram_message(msg)
        print("Selesai. Pesan berhasil dikirim ke Telegram.")
        
    except Exception as e:
        error_msg = f"⚠️ *Argon System Warning*\n\nTerjadi kendala sistem: `{str(e)}`"
        send_telegram_message(error_msg)
        print(f"Error: {e}")
