# 第一阶段：前端构建阶段
FROM node:20-alpine AS frontend-builder

# 设置工作目录
WORKDIR /app/frontend

# 复制前端代码
COPY frontend/package.json frontend/yarn.lock ./

# 安装依赖
RUN yarn install --frozen-lockfile

# 复制前端源代码
COPY frontend/src ./src
COPY frontend/public ./public
COPY frontend/index.html ./
COPY frontend/tsconfig*.json ./
COPY frontend/vite.config.ts ./

# 构建前端
RUN yarn build

# 第二阶段：后端构建阶段
FROM ghcr.io/astral-sh/uv:alpine AS backend-builder

# 设置工作目录
WORKDIR /app

# 安装构建依赖
RUN apk add --no-cache \
    libxml2-dev \
    libxslt-dev \
    gcc \
    python3-dev \
    musl-dev

# 复制依赖文件
COPY requirements.txt .
COPY pyproject.toml .
COPY web_server.py .
COPY utils/ ./utils/
COPY services/ ./services/

# 创建虚拟环境并安装Python依赖
RUN uv venv /app/.venv --python 3.10 && \
    uv pip install --no-build  --no-cache-dir -r requirements.txt

# 从前端构建阶段复制构建后的文件
COPY --from=frontend-builder /app/frontend/dist/ /app/frontend/dist/

# 创建必要的目录
RUN mkdir -p /app/data /app/logs && \
    chmod -R 755 /app/data /app/logs

# # 设置默认环境变量（可被.env文件覆盖）
# ENV API_KEY=""
# ENV API_URL=""
# ENV API_MODEL="gpt-4"
# ENV API_TIMEOUT="60"
# ENV TOKEN=""
# ENV MODE="RELEASE"
# ENV LOG_LEVEL="INFO"
# ENV ANNOUNCEMENT_TEXT="欢迎使用股票分析系统"
# ENV USER_TOKEN=""
# ENV TUSHARE_TOKEN=""

# 暴露端口
EXPOSE 8888

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8888/api/config || exit 1

# 启动命令
ENTRYPOINT ["uv", "run", "web_server.py"] 