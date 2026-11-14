# 检验报告智能解读 —— CPU 推理镜像
# 模型不进镜像：首次启动从 hf-mirror 下载到 /models/hf（约 485MB），挂 volume 后重建不用重下
FROM python:3.12-slim

# ---- 国内镜像源（构建时可用 --build-arg 覆盖）----
# PIP_INDEX_URL: PyPI 镜像，实测清华约 9.6MB/s（直连 pypi.org 在这网络只有 20KB/s）
# TORCH_INDEX_URL: torch 的 CPU 轮子目录；默认阿里镜像（178MB 约 3MB/s）
#   若某天阿里镜像缺版本，改回官方：--build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TORCH_INDEX_URL=https://mirrors.aliyun.com/pytorch-wheels/cpu
ARG TORCH_VERSION=2.6.0+cpu

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
# torch 必须来自 CPU 专用目录（PyPI 上的 Linux torch 带 CUDA，会多塞 2~5GB 的 nvidia 依赖）
RUN pip install --index-url ${PIP_INDEX_URL} --timeout 60 --retries 3 \
        --find-links ${TORCH_INDEX_URL} "torch==${TORCH_VERSION}" \
 && pip install --index-url ${PIP_INDEX_URL} --timeout 60 --retries 3 \
        -r requirements-docker.txt

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
