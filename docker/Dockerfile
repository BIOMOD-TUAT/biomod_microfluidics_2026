FROM ubuntu:22.04

# 対話的プロンプトを無効化
ENV DEBIAN_FRONTEND=noninteractive

# 基本ツールのインストール
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    software-properties-common \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    git \
    nano \
    psmisc \
    procps \
    && rm -rf /var/lib/apt/lists/*

# OpenFOAM (ESI版 v2312) のリポジトリ追加とインストール
RUN wget -q -O - https://dl.openfoam.com/add-debian-repo.sh | bash \
    && apt-get update \
    && apt-get install -y openfoam2312-default \
    && rm -rf /var/lib/apt/lists/*

# OpenFOAMの環境変数を自動読み込み
RUN echo "source /usr/lib/openfoam/openfoam2312/etc/bashrc" >> /root/.bashrc

# Pythonライブラリのインストール
COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Alternative allocator for runtime-only performance experiments.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjemalloc2 \
        libtcmalloc-minimal4 \
        numactl \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリ
WORKDIR /workspace

# デフォルトシェルをbashに変更
SHELL ["/bin/bash", "-c"]

CMD ["/bin/bash"]
