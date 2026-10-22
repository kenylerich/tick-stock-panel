# AKShare 桥复用主镜像作底座: 主镜像本地已有 (python3.11 + pip),
# 避免额外拉取 docker.io 基础镜像; 层共享, 磁盘增量仅为 akshare 依赖。
ARG BASE_IMAGE=tick-stock-panel-app:latest
FROM ${BASE_IMAGE}
ARG USE_CN_MIRROR=1
ARG PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PYPI_FALLBACK=https://mirrors.aliyun.com/pypi/simple

WORKDIR /srv
RUN if [ "$USE_CN_MIRROR" = "1" ]; then \
        pip install --no-cache-dir akshare fastapi uvicorn -i "$PYPI_INDEX" || \
        pip install --no-cache-dir akshare fastapi uvicorn -i "$PYPI_FALLBACK"; \
    else \
        pip install --no-cache-dir akshare fastapi uvicorn; \
    fi
COPY main.py .
EXPOSE 3020
# 单进程足够: 只读桥接 + 进程内缓存; 与主容器互不影响。
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3020"]
