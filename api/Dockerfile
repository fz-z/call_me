FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir fastapi uvicorn[standard] pyjwt "passlib[bcrypt]>=1.7.4" "bcrypt>=4.0,<4.1" aiohttp aiosqlite python-dotenv python-multipart livekit-api

COPY *.py .

RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
