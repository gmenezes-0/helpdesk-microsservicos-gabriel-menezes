FROM python:3.12-slim

# Mesmo uid dos serviços (10001). A pasta /segredos já nasce dele: quando o Docker cria
# o volume jwt-segredo vazio, copia esse dono e essas permissões para o volume.
# Assim o gerador não precisa rodar como root nem de nenhuma capacidade.
# /mq-segredos recebe as credenciais do RabbitMQ (volume à parte), quando MQ_SEGREDOS_PASTA é definida.
RUN useradd --no-create-home --uid 10001 helpdesk \
    && mkdir /segredos /mq-segredos \
    && chown helpdesk:helpdesk /segredos /mq-segredos && chmod 0700 /segredos /mq-segredos

COPY gerar_segredo.py /gerar_segredo.py

USER helpdesk
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

CMD ["python", "/gerar_segredo.py"]
