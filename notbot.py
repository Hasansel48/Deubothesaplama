import sqlite3
import time
import pytz
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, Defaults

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

TOKEN = "8218587809:AAHhXE8kP9VinHvLaOSF-r6DEg6IA6NonQk"

# --- VERİTABANI İŞLEMLERİ ---
def db_kur():
    conn = sqlite3.connect('debis_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS kullanicilar 
                 (user_id INTEGER PRIMARY KEY, email TEXT, sifre TEXT, periyot INTEGER)''')
    conn.commit()
    conn.close()
    print("📂 Veritabanı dosyası hazır.")

# --- SELENIUM TARAMA FONKSİYONU ---
def notlari_tara(email, sifre):
    print(f"🔄 {email} için tarama başlatılıyor...")
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Sunucularda hata almamak için binary yerini belirtiyoruz
    chrome_options.binary_location = "/usr/bin/google-chrome"
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wait = WebDriverWait(driver, 15)
    sonuc = ""
    try:
        print("🔗 SSO Giriş sayfasına bağlanılıyor...")
        driver.get("https://sso.deu.edu.tr:8443/realms/dokuzeylul/protocol/openid-connect/auth?client_id=debis-client&redirect_uri=https%3A%2F%2Fdebis.deu.edu.tr%2Fsso_callback.php&response_type=code&scope=openid+profile+email")
        
        wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(email)
        driver.find_element(By.ID, "password").send_keys(sifre)
        driver.find_element(By.ID, "kc-login").click()
        
        print("🔑 Giriş yapıldı, notlar sayfası açılıyor...")
        time.sleep(2)
        driver.get("https://debis.deu.edu.tr/OgrenciIsleri/Ogrenci/OgrenciNotu/index.php")
        
        # Dönem seçimi (323 = 2025 Güz)
        donem_dropdown = wait.until(EC.presence_of_element_located((By.ID, "ogretim_donemi_id")))
        Select(donem_dropdown).select_by_value("323")
        time.sleep(2)

        ders_menu = driver.find_element(By.ID, "ders")
        dersler = [(opt.get_attribute("value"), opt.text) for opt in Select(ders_menu).options if opt.get_attribute("value") != ""]

        if not dersler:
            return "❌ Dersler bulunamadı. Lütfen bilgileri kontrol et."

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
            
    except Exception as e:
        print(f"❌ Tarama Hatası: {e}")
        sonuc = "❌ Not çekme sırasında hata oluştu!"
    finally:
        driver.quit()
    return sonuc

# --- BOT KOMUTLARI ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *DEBİS Dakika Takip Botu Aktif!*\n\n"
        "Kayıt formatı:\n"
        "`/kayit email sifre dakika` \n\n"
        "Örnek: `/kayit hasan@ogr.deu.edu.tr 12345 30` (Her 30 dk bir kontrol)", 
        parse_mode="Markdown"
    )

async def kayit_ol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 3:
            return await update.message.reply_text("❌ Hata! Lütfen `/kayit email sifre dakika` şeklinde yaz.")
        
        email = context.args[0]
        sifre = context.args[1]
        dakika = int(context.args[2])
        user_id = update.effective_user.id
        
        conn = sqlite3.connect('debis_bot.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO kullanicilar VALUES (?, ?, ?, ?)", (user_id, email, sifre, dakika))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Kaydedildi! İlk notlar çekiliyor...")

        # İLK KONTROL
        ilk_sonuc = notlari_tara(email, sifre)
        await update.message.reply_text(f"📊 *ANLIK NOTLARIN:*\n{ilk_sonuc}", parse_mode="Markdown")

        # OTOMATİK DÖNGÜ (DAKİKA BAZLI)
        job_name = str(user_id)
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs: job.schedule_removal()
        
        saniye_aralik = dakika * 60
        context.job_queue.run_repeating(otomatik_kontrol, interval=saniye_aralik, first=saniye_aralik, chat_id=user_id, name=job_name)
        
        await update.message.reply_text(f"🕒 Takip başlatıldı. Her {dakika} dakikada bir kontrol yapacağım.")

    except Exception as e:
        await update.message.reply_text("❌ Hata oluştu! Lütfen sayıları doğru girdiğinden emin ol.")

async def manuel_kontrol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect('debis_bot.db'); c = conn.cursor()
    c.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (user_id,))
    user = c.fetchone(); conn.close()
    if not user:
        return await update.message.reply_text("❌ Önce `/kayit` yapmalısın.")
    await update.message.reply_text("🔍 Notlar çekiliyor...")
    mesaj = notlari_tara(user[0], user[1])
    await update.message.reply_text(mesaj, parse_mode="Markdown")

async def bilgi_sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect('debis_bot.db'); c = conn.cursor()
    c.execute("DELETE FROM kullanicilar WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()
    jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for j in jobs: j.schedule_removal()
    await update.message.reply_text("🗑️ Bilgiler silindi.")

async def otomatik_kontrol(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    conn = sqlite3.connect('debis_bot.db'); c = conn.cursor()
    c.execute("SELECT email, sifre FROM kullanicilar WHERE user_id=?", (job.chat_id,))
    user = c.fetchone(); conn.close()
    if user:
        mesaj = notlari_tara(user[0], user[1])
        await context.bot.send_message(chat_id=job.chat_id, text=f"🔔 *OTOMATİK KONTROL SONUCU:*\n{mesaj}", parse_mode="Markdown")

if __name__ == '__main__':
    db_kur()
    istanbul_tz = pytz.timezone("Europe/Istanbul")
    defaults = Defaults(tzinfo=istanbul_tz)
    app = Application.builder().token(TOKEN).defaults(defaults).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kayit", kayit_ol))
    app.add_handler(CommandHandler("kontrol", manuel_kontrol))
    app.add_handler(CommandHandler("sil", bilgi_sil))
    
    app.run_polling()
