# 使用 Python 3.11 官方镜像作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
RUN apt-get -o Acquire::Retries=10 update && apt-get -o Acquire::Retries=10 install -y --fix-missing --no-install-recommends \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN pip install uv

# 复制依赖文件
COPY requirements.txt .

# 使用 uv 安装 Python 依赖 + 使用清华镜像加速
RUN uv pip install --system \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

# 复制supervisord配置
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# 复制MCP服务代码（仅复制必要文件）
COPY ms_mcp_api.py /app/
COPY WHartTest_tools.py /app/
COPY playwright-mcp-config.json /app/

# 创建日志目录
RUN mkdir -p /var/log/supervisor

# 暴露两个服务的端口
# ms_mcp_api.py 使用端口 8007
# WHartTest_tools.py 使用端口 8006
EXPOSE 8006 8007

# 使用 supervisord 启动两个服务
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
