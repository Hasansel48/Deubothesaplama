# Debian Bookworm tabanlı Python imajı (daha kararlıdır)
FROM python:3.11-slim-bookworm

# Sistem güncellemeleri ve Chrome için gerekli temel paketler
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y \
    google-chrome-stable \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Çalışma dizini
WORKDIR /app

# Bağımlılıklar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Proje dosyaları
COPY . .

# SQLite izinleri
RUN touch debis_bot.db && chmod 666 debis_bot.db

CMD ["python", "notbot.py"]
