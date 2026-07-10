# ============ Python 运行阶段 ============
FROM python:3.12-slim

# ffmpeg 用于音频提取
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 后端代码
COPY . .

# 前端构建产物由部署脚本在本地生成，避免远端重复 npm install/build。
COPY frontend/dist /app/app/web/static

EXPOSE 8080

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
