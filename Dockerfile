FROM python:3.11-slim

# Sistem paketlerini ve Chrome'u kur
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' \
    && apt-get update && apt-get install -y google-chrome-stable \
    && apt-get clean

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt

# Botun ana dosyasının adı neyse onu yaz (notbot.py demiştik)
CMD ["python", "notbot.py"]
