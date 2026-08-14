FROM python:3.11-slim

# ffmpeg ត្រូវការសម្រាប់ yt-dlp បម្លែងទៅ mp3
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY song_search_bot.py .

# DATA_DIR (persistent disk) - mount point កំណត់ក្នុង render.yaml
ENV DATA_DIR=/data

CMD ["python", "song_search_bot.py"]
