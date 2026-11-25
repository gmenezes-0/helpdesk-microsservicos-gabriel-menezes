"""Repasse das requisições para o serviço certo.

- O método, o caminho, a query string, o corpo e o Authorization vão como vieram.
- X-Forwarded-For é sempre reescrito com o endereço de quem conectou no gateway;
  valores enviados pelo cliente (X-Forwarded-*, X-Real-IP, Forwarded) são descartados.
- Cabeçalhos de conexão (hop-by-hop) não são repassados, nem na ida nem na volta.
- Serviço fora do ar ou que não responde no tempo limite: 503 com mensagem genérica.
- Nada de cabeçalhos ou tokens nos logs: só o método, o caminho e o tipo do erro.
"""
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.config import NOMES, ROTAS, SERVICOS, TAMANHO_MAXIMO_REQUISICAO, TIMEOUT_SEGUNDOS, log

# Cabeçalhos que valem só para uma conexão (RFC 9110, seção 7.6.1)
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection",
              "te", "trailer", "transfer-encoding", "upgrade"}

# Enviados pelo cliente, não são confiáveis: o gateway define os seus
CABECALHOS_DE_ORIGEM = {"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "x-forwarded-port",
                        "x-real-ip", "forwarded"}

# content-length é recalculado; accept-encoding fica de fora para a resposta vir sem compressão
NAO_REPASSAR_NA_IDA = HOP_BY_HOP | CABECALHOS_DE_ORIGEM | {"content-length", "accept-encoding"}

# date e server são definidos pelo próprio gateway; o corpo já vem descomprimido
NAO_REPASSAR_NA_VOLTA = HOP_BY_HOP | {"content-length", "content-encoding", "date", "server"}

_cliente: httpx.AsyncClient | None = None


def novo_cliente(**opcoes) -> httpx.AsyncClient:
    # trust_env=False: chamadas internas não passam por proxies configurados no ambiente
    return httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS, follow_redirects=False, trust_env=False, **opcoes)


def cliente() -> httpx.AsyncClient:
    """Cliente HTTP compartilhado (reaproveita conexões entre requisições)."""
    global _cliente
    if _cliente is None:
        _cliente = novo_cliente()
    return _cliente


def usar(novo: httpx.AsyncClient | None) -> None:
    """Troca o cliente HTTP (os testes usam um cliente com respostas simuladas)."""
    global _cliente
    _cliente = novo


async def fechar() -> None:
    global _cliente
    if _cliente is not None:
        await _cliente.aclose()
    _cliente = None


def servico_da_rota(caminho: str) -> str | None:
    """Nome do serviço que atende o caminho, ou None se nenhum atende."""
    for prefixo, servico in ROTAS.items():
        if caminho == prefixo or caminho.startswith(prefixo + "/"):
            return servico
    return None


def indisponivel(servico: str) -> JSONResponse:
    return JSONResponse(status_code=503, content={
        "detail": f"O serviço de {NOMES[servico]} está indisponível no momento. Tente novamente em instantes."})


def nao_encontrado() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


def cabecalhos_de_ida(request: Request) -> list[tuple[str, str]]:
    conexao = {item.strip().lower() for item in request.headers.get("connection", "").split(",") if item.strip()}
    cabecalhos = [(nome, valor) for nome, valor in request.headers.items()
                  if nome.lower() not in NAO_REPASSAR_NA_IDA and nome.lower() not in conexao]
    if request.client:
        cabecalhos.append(("x-forwarded-for", request.client.host))
    cabecalhos.append(("x-forwarded-proto", request.url.scheme))
    return cabecalhos


async def repassar(request: Request) -> Response:
    caminho = request.url.path
    servico = servico_da_rota(caminho)
    # Caminhos com "." ou ".." poderiam ser normalizados para outra rota no meio do caminho
    if servico is None or any(parte in (".", "..") for parte in caminho.split("/")):
        return nao_encontrado()

    corpo = await request.body()
    if len(corpo) > TAMANHO_MAXIMO_REQUISICAO:  # também cobre corpo enviado sem Content-Length
        return JSONResponse(status_code=413, content={"detail": "Requisição grande demais."})

    caminho_original = (request.scope.get("raw_path") or caminho.encode()).decode("latin-1")
    query = request.scope.get("query_string", b"").decode("latin-1")
    url = SERVICOS[servico] + caminho_original + (f"?{query}" if query else "")

    try:
        resposta = await cliente().request(request.method, url, headers=cabecalhos_de_ida(request), content=corpo)
    except httpx.TimeoutException:
        log.warning("Tempo limite esgotado ao repassar %s %s para %s", request.method, caminho, servico)
        return indisponivel(servico)
    except httpx.HTTPError as erro:  # conexão recusada, nome não encontrado, conexão caiu...
        log.warning("Falha ao repassar %s %s para %s: %s", request.method, caminho, servico, type(erro).__name__)
        return indisponivel(servico)

    saida = Response(content=resposta.content, status_code=resposta.status_code)
    for nome, valor in resposta.headers.multi_items():
        if nome.lower() not in NAO_REPASSAR_NA_VOLTA:
            saida.headers.append(nome, valor)
    return saida
