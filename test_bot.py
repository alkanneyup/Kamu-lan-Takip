import telebot
import os
# main.py içerisindeki ana tarama fonksiyonunu çağırıyoruz
from main import iskur_ilanlarini_getir, ilan_detay_getir, ilan_analiz_et, HEADERS
import requests
import xml.etree.ElementTree as ET

# Bot Father'dan aldığınız Token ve kendi Chat ID'niz
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "BURAYA_BOT_TOKEN_YAZIN")
bot = telebot.TeleBot(BOT_TOKEN)

def ilanlari_tara():
    """Tüm kaynakları tarayıp sonuçları kategorize eder."""
    rss_url = "https://kariyerkapisi.gov.tr/RSS"
    ilanlar = []
    
    # 1. Kariyer Kapısı
    try:
        res = requests.get(rss_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for item in root.findall('./channel/item'):
                ilanlar.append({
                    'title': item.find('title').text if item.find('title') is not None else '',
                    'link': item.find('link').text if item.find('link') is not None else '',
                    'source': 'Kariyer Kapısı'
                })
    except Exception as e:
        print(f"RSS Hatası: {e}")

    # 2. İŞKUR
    try:
        iskur_ilanlari = iskur_ilanlarini_getir()
        if iskur_ilanlari:
            ilanlar.extend(iskur_ilanlari)
    except Exception as e:
        print(f"İŞKUR Hatası: {e}")

    green_list = []
    yellow_list = []

    for ilan in ilanlar:
        baslik = ilan.get('title', '')
        link = ilan.get('link', '')
        detay = ilan_detay_getir(link) if link else ""
        durum, aciklama = ilan_analiz_et(baslik, detay)

        if "🟢" in durum:
            green_list.append(f"🟢 **{baslik}**\n🔗 [İlan Linki]({link})")
        elif "🟡" in durum:
            yellow_list.append(f"🟡 **{baslik}**\n🔗 [İlan Linki]({link})")

    return green_list, yellow_list

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "👋 **Kamu İlan Takip Botu'na Hoş Geldiniz!**\n\n"
        "Kullanabileceğiniz komutlar:\n"
        "🟢 `/basvuru` - Sadece başvurabileceğiniz uygun ilanları listeler.\n"
        "🟡 `/kontrol` - İncelemeniz gereken şüpheli/genel ilanları listeler.\n"
        "📊 `/ozet` - Anlık genel durum özetini gönderir."
    )

@bot.message_handler(commands=['basvuru'])
def send_green_jobs(message):
    bot.reply_to(message, "🔍 İlanlar taranıyor, lütfen bekleyin...")
    green_jobs, _ = ilanlari_tara()
    
    if not green_jobs:
        bot.send_message(message.chat.id, "❌ Şu an profilinize %100 uygun açık ilan bulunamadı.")
        return

    response = "🟢 **BAŞVURABİLECEĞİNİZ İLANLAR:**\n\n" + "\n\n".join(green_jobs)
    # Telegram 4096 karakter sınırına takılmamak için bölerek gönderiyoruz
    if len(response) > 4000:
        for chunk in [response[i:i+4000] for i in range(0, len(response), 4000)]:
            bot.send_message(message.chat.id, chunk, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, response, parse_mode="Markdown")

@bot.message_handler(commands=['kontrol'])
def send_yellow_jobs(message):
    bot.reply_to(message, "🔍 Kontrol gereken ilanlar getiriliyor...")
    _, yellow_jobs = ilanlari_tara()
    
    if not yellow_jobs:
        bot.send_message(message.chat.id, "⚪ Kontrol gerektiren ilan bulunmuyor.")
        return

    # İlk 10 ilanı gönderelim (Mesaj boyutu aşılmasın)
    response = "🟡 **KONTROL ETMENİZ GEREKEN İLANLAR (İlk 10):**\n\n" + "\n\n".join(yellow_jobs[:10])
    bot.send_message(message.chat.id, response, parse_mode="Markdown")

if __name__ == "__main__":
    print("Bot dinlemede... Telegram'dan komut bekleniyor.")
    bot.infinity_polling()
    
