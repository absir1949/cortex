# ============ 前端构建阶段 ============
FROM node:20-slim AS frontend-build
WORKDIR /frontend

# 依赖层（package.json 单独 COPY 利用缓存）
COPY frontend/package.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build    # 产物: /frontend/dist

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

# 前端构建产物 → FastAPI 托管
COPY --from=frontend-build /frontend/dist /app/app/web/static

EXPOSE 8080

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
