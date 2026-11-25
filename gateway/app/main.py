"""HelpDesk TI · API Gateway.

Único ponto de entrada do sistema (porta 8000): serve a tela do HelpDesk,
a documentação unificada e encaminha cada rota para o serviço responsável:

    /auth, /usuarios         -> Usuários
    /ativos                  -> Inventário
    /chamados, /notificacoes -> Chamados

O gateway não acessa bancos e não confere o token: cada serviço confere o seu.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse

from app import documentacao, proxy
from app.config import DOCS_ATIVA, NOME_SERVICO, SAUDE_TIMEOUT_SEGUNDOS, SERVICOS
from app.seguranca_http import CabecalhosDeSeguranca

WEB = Path(__file__).parent / "web"
METODOS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    yield
    await proxy.fechar()


app = FastAPI(
    title="HelpDesk TI · API Gateway", version="2.0.0", lifespan=ciclo_de_vida,
    # /docs e /openapi.json são montados abaixo, juntando a documentação dos serviços
    docs_url=None, redoc_url=None, openapi_url=None,
)
app.add_middleware(CabecalhosDeSeguranca)


# ---------- saúde ----------

async def _saude_do_servico(base: str) -> bool:
    try:
        resposta = await proxy.cliente().get(f"{base}/saude", timeout=SAUDE_TIMEOUT_SEGUNDOS)
        return resposta.status_code == 200 and resposta.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


@app.get("/saude", tags=["Saúde"])
async def saude():
    """Mostra quais serviços estão no ar (não exige login).

    Responde 200 enquanto o gateway funciona; `status` fica "degradado" se algum serviço cair.
    """
    nomes = list(SERVICOS)
    resultados = await asyncio.gather(*(_saude_do_servico(SERVICOS[nome]) for nome in nomes))
    servicos = {nome: "ok" if no_ar else "fora do ar" for nome, no_ar in zip(nomes, resultados)}
    return {"status": "ok" if all(resultados) else "degradado", "servico": NOME_SERVICO, "servicos": servicos}


# ---------- documentação ----------

if DOCS_ATIVA:
    @app.get("/openapi.json", include_in_schema=False)
    async def openapi():
        return JSONResponse(await documentacao.montar(app))

    @app.get("/docs", include_in_schema=False)
    def docs():
        return get_swagger_ui_html(openapi_url="/openapi.json", title="HelpDesk TI · API")


# ---------- tela ----------

@app.get("/", include_in_schema=False)
def tela_inicial():
    return FileResponse(WEB / "index.html")


@app.get("/app.js", include_in_schema=False)
def script():
    return FileResponse(WEB / "app.js", media_type="text/javascript")


@app.get("/estilo.css", include_in_schema=False)
def estilo():
    return FileResponse(WEB / "estilo.css", media_type="text/css")


# ---------- encaminhamento (por último: atende tudo que não foi definido acima) ----------

@app.api_route("/{caminho:path}", methods=METODOS, include_in_schema=False)
async def encaminhar(request: Request, caminho: str):
    return await proxy.repassar(request)
