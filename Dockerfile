FROM python:3.12-slim

# Default timezone used by the app (IANA name)
ENV TIMEZONE=America/New_York

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user matching the host UID/GID so bind-mounted files don't
# end up owned by root on the host after container writes.
ARG USER_UID=1000
ARG USER_GID=1000
RUN groupadd -g $USER_GID app && useradd -m -u $USER_UID -g $USER_GID -s /bin/bash app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
