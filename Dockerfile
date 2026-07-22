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
# Bound native (torch/OpenBLAS/MKL) thread pools — a per-CPU default spikes
# memory and CPU during OCR and risks OOM-killing the container.
ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

# Persist the SQLite DB and EasyOCR weights outside the image via volumes.
CMD ["python", "-m", "sixseven"]
