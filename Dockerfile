# 检验报告智能解读 —— CPU 推理镜像
# 模型不进镜像：首次启动从 HF 镜像源下载到 /models/hf（约 485MB），挂 volume 后重建镜像不用重下
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HOME=/models/hf

# 系统库：opencv/onnxruntime 运行时要 libglib/libgomp，curl 给 HEALTHCHECK 用
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖层单独缓存：只要 requirements 不变，改代码不会触发重装
COPY requirements-docker.txt ./
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install -r requirements-docker.txt

COPY scripts/ ./scripts/
COPY data/ ./data/

# 非 root 运行；/models 预建好属主，named volume 首次挂载会继承它
RUN mkdir -p /models/hf \
 && useradd --create-home --uid 1000 appuser \
 && chown -R appuser:appuser /app /models
USER appuser

EXPOSE 7862 7860

# 默认跑 FastAPI（本镜像的 CMD 对应 /api/health）；compose 里的 ui 服务会覆盖 command 与 healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7862/api/health || exit 1

CMD ["python", "scripts/api.py"]
