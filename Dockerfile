# 1. Python 3.10 use karein (Aapke error mein yahi version dikh raha hai)
FROM python:3.10-slim-buster

# 2. Update aur Basic Dependencies install karein
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    gnupg \
    ffmpeg \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 3. Node.js 20 (LTS) ko manually install karein (Taki 'node' command mil sake)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest

# 4. Working directory set karein
WORKDIR /app

# 5. Pehle requirements copy karke install karein (Cache optimization)
COPY requirements.txt .
RUN pip3 install --no-cache-dir -U -r requirements.txt

# 6. Baaki saara code copy karein
COPY . .

# 7. Start command
CMD ["bash", "start"]
