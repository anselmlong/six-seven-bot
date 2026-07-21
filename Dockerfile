FROM python:3.11-slim

# System libraries: OpenCV needs libGL/glib; ffmpeg helps with video decoding.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Persist the SQLite DB and EasyOCR weights outside the image via volumes.
CMD ["python", "-m", "sixseven"]
