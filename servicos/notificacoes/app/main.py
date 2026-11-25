"""HelpDesk TI · serviço de Notificações.

Dono dos avisos enviados aos usuários. Recebe os eventos ChamadoAberto, ChamadoAtribuido
e ChamadoResolvido pela fila do RabbitMQ (consumidor numa thread própria) e os grava no
seu banco. Confere o token JWT localmente, com o mesmo segredo do serviço de Usuários.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import DOCS_ATIVA, NOME_SERVICO, RABBITMQ_HOST, log
from app.database import Base, engine, get_db
from app.eventos.consumidor import Consumidor
from app.notificacoes.rotas import router as notificacoes_router
from app.seguranca_http import CabecalhosDeSeguranca

consumidor: Consumidor | None = None


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Cria as tabelas e liga o consumidor da fila (se o RabbitMQ estiver configurado)."""
    global consumidor
    Base.metadata.create_all(engine)
    if RABBITMQ_HOST:
        consumidor = Consumidor()
        consumidor.iniciar()
    else:
        log.warning("RABBITMQ_HOST não definido: o consumidor de eventos não foi iniciado.")
    yield
    if consumidor is not None:
        consumidor.parar()
        consumidor = None


app = FastAPI(
    title="HelpDesk TI · Notificações", version="2.0.0", lifespan=ciclo_de_vida,
    docs_url="/docs" if DOCS_ATIVA else None, redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ATIVA else None,
)
app.add_middleware(CabecalhosDeSeguranca)

app.include_router(notificacoes_router)


@app.get("/saude", tags=["Saúde"])
def saude(db: Session = Depends(get_db)):
    """Responde se o serviço e o seu banco estão funcionando (não exige login).

    O estado do consumidor é informativo: com o RabbitMQ fora, a API continua respondendo
    e os eventos esperam na fila (ou na caixa de saída do Chamados).
    """
    estado = consumidor.estado if consumidor is not None else "desligado"
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        log.exception("Banco de notificações indisponível")
        return JSONResponse(status_code=503, content={"status": "falha", "servico": NOME_SERVICO, "consumidor": estado})
    return {"status": "ok", "servico": NOME_SERVICO, "consumidor": estado}
