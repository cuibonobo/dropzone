FROM python:3.12-alpine AS builder

RUN apk add --no-cache gcc musl-dev libffi-dev

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


FROM python:3.12-alpine

# Default timezone used by the app (IANA name)
ENV TIMEZONE=America/New_York

RUN apk add --no-cache git unzip tzdata

# Create a non-root user matching the host UID/GID so bind-mounted files don't
# end up owned by root on the host after container writes.
ARG USER_UID=1000
ARG USER_GID=1000
RUN addgroup -g $USER_GID app && adduser -D -u $USER_UID -G app app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels /wheels/*.whl && rm -rf /wheels

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
