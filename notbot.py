import sqlite3
import time
import pytz
import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, Defaults

# Selenium Importları
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- LOG SİSTEMİ ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- AYARLAR ---
# GÜVENLİK NOTU: Tokenını koda gömmek yerine çevre değişkeni kullanman önerilir.
TOKEN = "8218587809:AAHhXE8kP9VinHvLaOSF-r6DEg6IA6NonQk"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'debis_bot.db')

# --- VERİTABANI İŞLEMLERİ ---
def db_kur():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Periyot tipini REAL (ondalıklı sayı) yaptık
    c.execute('''CREATE TABLE IF NOT EXISTS kullanicilar 
                 (user_id INTEGER PRIMARY KEY, email TEXT, sifre TEXT, periyot REAL)''')
    conn.commit()
    conn.close()
    logging.info(f"📂 Veritabanı hazır: {DB_PATH}")

# --- SELENIUM TARAMA FONKSİYONU ---
def notlari_tara(email, sifre):
    logging.info(f"🔄 {email} için tarama başlatılıyor...")
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        wait = WebDriverWait(driver, 15)
        sonuc = ""
        
        driver.get("https://sso.deu.edu.tr:8443/realms/dokuzeylul/protocol/openid-connect/auth?client_id=debis-client&redirect_uri=https%3A%2F%2Fdebis.deu.edu.tr%2Fsso_callback.php&response_type=code&scope=openid+profile+email")
        
        wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(email)
        driver.find_element(By.ID, "password").send_keys(sifre)
        driver.find_element(By.ID, "kc-login").click()
        
        time.sleep(2)
        driver.get("https://debis.deu.edu.tr/OgrenciIsleri/Ogrenci/OgrenciNotu/index.php")
        
        # Dönem seçimi (323 = 2025 Güz)
        donem_dropdown = wait.until(EC.presence_of_element_located((By.ID, "ogretim_donemi_id")))
        Select(donem_dropdown).select_by_value("323")
        time.sleep(2)

        ders_menu = driver.find_element(By.ID, "ders")
        dersler = [(opt.get_attribute("value"), opt.text) for opt in Select(ders_menu).options if opt.get_attribute("value") != ""]

        if not dersler:
            return "❌ Dersler bulunamadı. Bilgilerini kontrol et."

        for d_id, d_adi in dersler:
            driver.execute_script(f"document.getElementById('ders').value = '{d_id}';")
            driver.execute_script("form_ders_submit();")
            time.sleep(3)
            
            sonuc += f"\n📖 *{d_adi}*\n"
            rows = driver.find_elements(By.XPATH, "//table//table//tr")
            found = False
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) == 5:
                    adi, notu = cols[0].text.strip(), cols[4].text.strip()
                    if any(x in adi for x in ["Vize", "Final", "Başarı Notu", "Quiz", "Bütünleme"]):
                        val = notu if notu else "Yok"
                        sonuc += f" - {adi}: `{val}`\n"
                        found = True
            if not found: sonuc += " - Not girişi henüz yok.\n"
        
        return sonuc
            
    except Exception as e:
        logging.error(f"❌ Tarama Hatası: {e}")
        return "❌ Not çekme sırasında hata! Bilgilerini kontrol et."
    finally:
        try: driver.quit()
        except: pass

# --- BOT KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *DEBİS Takip Botu Aktif!*\n\n"
        "Kayıt: `/kayit email sifre saat` \n"
        "Örnek: `/kayit hasan@ogr.deu.edu.tr 12345 0.5`", 
        parse_mode="Markdown"
    )

async def kayit_ol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 3:
            return await update.message.reply_text("❌ Eksik bilgi! Format: `/kayit email sifre saat`")
        
        email, sifre = context.args[0], context.args[1]
        saat = float(context.args[2].replace(',', '.'))
        user_id = update.effective_user.id
        
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO kullanicilar VALUES (?, ?, ?, ?)", (user_id, email, sifre, saat))
            conn.commit()
        
        await update.message.reply_text("✅ Kaydedildi! İlk kontrol yapılıyor...")
        
        mesaj = notlari_tara(email, sifre)
        await update.message.reply_text(f"📊 *GÜNCEL NOTLARIN:*\n{mesaj}", parse_mode="Markdown")

        # Job Queue Ayarı
        job_name = str(user_id)
        for job in context.job_queue.get_jobs_by_name(job_name): job.schedule_removal()
        
        context.job_queue.run_repeating(
            otomatik_kontrol, 
            interval=int(saat * 3600), 
            first=int(saat * 3600), 
            chat_id=user_id, 
            name=job_name
        )
    except ValueError:
        await update.message.reply_text("❌ Hata: Saat kısmına sayı girmelisin (Örn: 0.5 veya 1)")
    except Exception as e:
        logging.error(f"Kayıt Hatası: {e}")
        await update.message.reply_text("❌ Kayıt başarısız.")

async def manuel_kontrol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (user_id,))
        user = c.fetchone()
    
    if not user:
        return await update.message.reply_text("❌ Kaydın bulunamadı!")
    
    await update.message.reply_text("🔍 Notlar çekiliyor...")
    mesaj = notlari_tara(user[0], user[1])
    await update.message.reply_text(mesaj, parse_mode="Markdown")

async def bilgi_sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM kullanicilar WHERE user_id=?", (user_id,))
    
    for j in context.job_queue.get_jobs_by_name(str(user_id)): j.schedule_removal()
    await update.message.reply_text("🗑️ Bilgilerin silindi.")

async def otomatik_kontrol(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (job.chat_id,))
        user = c.fetchone()
    
    if user:
        mesaj = notlari_tara(user[0], user[1])
        await context.bot.send_message(chat_id=job.chat_id, text=f"🔔 *OTOMATİK KONTROL:*\n{mesaj}", parse_mode="Markdown")

if __name__ == '__main__':
    db_kur()
    istanbul_tz = pytz.timezone("Europe/Istanbul")
    app = Application.builder().token(TOKEN).defaults(Defaults(tzinfo=istanbul_tz)).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kayit", kayit_ol))
    app.add_handler(CommandHandler("kontrol", manuel_kontrol))
    app.add_handler(CommandHandler("sil", bilgi_sil))
    
    logging.info("🚀 Bot başladı!")
    app.run_polling()
