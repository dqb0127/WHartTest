# ============================================
# 多阶段构建 - 优化后的Dockerfile
# 镜像大小：~1.1GB（从1.74GB减少36.8%）
# ============================================

# ============================================
# 第一阶段：构建阶段（包含编译工具）
# ============================================
FROM docker.1ms.run/library/python:3.11-slim AS builder

WORKDIR /build

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 配置 apt 国内镜像加速（清华源）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources

# 安装构建依赖（仅在构建阶段需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装uv（更快的pip替代品）+ 使用清华镜像加速
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple uv

# 复制requirements并安装依赖到虚拟环境
COPY requirements.txt .

# 使用uv直接安装到虚拟环境（uv更快）+ 使用清华镜像加速
RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python --no-cache \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

# 预下载 BM25 稀疏编码模型（用于混合检索）
# 使用 FASTEMBED_CACHE_PATH 环境变量强制指定缓存路径
# 使用 Hugging Face 国内镜像加速下载
ENV HOME=/root \
    FASTEMBED_CACHE_PATH=/root/.cache/fastembed \
    HF_ENDPOINT=https://hf-mirror.com
RUN mkdir -p /root/.cache/fastembed && \
    /opt/venv/bin/python -c "\
import os; \
os.environ['FASTEMBED_CACHE_PATH'] = '/root/.cache/fastembed'; \
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'; \
from fastembed import SparseTextEmbedding; \
m = SparseTextEmbedding('Qdrant/bm25'); \
print('BM25 model downloaded to:', os.environ.get('FASTEMBED_CACHE_PATH')); \
" && ls -la /root/.cache/fastembed/

# ============================================
# 第二阶段：运行阶段（仅包含运行时依赖）
# ============================================
FROM docker.1ms.run/library/python:3.11-slim

WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH" \
    FASTEMBED_CACHE_PATH=/root/.cache/fastembed \
    HF_ENDPOINT=https://hf-mirror.com

# 配置 apt 国内镜像加速（清华源）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources

# 仅安装运行时必需的系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    nodejs \
    npm \
    # Playwright 所需的系统依赖
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    # 中文字体支持（解决截图乱码问题）
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    # 旧版Word文档(.doc)解析支持
    antiword \
    catdoc \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && fc-cache -fv

# 从构建阶段复制虚拟环境（不包含构建工具）
COPY --from=builder /opt/venv /opt/venv

# 安装 Playwright 浏览器（Chromium）
RUN /opt/venv/bin/playwright install chromium

# 安装 agent-browser CLI 工具及其浏览器
# agent-browser 是 AI Agent 专用的浏览器自动化工具
RUN npm install -g agent-browser && \
    agent-browser install

# 从构建阶段复制预下载的 BM25 模型缓存
COPY --from=builder /root/.cache/fastembed /root/.cache/fastembed

# 复制启动脚本和配置文件
COPY entrypoint.sh /app/entrypoint.sh
COPY supervisord.conf /app/supervisord.conf

# 转换换行符并添加执行权限
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# 复制Django项目代码（仅复制必要的Python代码）
COPY manage.py /app/
COPY accounts/ /app/accounts/
COPY api_keys/ /app/api_keys/
COPY knowledge/ /app/knowledge/
COPY langgraph_integration/ /app/langgraph_integration/
COPY mcp_tools/ /app/mcp_tools/
COPY orchestrator_integration/ /app/orchestrator_integration/
COPY projects/ /app/projects/
COPY prompts/ /app/prompts/
COPY requirements/ /app/requirements/
COPY skills/ /app/skills/
COPY testcase_templates/ /app/testcase_templates/
COPY testcases/ /app/testcases/
COPY wharttest_django/ /app/wharttest_django/

# 清理不必要的文件
RUN find /app -type f \( -name "*.sqlite*" -o -name "*.db" -o -name "*.sql" \) -delete && \
    find /app -type d \( -name ".venv" -o -name "venv" -o -name "__pycache__" -o -name ".git" -o -name "*.egg-info" \) -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyo" -delete 2>/dev/null || true

# 创建必要的目录
RUN mkdir -p media static nltk_data /var/log

# 暴露端口
EXPOSE 8000

# 设置启动脚本为入口点
ENTRYPOINT ["/app/entrypoint.sh"]