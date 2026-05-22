FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir "livekit-agents[openai,silero,turn-detector]~=1.3" livekit-plugins-noise-cancellation dashscope python-dotenv aiohttp

COPY *.py .

CMD ["python", "agent.py", "start"]
