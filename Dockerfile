FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=coredns/coredns:1.14.3 /coredns /usr/local/bin/coredns

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /etc/coredns/zones /etc/dns

ENTRYPOINT ["honcho", "start"]