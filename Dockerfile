FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tar \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 项目代码
COPY . .

# 下载 subs-check 二进制
RUN chmod +x scripts/install_subscheck.sh && ./scripts/install_subscheck.sh

# 数据与输出目录
RUN mkdir -p data output

EXPOSE 8899

HEALTHCHECK --interval=60s --timeout=10s --start-period=15s \
    CMD curl -fsS http://127.0.0.1:8899/api/nodes/stats || exit 1

CMD ["python", "main.py"]
