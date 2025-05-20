FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04
WORKDIR /app
COPY . /app
RUN apt-get update && apt-get install -y python3-pip wget
RUN pip3 install --no-cache-dir torch==2.2.2+cu118 torchvision==0.17.2+cu118 torchaudio==2.2.2+cu118 --extra-index-url https://download.pytorch.org/whl/cu118 && \
    pip3 install --no-cache-dir numpy pillow websockets lerobot "networkx<3.2"
RUN mkdir -p /app/models && pip install -U huggingface-cli && \
    huggingface-cli download phospho-app/so100_strawberry_grape-915h3ndhhf --local-dir /app/models
EXPOSE 8765
CMD ["python3","-u","getting_started/examples/eval_gr00t_so100.py"]