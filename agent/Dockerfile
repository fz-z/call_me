FROM python:3.12-slim

WORKDIR /app

# Fix SSL certificate verification for DashScope WebSocket
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY pyproject.toml .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -e . || pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ "livekit-agents[openai,silero,turn-detector]~=1.3" livekit-plugins-noise-cancellation dashscope python-dotenv aiohttp certifi

# Download turn detector and VAD models (via HF mirror for China)
ENV HF_ENDPOINT=https://hf-mirror.com
RUN python -m livekit.agents download-files

COPY *.py .

CMD ["python", "agent.py", "start"]
