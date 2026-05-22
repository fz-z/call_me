FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir "livekit-agents[openai,silero,turn-detector]~=1.3" livekit-plugins-noise-cancellation dashscope python-dotenv aiohttp

# Download turn detector and VAD models
RUN python -m livekit.agents download-files

COPY *.py .

CMD ["python", "agent.py", "start"]
