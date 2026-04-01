FROM python:3.12-slim

# ffmpeg 用于音频提取（转录需要）
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 数据目录
VOLUME ["/app/data", "/app/knowledge"]

ENTRYPOINT ["python", "cli.py"]
CMD ["start"]
