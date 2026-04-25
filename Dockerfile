# 1. Updated Base Image: Node.js 20 (LTS) aur Python 3.11/3.12 ka use karein
FROM nikolaik/python-nodejs:python3.11-nodejs20-slim

# 2. Environment variables set karein
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. System dependencies install karein
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 4. Working directory set karein
WORKDIR /app

# 5. Pehle requirements copy karein (Layer caching ke liye)
# Isse agar aap sirf code change karenge, toh dependencies baar-baar install nahi hongi
COPY requirements.txt .
RUN pip3 install --no-cache-dir -U -r requirements.txt

# 6. Baaki bacha hua code copy karein
COPY . .

# 7. Command ko fix karein
# Agar aapki file ka naam 'start' hai toh:
CMD ["bash", "start"]
