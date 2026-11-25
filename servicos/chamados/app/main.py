"""HelpDesk TI · serviço de Chamados.

Dono dos chamados e comentários. Confere o token JWT localmente (mesmo segredo
do serviço de Usuários) e consulta Usuários e Inventário por HTTP, com tempo limite,
repassando o token de quem fez o pedido. Os fatos que geram aviso viram eventos na
caixa de saída, publicados no RabbitMQ por uma thread própria (app/eventos/).
"""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app import clientes, dados_exemplo
from app.chamados.rotas import router as chamados_router
from app.config import DOCS_ATIVA, NOME_SERVICO, RABBITMQ_HOST, log
from app.database import Base, SessionLocal, engine, get_db
from app.erros import NaoEncontrado, RegraDeNegocio, SemPermissao, ServicoIndisponivel
from app.eventos import modelos as _modelos_eventos  # noqa: F401  (registra a tabela eventos_saida)
from app.eventos.publicador import Publicador
from app.seguranca_http import CabecalhosDeSeguranca


publicador: Publicador | None = None


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Cria as tabelas e, se pedido, os dados de exemplo; liga o publicador de eventos.

    Ao parar, encerra o publicador e as conexões HTTP. Sem RABBITMQ_HOST, os eventos
    ficam guardados na caixa de saída até o publicador ser ligado.
    """
    global publicador
    Base.metadata.create_all(engine)
    if os.getenv("DADOS_EXEMPLO", "1") == "1":
        with SessionLocal() as db:
            dados_exemplo.carregar(db)
    if RABBITMQ_HOST:
        publicador = Publicador()
        publicador.iniciar()
    else:
        log.warning("RABBITMQ_HOST não definido: os eventos ficam pendentes na caixa de saída.")
    yield
    if publicador is not None:
        publicador.parar()
        publicador = None
    clientes.fechar()


app = FastAPI(
    title="HelpDesk TI · Chamados", version="2.0.0", lifespan=ciclo_de_vida,
    docs_url="/docs" if DOCS_ATIVA else None, redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ATIVA else None,
)
app.add_middleware(CabecalhosDeSeguranca)

app.include_router(chamados_router)


@app.exception_handler(NaoEncontrado)
def tratar_nao_encontrado(request: Request, erro: NaoEncontrado):
    return JSONResponse(status_code=404, content={"detail": str(erro)})


@app.exception_handler(RegraDeNegocio)
def tratar_regra(request: Request, erro: RegraDeNegocio):
    return JSONResponse(status_code=422, content={"detail": str(erro)})


@app.exception_handler(SemPermissao)
def tratar_sem_permissao(request: Request, erro: SemPermissao):
    return JSONResponse(status_code=403, content={"detail": str(erro)})


@app.exception_handler(ServicoIndisponivel)
def tratar_servico_indisponivel(request: Request, erro: ServicoIndisponivel):
    # Mensagem genérica: o motivo (timeout, conexão recusada...) fica só no log
    return JSONResponse(status_code=503, content={"detail": str(erro)})


@app.exception_handler(IntegrityError)
def tratar_conflito(request: Request, erro: IntegrityError):
    # Não expõe detalhes do banco na resposta
    return JSONResponse(status_code=409, content={"detail": "O registro conflita com outro já existente."})


@app.get("/saude", tags=["Saúde"])
def saude(db: Session = Depends(get_db)):
    """Responde se o serviço e o seu banco estão funcionando (não exige login)."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        log.exception("Banco de chamados indisponível")
        return JSONResponse(status_code=503, content={"status": "falha", "servico": NOME_SERVICO})
    return {"status": "ok", "servico": NOME_SERVICO}
