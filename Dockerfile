FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for speedtest and ssh
RUN apt-get update && apt-get install -y \
    ssh \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Environment variable defaults
ENV INFLUX_BUCKET=telegraf
ENV SSH_USER=admin
ENV SSH_KEY_PATH=/app/id_rsa
ENV PYTHONPATH=/app/src

# Default command (can be overridden to run Monitor-Internet.py)
CMD ["python", "src/main.py"]
