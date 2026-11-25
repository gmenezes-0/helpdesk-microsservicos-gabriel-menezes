FROM python:3.12-slim

# Mesmo uid dos serviços (10001). A pasta /segredos já nasce dele: quando o Docker cria
# o volume jwt-segredo vazio, copia esse dono e essas permissões para o volume.
# Assim o gerador não precisa rodar como root nem de nenhuma capacidade.
RUN useradd --no-create-home --uid 10001 helpdesk \
    && mkdir /segredos && chown helpdesk:helpdesk /segredos && chmod 0700 /segredos

COPY gerar_segredo.py /gerar_segredo.py

USER helpdesk
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

CMD ["python", "/gerar_segredo.py"]
