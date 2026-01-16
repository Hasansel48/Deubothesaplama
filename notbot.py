import sqlite3, requests, pytz, logging, time
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, Defaults

# Logları Railway panelinden izlemek için ayar
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = "8218587809:AAHhXE8kP9VinHvLaOSF-r6DEg6IA6NonQk"

# --- VERİTABANI AYARI ---
def db_kur():
    conn = sqlite3.connect('debis_bot.db')
    conn.execute('CREATE TABLE IF NOT EXISTS kullanicilar (user_id INTEGER PRIMARY KEY, email TEXT, sifre TEXT, periyot INTEGER)')
    conn.close()

# --- REQUESTS TABANLI HIZLI TARAMA ---
def notlari_tara_fast(email, sifre):
    session = requests.Session()
    # DEBİS'i bot olmadığımıza ikna eden başlıklar
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
    try:
        # 1. Giriş Sayfasını ve Gerekli Form URL'sini Al
        login_url = "https://sso.deu.edu.tr:8443/realms/dokuzeylul/protocol/openid-connect/auth?client_id=debis-client&redirect_uri=https%3A%2F%2Fdebis.deu.edu.tr%2Fsso_callback.php&response_type=code&scope=openid+profile+email"
        res = session.get(login_url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        form = soup.find('form', id='kc-form-login')
        if not form: return "❌ DEBİS giriş sayfası şu an açılmıyor."
        action_url = form['action']

        # 2. Giriş Yap (Post)
        payload = {'username': email, 'password': sifre, 'credentialId': ''}
        headers['Referer'] = login_url # Güvenlik için şart
        login_res = session.post(action_url, data=payload, headers=headers, allow_redirects=True)
        
        if "Geçersiz kullanıcı adı veya parola" in login_res.text:
            return "❌ Hatalı e-posta veya şifre girdin."

        # 3. Not Sayfasına ve Döneme Eriş (2025 Güz: 323)
        not_url = "https://debis.deu.edu.tr/OgrenciIsleri/Ogrenci/OgrenciNotu/index.php"
        res = session.post(not_url, data={'ogretim_donemi_id': '323'}, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        ders_select = soup.find('select', id='ders')
        if not ders_select: return "❌ Not sayfasına girilemedi. Lütfen bilgileri kontrol et."
        
        dersler = [(opt['value'], opt.text) for opt in ders_select.find_all('option') if opt['value']]
        
        sonuc = ""
        for d_id, d_adi in dersler:
            # Her ders için veriyi çek
            headers['Referer'] = not_url
            res = session.post(not_url, data={'ogretim_donemi_id': '323', 'ders': d_id}, headers=headers)
            s_soup = BeautifulSoup(res.text, 'html.parser')
            
            sonuc += f"\n📖 *{d_adi}*\n"
            found = False
            # Tabloları tara ve not tablosunu bul
            for tablo in s_soup.find_all('table'):
                if "Sınav Adı" in tablo.text:
                    for row in tablo.find_all('tr'):
                        cols = row.find_all('td')
                        if len(cols) >= 5:
                            adi, notu = cols[0].text.strip(), cols[4].text.strip()
                            if any(x in adi for x in ["Vize", "Final", "Başarı", "Quiz", "Bütünleme"]):
                                sonuc += f" - {adi}: `{notu if notu else 'Yok'}`\n"
                                found = True
                    break
            if not found: sonuc += " - Henüz not girişi yok.\n"
        
        return sonuc if sonuc else "🔍 Ders kaydı bulunamadı."
        
    except Exception as e:
        logging.error(f"Hata: {e}")
        return "❌ DEBİS bağlantısı kurulamadı. Lütfen tekrar dene."

# --- TELEGRAM KOMUTLARI ---
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("🚀 *DEBİS Profesyonel Takip Botu*\n\n"
                               "Notların açıklandığı an cebine gelsin!\n"
                               "`/kayit email sifre dakika` yazarak başla.", parse_mode="Markdown")

async def kayit_ol(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if len(c.args) < 3: return await u.message.reply_text("❌ Kullanım: `/kayit email sifre dakika` \nÖrnek: `/kayit hasan@ogr.deu.edu.tr 12345 30`")
    
    email, sifre, dk = c.args[0], c.args[1], int(c.args[2])
    conn = sqlite3.connect('debis_bot.db')
    conn.execute("INSERT OR REPLACE INTO kullanicilar VALUES (?, ?, ?, ?)", (u.effective_user.id, email, sifre, dk))
    conn.commit(); conn.close()
    
    await u.message.reply_text("✅ Kaydedildi, saniyeler içinde notların geliyor...")
    notlar = notlari_tara_fast(email, sifre)
    await u.message.reply_text(notlar, parse_mode="Markdown")

    job_name = str(u.effective_user.id)
    for j in c.job_queue.get_jobs_by_name(job_name): j.schedule_removal()
    c.job_queue.run_repeating(otomatik_kontrol, interval=dk*60, first=dk*60, chat_id=u.effective_user.id, name=job_name)
    await u.message.reply_text(f"🕒 Takip Aktif: Her {dk} dakikada bir kontrol edeceğim.")

async def manuel_kontrol(u: Update, c: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('debis_bot.db')
    user = conn.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (u.effective_user.id,)).fetchone()
    conn.close()
    if not user: return await u.message.reply_text("❌ Önce `/kayit` yapmalısın.")
    await u.message.reply_text("🔍 Güncel notların çekiliyor...")
    await u.message.reply_text(notlari_tara_fast(user[0], user[1]), parse_mode="Markdown")

async def sil(u: Update, c: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('debis_bot.db')
    conn.execute("DELETE FROM kullanicilar WHERE user_id=?", (u.effective_user.id,))
    conn.commit(); conn.close()
    for j in c.job_queue.get_jobs_by_name(str(u.effective_user.id)): j.schedule_removal()
    await u.message.reply_text("🗑️ Tüm bilgilerin silindi ve takip durduruldu.")

async def otomatik_kontrol(c: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('debis_bot.db')
    user = conn.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (c.job.chat_id,)).fetchone()
    conn.close()
    if user:
        res = notlari_tara_fast(user[0], user[1])
        if "📖" in res: # Sadece başarılı sonuçlarda mesaj at
            await c.bot.send_message(chat_id=c.job.chat_id, text=f"🔔 *OTOMATİK KONTROL SONUCU:*\n{res}", parse_mode="Markdown")

if __name__ == '__main__':
    db_kur()
    app = Application.builder().token(TOKEN).defaults(Defaults(tzinfo=pytz.timezone("Europe/Istanbul"))).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kayit", kayit_ol))
    app.add_handler(CommandHandler("kontrol", manuel_kontrol))
    app.add_handler(CommandHandler("sil", sil))
    app.run_polling()
