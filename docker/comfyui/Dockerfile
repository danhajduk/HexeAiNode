FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ARG COMFYUI_REF=master

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip setuptools wheel

RUN git clone --depth 1 --branch "${COMFYUI_REF}" https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI

WORKDIR /opt/ComfyUI

RUN python3 -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 \
    && python3 -m pip install -r requirements.txt

COPY docker/comfyui/run-dual.sh /opt/hexe/run-comfyui-dual.sh
COPY docker/comfyui/socket-proxy.py /opt/hexe/comfyui-socket-proxy.py
RUN chmod +x /opt/hexe/run-comfyui-dual.sh /opt/hexe/comfyui-socket-proxy.py

EXPOSE 8188 8189

ENTRYPOINT ["python3", "main.py"]
CMD ["--listen", "0.0.0.0", "--port", "8188", "--disable-auto-launch"]
