FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-setuptools \
    wget \
    git-lfs \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY ../ /app
COPY pyproject.toml .

# Install PyTorch first
RUN pip3 install --no-cache-dir \
    torch==2.2.2+cu118 \
    torchvision==0.17.2+cu118 \
    torchaudio==2.2.2+cu118 \
    --extra-index-url https://download.pytorch.org/whl/cu118

# Install other project dependencies first
RUN pip3 install --no-cache-dir \
    numpy \
    pillow \
    websockets \
    lerobot \
    "networkx<3.2" \
    runpod

# Install the project (this will install dependencies from pyproject.toml)
RUN pip3 install .

# OVERRIDE with our working versions (this fixes the compatibility issue)
RUN pip3 install --no-cache-dir --force-reinstall \
    huggingface-hub==0.14.1 \
    transformers==4.21.3 \
    diffusers==0.16.1 \
    accelerate==0.19.0 \
    peft==0.3.0

# Download models
RUN git lfs install && \
    git clone --depth 1 https://huggingface.co/phospho-app/so100_strawberry_grape-915h3ndhhf /app/models

EXPOSE 8765

# Run the RunPod handler instead of the eval script directly
CMD ["python3", "-u", "rp_handler.py"]