# =========================
# Stage 1: build OpenSSL 3.5.x + Python 3.12 + venv on CentOS 7
# =========================
FROM centos:7.9.2009 AS pybuilder

ARG OPENSSL_VERSION=3.5.5
ARG PYTHON_VERSION=3.12.13

ENV OPENSSL_PREFIX=/usr/local/openssl-${OPENSSL_VERSION}
ENV PYTHON_PREFIX=/opt/python-3.12
ENV LD_LIBRARY_PATH=${PYTHON_PREFIX}/lib:${OPENSSL_PREFIX}/lib

WORKDIR /tmp

# CentOS 7 已归档，切到 vault
RUN sed -i 's/^mirrorlist=/#mirrorlist=/g' /etc/yum.repos.d/CentOS-*.repo && \
    sed -i 's|^#baseurl=http://mirror.centos.org/centos/$releasever|baseurl=http://vault.centos.org/7.9.2009|g' /etc/yum.repos.d/CentOS-*.repo && \
    yum clean all && \
    yum makecache

# 构建 OpenSSL / Python 所需依赖
RUN yum install -y \
    gcc \
    gcc-c++ \
    make \
    perl \
    perl-core \
    perl-IPC-Cmd \
    wget \
    tar \
    xz \
    bzip2-devel \
    expat-devel \
    gdbm-devel \
    libffi-devel \
    ncurses-devel \
    readline-devel \
    sqlite-devel \
    tk-devel \
    xz-devel \
    zlib-devel \
    findutils \
    ca-certificates && \
    yum clean all

# 1) 编译安装 OpenSSL 3.5.x
RUN wget https://www.openssl.org/source/openssl-${OPENSSL_VERSION}.tar.gz && \
    tar -xzf openssl-${OPENSSL_VERSION}.tar.gz && \
    cd openssl-${OPENSSL_VERSION} && \
    ./config \
      --prefix=${OPENSSL_PREFIX} \
      --openssldir=${OPENSSL_PREFIX} \
      --libdir=lib \
      shared \
      zlib && \
    make -j"$(nproc)" && \
    make install_sw && \
    echo "${OPENSSL_PREFIX}/lib" > /etc/ld.so.conf.d/openssl-${OPENSSL_VERSION}.conf && \
    ldconfig

# 2) 用自定义 OpenSSL 编译安装 Python 3.12
RUN wget https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz && \
    tar -xzf Python-${PYTHON_VERSION}.tgz && \
    cd Python-${PYTHON_VERSION} && \
    ./configure \
      --prefix=${PYTHON_PREFIX} \
      --enable-shared \
      --with-openssl=${OPENSSL_PREFIX} \
      --with-openssl-rpath=auto \
      --with-ensurepip=install \
      --enable-loadable-sqlite-extensions && \
    make -j"$(nproc)" && \
    make altinstall && \
    echo "${PYTHON_PREFIX}/lib" > /etc/ld.so.conf.d/python3.12.conf && \
    ldconfig

# 3) 先验证 ssl/sqlite3 模块可用，避免后面 pip 才失败
RUN ${PYTHON_PREFIX}/bin/python3.12 -c "import ssl, sqlite3; print(ssl.OPENSSL_VERSION); print(sqlite3.sqlite_version)"

# 4) 创建 venv
RUN ${PYTHON_PREFIX}/bin/python3.12 -m venv /opt/venv

# 5) 安装 agent 依赖
COPY dptest-agent-v2/codes/requirements.txt /tmp/requirements.txt

RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# 6) 瘦身：删除测试/缓存/静态库/源码
RUN find ${PYTHON_PREFIX} -type d \( -name test -o -name tests -o -name idle_test \) -prune -exec rm -rf {} + && \
    find ${PYTHON_PREFIX} -type f \( -name '*.pyc' -o -name '*.pyo' -o -name 'libpython*.a' \) -delete && \
    find /opt/venv -type d -name '__pycache__' -prune -exec rm -rf {} + && \
    find /opt/venv -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete && \
    rm -rf /root/.cache /tmp/Python-${PYTHON_VERSION} /tmp/Python-${PYTHON_VERSION}.tgz && \
    rm -rf /tmp/openssl-${OPENSSL_VERSION} /tmp/openssl-${OPENSSL_VERSION}.tar.gz


# =========================
# Stage 2: final runtime image
# =========================
FROM centos:7.9.2009

ARG OPENSSL_VERSION=3.5.5

ENV OPENSSL_PREFIX=/usr/local/openssl-${OPENSSL_VERSION}
ENV PYTHON_PREFIX=/opt/python-3.12

WORKDIR /usr/local/dproxy

# 原有 engine 目录 + agent 目录
RUN mkdir -p \
    /usr/local/dproxy/app \
    /usr/local/dproxy/lib64 \
    /usr/local/dproxy/uconf \
    /etc/dproxy \
    /etc/dproxy/backup \
    /usr/share/dproxy/cert \
    /usr/share/dproxy/license \
    /opt/dptest-agent-v2/codes \
    /opt/dptest-agent-v2/templates \
    /opt/dptest-agent-v2/data \
    /opt/dptest-agent-v2/data/compiled \
    /tmp/dptest-agent-v2/rendered

# engine 原有内容
COPY app/ /usr/local/dproxy/app/
COPY lib64/ /usr/local/dproxy/lib64/
COPY uconf/ /usr/local/dproxy/uconf/
COPY dpdkproxy.conf /etc/dproxy/
COPY cert/ /usr/share/dproxy/cert/
COPY license/ /usr/share/dproxy/license/

# agent 代码和模板
COPY dptest-agent-v2/codes/ /opt/dptest-agent-v2/codes/
COPY dptest-agent-v2/templates/ /opt/dptest-agent-v2/templates/

# 只复制运行时：OpenSSL + Python + venv
COPY --from=pybuilder ${OPENSSL_PREFIX} ${OPENSSL_PREFIX}
COPY --from=pybuilder ${PYTHON_PREFIX} ${PYTHON_PREFIX}
COPY --from=pybuilder /opt/venv /opt/venv

# 配置动态库
RUN printf "/usr/local/dproxy/lib64\n${OPENSSL_PREFIX}/lib\n${PYTHON_PREFIX}/lib\n" > /etc/ld.so.conf.d/dptest-engine.conf && \
    ldconfig && \
    chmod +x /usr/local/dproxy/app/dpdkproxy

# 兼容旧路径（如果代码里还有 /opt/dptest-agent）
RUN ln -s /opt/dptest-agent-v2 /opt/dptest-agent

# 运行时环境变量
ENV LD_LIBRARY_PATH=/usr/local/dproxy/lib64:${OPENSSL_PREFIX}/lib:${PYTHON_PREFIX}/lib
ENV PATH=/opt/venv/bin:${PYTHON_PREFIX}/bin:${OPENSSL_PREFIX}/bin:$PATH
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# dptest-agent 默认配置
ENV DPTEST_TEMPLATE_DIR=/opt/dptest-agent-v2/templates \
    DPTEST_DEPLOY_DIR=/etc/dproxy \
    DPTEST_DEPLOY_FILENAME=dpdkproxy.conf \
    DPTEST_BACKUP_DIR=/etc/dproxy/backup \
    DPTEST_RENDER_DIR=/tmp/dptest-agent-v2/rendered \
    DPTEST_STRICT_PLACEHOLDER_CHECK=true \
    DPTEST_ALLOW_OVERWRITE=true \
    DPTEST_ENGINE_MONITOR_URL=http://127.0.0.1:10086/run/monitor \
    DPTEST_ENGINE_MONITOR_TIMEOUT=5 \
    DPTEST_STAGE_MAP=0:delay,1:ramp_up,2:stair_step,3:steady_state,4:ramp_down \
    DPTEST_MANIFEST_FILENAME=manifest.json \
    DPTEST_V2_BASE_DIR=/opt/dptest-agent-v2 \
    DPTEST_V2_DATA_DIR=/opt/dptest-agent-v2/data \
    DPTEST_V2_DB_PATH=/opt/dptest-agent-v2/data/dptest_agent_v2.db \
    DPTEST_V2_COMPILED_DIR=/opt/dptest-agent-v2/data/compiled

# agent API 端口；10086 是压测运行时 monitor 端口
EXPOSE 18081 10086

# 默认启动 agent；dpdkproxy 由 agent API 触发
WORKDIR /opt/dptest-agent-v2/codes
CMD ["python", "-m", "uvicorn", "dptest_agent_service_v2:app", "--host", "0.0.0.0", "--port", "18081"]
