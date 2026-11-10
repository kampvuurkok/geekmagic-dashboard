FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Europe/Amsterdam DATA_DIR=/data
WORKDIR /opt/dashboard
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fonts/ fonts/
COPY app/ app/
VOLUME /data
CMD ["python", "app/main.py"]
