FROM python:3.12-slim

WORKDIR /app

# Fix SSL certificate verification for DashScope WebSocket
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY pyproject.toml .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -e . || pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ "livekit-agents[openai,silero,turn-detector]~=1.3" livekit-plugins-noise-cancellation dashscope python-dotenv aiohttp certifi

# Preload the exact ONNX asset opened by every registered turn-detector
# revision. They are opened with `local_files_only=True` during a pipeline
# call, so a clean worker cannot fetch them lazily. Avoid downloading full
# repository snapshots: they include unused, much larger model artifacts.
# Also avoid LiveKit's broad `download-files` CLI: its native download helper
# can abort after a successful transfer in this environment.
ENV HF_ENDPOINT=https://hf-mirror.com
ENV HF_HUB_DISABLE_XET=1
RUN python -c 'from huggingface_hub import hf_hub_download; from livekit.plugins.turn_detector.models import HG_MODEL, MODEL_REVISIONS, ONNX_FILENAME; [hf_hub_download(HG_MODEL, ONNX_FILENAME, subfolder="onnx", revision=revision) for revision in MODEL_REVISIONS.values()]'

COPY *.py ./
COPY realtime ./realtime

CMD ["python", "agent.py", "start"]
