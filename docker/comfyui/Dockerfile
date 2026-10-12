FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ARG COMFYUI_REF=f8e51b674c75f41b3960d65ce83f77301ab297c9
ARG COMFYUI_CONTROLNET_AUX_REF=main
ARG COMFYUI_PULID_REF=main
ARG COMFYUI_IPADAPTER_REF=a0f451a5113cf9becb0847b92884cb10cbdec0ef

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        build-essential \
        cmake \
        curl \
        git \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip setuptools wheel

RUN git init /opt/ComfyUI \
    && git -C /opt/ComfyUI remote add origin https://github.com/comfyanonymous/ComfyUI.git \
    && git -C /opt/ComfyUI fetch --depth 1 origin "${COMFYUI_REF}" \
    && git -C /opt/ComfyUI checkout --detach FETCH_HEAD

WORKDIR /opt/ComfyUI

RUN python3 -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 \
    && python3 -m pip install -r requirements.txt

RUN git clone --depth 1 --branch "${COMFYUI_CONTROLNET_AUX_REF}" https://github.com/Fannovel16/comfyui_controlnet_aux.git custom_nodes/comfyui_controlnet_aux \
    && python3 -m pip install -r custom_nodes/comfyui_controlnet_aux/requirements.txt

RUN git clone --depth 1 --branch "${COMFYUI_PULID_REF}" https://github.com/cubiq/PuLID_ComfyUI.git custom_nodes/PuLID_ComfyUI \
    && python3 -m pip install -r custom_nodes/PuLID_ComfyUI/requirements.txt

RUN git init custom_nodes/ComfyUI_IPAdapter_plus \
    && git -C custom_nodes/ComfyUI_IPAdapter_plus remote add origin https://github.com/cubiq/ComfyUI_IPAdapter_plus.git \
    && git -C custom_nodes/ComfyUI_IPAdapter_plus fetch --depth 1 origin "${COMFYUI_IPADAPTER_REF}" \
    && git -C custom_nodes/ComfyUI_IPAdapter_plus checkout --detach FETCH_HEAD

COPY docker/comfyui/run-dual.sh /opt/hexe/run-comfyui-dual.sh
COPY docker/comfyui/run-cpu-limited.py /opt/hexe/run-cpu-limited.py
COPY docker/comfyui/socket-proxy.py /opt/hexe/comfyui-socket-proxy.py
RUN chmod +x /opt/hexe/run-comfyui-dual.sh /opt/hexe/run-cpu-limited.py /opt/hexe/comfyui-socket-proxy.py

EXPOSE 8188 8189

ENTRYPOINT ["python3", "main.py"]
CMD ["--listen", "0.0.0.0", "--port", "8188", "--disable-auto-launch"]
