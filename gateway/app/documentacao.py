"""Documentação única da API (Swagger em /docs), montada a partir dos serviços.

Os serviços não ficam expostos, então o gateway busca o /openapi.json de cada um,
mantém só as rotas que ele realmente encaminha para aquele serviço e junta tudo
com as rotas do próprio gateway. Um serviço fora do ar não derruba a documentação:
as rotas dele só deixam de aparecer, com um aviso na descrição.
"""
import asyncio

import httpx
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app import proxy
from app.config import SAUDE_TIMEOUT_SEGUNDOS, SERVICOS, log

DESCRICAO = (
    "API do HelpDesk TI em microsserviços. Todas as rotas passam por este gateway, "
    "que encaminha cada uma para o serviço responsável. Clique em **Authorize** e cole "
    "o token recebido em `POST /auth/login`."
)


async def _buscar(nome: str, base: str) -> dict | None:
    try:
        resposta = await proxy.cliente().get(f"{base}/openapi.json", timeout=SAUDE_TIMEOUT_SEGUNDOS)
        if resposta.status_code == 200:
            especificacao = resposta.json()
            if isinstance(especificacao, dict):
                return especificacao
        log.warning("Documentação do serviço %s indisponível: HTTP %d", nome, resposta.status_code)
    except (httpx.HTTPError, ValueError) as erro:
        log.warning("Documentação do serviço %s indisponível: %s", nome, type(erro).__name__)
    return None


async def montar(app: FastAPI) -> dict:
    documento = get_openapi(title="HelpDesk TI · API Gateway", version="2.0.0",
                            description=DESCRICAO, routes=app.routes)
    caminhos = documento.setdefault("paths", {})
    componentes = documento.setdefault("components", {})

    nomes = list(SERVICOS)
    especificacoes = await asyncio.gather(*(_buscar(nome, SERVICOS[nome]) for nome in nomes))
    fora = []
    for nome, especificacao in zip(nomes, especificacoes):
        if especificacao is None:
            fora.append(nome)
            continue
        for caminho, operacoes in especificacao.get("paths", {}).items():
            if proxy.servico_da_rota(caminho) == nome:  # só o que o gateway encaminha a este serviço
                caminhos[caminho] = operacoes
        for tipo, itens in especificacao.get("components", {}).items():
            destino = componentes.setdefault(tipo, {})
            for chave, valor in itens.items():
                if chave in destino and destino[chave] != valor:
                    log.warning("Componente %s/%s diferente no serviço %s; mantido o primeiro", tipo, chave, nome)
                    continue
                destino[chave] = valor

    if fora:
        documento["info"]["description"] += (
            "\n\n**Fora do ar agora (rotas não listadas):** " + ", ".join(fora) + ".")
    return documento
