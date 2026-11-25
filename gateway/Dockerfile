FROM python:3.12-slim

# Não roda como root dentro do contêiner. O gateway não guarda dados: não há volume.
RUN useradd --create-home --uid 10001 helpdesk

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

USER helpdesk
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8000

# A imagem slim não tem curl: a checagem usa o próprio Python
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/saude', timeout=2).status == 200 else 1)"]

# --no-proxy-headers: o gateway é a borda do sistema e não confia em
# X-Forwarded-For vindo do cliente; o endereço real vem da conexão TCP.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
