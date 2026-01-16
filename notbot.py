import sqlite3, requests, pytz, logging
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, Defaults

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = "8218587809:AAHhXE8kP9VinHvLaOSF-r6DEg6IA6NonQk"

def db_kur():
    conn = sqlite3.connect('debis_bot.db')
    conn.execute('CREATE TABLE IF NOT EXISTS kullanicilar (user_id INTEGER PRIMARY KEY, email TEXT, sifre TEXT, periyot INTEGER)')
    conn.close()

async def mesaj_gonder_bolerek(update_or_context, chat_id, text):
    if len(text) <= 4096:
        if hasattr(update_or_context, 'message') and update_or_context.message:
            await update_or_context.message.reply_text(text, parse_mode="Markdown")
        else:
            await update_or_context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    else:
        for i in range(0, len(text), 4096):
            await update_or_context.bot.send_message(chat_id=chat_id, text=text[i:i+4096], parse_mode="Markdown")

def notlari_tara_fast(email, sifre):
    session = requests.Session()
    requests.packages.urllib3.disable_warnings()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        login_url = "https://sso.deu.edu.tr:8443/realms/dokuzeylul/protocol/openid-connect/auth?client_id=debis-client&redirect_uri=https%3A%2F%2Fdebis.deu.edu.tr%2Fsso_callback.php&response_type=code&scope=openid+profile+email"
        res = session.get(login_url, headers=headers, verify=False)
        soup = BeautifulSoup(res.text, 'html.parser')
        action_url = soup.find('form', id='kc-form-login')['action']
        
        payload = {'username': email, 'password': sifre, 'credentialId': ''}
        session.post(action_url, data=payload, headers=headers, verify=False)
        
        not_url = "https://debis.deu.edu.tr/OgrenciIsleri/Ogrenci/OgrenciNotu/index.php"
        res = session.post(not_url, data={'ogretim_donemi_id': '323'}, headers=headers, verify=False)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        ders_select = soup.find('select', id='ders')
        if not ders_select: return "❌ Giriş başarısız. Bilgileri kontrol et."
        
        dersler = [(opt['value'], opt.text) for opt in ders_select.find_all('option') if opt['value']]
        sonuc = "📊 *ANLIK NOTLARIN:*\n"

        for d_id, d_adi in dersler:
            res = session.post(not_url, data={'ogretim_donemi_id': '323', 'ders': d_id}, headers=headers, verify=False)
            s_soup = BeautifulSoup(res.text, 'html.parser')
            
            sonuc += f"\n📖 *{d_adi}*\n"
            found = False
            
            # Sadece not tablosunu hedef alıyoruz
            for tablo in s_soup.find_all('table'):
                # Eğer tablonun başlıklarında "SİZİN NOTUNUZ" varsa doğru tablodur
                if "SİZİN NOTUNUZ" in tablo.text:
                    rows = tablo.find_all('tr')[1:] # Başlığı atla
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 5:
                            sinav_adi = cols[0].text.strip()
                            not_degeri = cols[4].text.strip()
                            
                            # Gereksiz boş satırları veya "İLAN EDİLMEMİŞ" yazılarını filtrele
                            if sinav_adi and not_degeri and "İLAN EDİLMEMİŞ" not in not_degeri:
                                sonuc += f" - {sinav_adi}: `{not_degeri}`\n"
                                found = True
                            elif sinav_adi and ("Yok" in not_degeri or not_degeri == ""):
                                # Not henüz girilmediyse "Yok" yaz
                                if any(x in sinav_adi for x in ["Vize", "Final", "Başarı", "Quiz", "Bütünleme"]):
                                    sonuc += f" - {sinav_adi}: `Yok`\n"
                                    found = True
                    break
            
            if not found:
                sonuc += " - Not girişi henüz yok.\n"
        
        return sonuc
    except Exception as e:
        return f"❌ Hata oluştu: {str(e)}"

# --- KOMUTLAR ---
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("🚀 Bot Aktif! `/kayit email sifre dakika` yaz.", parse_mode="Markdown")

async def kayit_ol(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if len(c.args) < 3: return await u.message.reply_text("❌ Kullanım: `/kayit email sifre dakika`")
    e, s, dk = c.args[0], c.args[1], int(c.args[2])
    conn = sqlite3.connect('debis_bot.db'); conn.execute("INSERT OR REPLACE INTO kullanicilar VALUES (?,?,?,?)", (u.effective_user.id, e, s, dk)); conn.commit(); conn.close()
    await u.message.reply_text("✅ Kaydedildi, temiz liste hazırlanıyor...")
    res = notlari_tara_fast(e, s)
    await mesaj_gonder_bolerek(u, u.effective_user.id, res)
    job_name = str(u.effective_user.id)
    for j in c.job_queue.get_jobs_by_name(job_name): j.schedule_removal()
    c.job_queue.run_repeating(otomatik_kontrol, interval=dk*60, first=dk*60, chat_id=u.effective_user.id, name=job_name)

async def manuel_kontrol(u: Update, c: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('debis_bot.db'); user = conn.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (u.effective_user.id,)).fetchone(); conn.close()
    if user:
        res = notlari_tara_fast(user[0], user[1])
        await mesaj_gonder_bolerek(u, u.effective_user.id, res)

async def sil(u: Update, c: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('debis_bot.db'); conn.execute("DELETE FROM kullanicilar WHERE user_id=?", (u.effective_user.id,)); conn.commit(); conn.close()
    for j in c.job_queue.get_jobs_by_name(str(u.effective_user.id)): j.schedule_removal()
    await u.message.reply_text("🗑️ Bilgiler silindi.")

async def otomatik_kontrol(c: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('debis_bot.db'); user = conn.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (c.job.chat_id,)).fetchone(); conn.close()
    if user:
        res = notlari_tara_fast(user[0], user[1])
        await mesaj_gonder_bolerek(c, c.job.chat_id, res)

if __name__ == '__main__':
    db_kur()
    app = Application.builder().token(TOKEN).defaults(Defaults(tzinfo=pytz.timezone("Europe/Istanbul"))).build()
    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("kayit", kayit_ol))
    app.add_handler(CommandHandler("kontrol", manuel_kontrol)); app.add_handler(CommandHandler("sil", sil))
    app.run_polling()
