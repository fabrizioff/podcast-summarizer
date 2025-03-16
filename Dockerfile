FROM python:3.9-slim

WORKDIR /app

# Install system dependencies including FFmpeg with all codecs
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    ffmpeg \
    libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default command runs the bot
CMD ["python", "bot.py"]