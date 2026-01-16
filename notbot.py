import sqlite3, pytz, logging, time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, Defaults

# Log Ayarları
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = "8218587809:AAHhXE8kP9VinHvLaOSF-r6DEg6IA6NonQk"

def db_kur():
    conn = sqlite3.connect('debis_bot.db')
    conn.execute('CREATE TABLE IF NOT EXISTS kullanicilar (user_id INTEGER PRIMARY KEY, email TEXT, sifre TEXT, periyot INTEGER)')
    conn.close()

def get_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

async def mesaj_gonder(context, chat_id, text):
    if len(text) <= 4000:
        await context.bot.send_message(chat_id=chat_id, text=text)
    else:
        for i in range(0, len(text), 4000):
            await context.bot.send_message(chat_id=chat_id, text=text[i:i+4000])

def notlari_tara_selenium(email, sifre):
    driver = get_driver()
    try:
        driver.get("https://debis.deu.edu.tr/OgrenciIsleri/Ogrenci/OgrenciNotu/index.php")
        # SSO Giriş
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username"))).send_keys(email)
        driver.find_element(By.ID, "password").send_keys(sifre)
        driver.find_element(By.ID, "kc-login").click()
        
        # Sayfanın yüklenmesini bekle
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "ders")))
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        ders_select = soup.find('select', id='ders')
        dersler = [(opt['value'], opt.text) for opt in ders_select.find_all('option') if opt['value']]
        
        sonuc = "📊 ANLIK NOTLARIN:\n"
        for d_id, d_adi in dersler:
            driver.find_element(By.XPATH, f"//option[@value='{d_id}']").click()
            time.sleep(1) 
            
            s_soup = BeautifulSoup(driver.page_source, 'html.parser')
            sonuc += f"\n📖 {d_adi}\n"
            found = False
            
            for tablo in s_soup.find_all('table'):
                if "SİZİN NOTUNUZ" in tablo.text:
                    for row in tablo.find_all('tr')[1:]:
                        cols = row.find_all('td')
                        if len(cols) >= 5:
                            adi, notu = cols[0].text.strip(), cols[4].text.strip()
                            if any(x in adi for x in ["Vize", "Final", "Başarı Notu", "Quiz", "Bütünleme"]):
                                val = "Yok" if "İLAN EDİLMEMİŞ" in notu or notu == "" else notu
                                sonuc += f" - {adi}: {val}\n"
                                found = True
                    break
            if not found: sonuc += " - Not girişi henüz yok.\n"
        return sonuc
    except Exception as e:
        return f"Hata: {str(e)}"
    finally:
        driver.quit()

# --- Komutlar ---
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("🚀 Bot Aktif! /kayit email sifre dakika")

async def kayit_ol(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if len(c.args) < 3: return await u.message.reply_text("❌ Kullanım: /kayit email sifre dakika")
    e, s, dk = c.args[0], c.args[1], int(c.args[2])
    
    conn = sqlite3.connect('debis_bot.db')
    conn.execute("INSERT OR REPLACE INTO kullanicilar VALUES (?,?,?,?)", (u.effective_user.id, e, s, dk))
    conn.commit(); conn.close()
    
    await u.message.reply_text("✅ Kaydedildi, Selenium ile notlar taranıyor...")
    res = notlari_tara_selenium(e, s)
    await mesaj_gonder(c, u.effective_user.id, res)
    
    # JobQueue Güvenli Başlatma
    if c.job_queue:
        job_name = str(u.effective_user.id)
        # Varsa eski görevleri sil
        for j in c.job_queue.get_jobs_by_name(job_name): j.schedule_removal()
        # Yeni görevi ekle
        c.job_queue.run_repeating(otomatik_kontrol, interval=dk*60, first=dk*60, chat_id=u.effective_user.id, name=job_name)
    else:
        await u.message.reply_text("⚠️ JobQueue hatası: Otomatik kontrol şu an yapılamıyor.")

async def kontrol(u: Update, c: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('debis_bot.db')
    user = conn.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (u.effective_user.id,)).fetchone()
    conn.close()
    if user:
        await u.message.reply_text("🔍 Güncel notlar taranıyor...")
        res = notlari_tara_selenium(user[0], user[1])
        await mesaj_gonder(c, u.effective_user.id, res)

async def sil(u: Update, c: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('debis_bot.db')
    conn.execute("DELETE FROM kullanicilar WHERE user_id=?", (u.effective_user.id,))
    conn.commit(); conn.close()
    if c.job_queue:
        for j in c.job_queue.get_jobs_by_name(str(u.effective_user.id)): j.schedule_removal()
    await u.message.reply_text("🗑️ Bilgileriniz silindi.")

async def otomatik_kontrol(c: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('debis_bot.db')
    user = conn.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (c.job.chat_id,)).fetchone()
    conn.close()
    if user:
        res = notlari_tara_selenium(user[0], user[1])
        await mesaj_gonder(c, c.job.chat_id, f"🔔 OTOMATİK KONTROL:\n{res}")

if __name__ == '__main__':
    db_kur()
    # Application builder artık JobQueue'yu otomatik tanıyacak
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kayit", kayit_ol))
    app.add_handler(CommandHandler("kontrol", kontrol))
    app.add_handler(CommandHandler("sil", sil))
    app.run_polling()
