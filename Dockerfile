FROM python:3.11-slim

# ffmpeg ត្រូវការសម្រាប់ yt-dlp បម្លែងទៅ mp3
# libglib2.0-0, libgl1 ត្រូវការសម្រាប់ opencv-python-headless (dependency របស់ rembg)
# tesseract-ocr + tesseract-ocr-khm (ខ្មែរ) + tesseract-ocr-eng (អង់គ្លេស) សម្រាប់ OCR
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg libglib2.0-0 libgl1 \
        tesseract-ocr tesseract-ocr-khm tesseract-ocr-eng && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# yt-dlp ត្រូវ update ជាប្រចាំ ព្រោះ YouTube ផ្លាស់ប្តូរ detection ញឹកញាប់
# ការ install ថ្មីបំផុតត្រង់ពេល build ជួយកាត់បន្ថយហានិភ័យត្រូវ block
RUN pip install --no-cache-dir --upgrade yt-dlp

COPY song_search_bot.py .

# DATA_DIR (persistent disk) - mount point កំណត់ក្នុង render.yaml
ENV DATA_DIR=/data

CMD ["python", "song_search_bot.py"]
