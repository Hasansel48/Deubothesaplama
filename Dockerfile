FROM python:3.11-slim

# Gerekli sistem paketlerini kur
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome'u modern yöntemle kur (apt-key yerine gpg kullanıyoruz)
RUN curl -fSsL https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor | tee /usr/share/keyrings/google-chrome.gpg > /dev/null \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && apt-get clean

# Çalışma dizini ayarları
WORKDIR /app
COPY . /app

# Python kütüphanelerini kur
RUN pip install --no-cache-dir -r requirements.txt

# Botu çalıştır
CMD ["python", "notbot.py"]
