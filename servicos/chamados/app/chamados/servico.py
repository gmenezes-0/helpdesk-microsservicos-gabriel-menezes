"""Regras do serviço de chamados.

No monólito, o técnico e o equipamento eram conferidos com chamadas de função
para `usuarios.servico` e `inventario.servico`. Aqui são chamadas HTTP aos
serviços de Usuários e Inventário (veja `app/clientes.py`), repassando o token
de quem fez o pedido. As notificações viraram eventos (ChamadoAberto,
ChamadoAtribuido, ChamadoResolvido): cada um é gravado na caixa de saída, na mesma
transação do chamado, e publicado depois no RabbitMQ (veja `app/eventos/`).
O serviço de Notificações consome esses eventos e grava os avisos no banco dele.

Permissões:
- solicitante: abre chamados e só vê, comenta e fecha os próprios;
- técnico e admin: veem todos, atribuem e mudam o status.
"""
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import clientes
from app.auth.tokens import UsuarioToken
from app.chamados import repositorio
from app.chamados.esquemas import ChamadoCriar, ComentarioCriar
from app.chamados.modelos import Chamado, Comentario
from app.erros import NaoEncontrado, RegraDeNegocio, SemPermissao
from app.eventos import servico as eventos

# Prazo para resolver o chamado, conforme a prioridade (SLA)
HORAS_SLA = {"critica": 4, "alta": 8, "media": 24, "baixa": 72}

# De qual status para quais status um chamado pode ir
TRANSICOES = {
    "aberto": {"em_atendimento"},
    "em_atendimento": {"resolvido"},
    "resolvido": {"fechado", "em_atendimento"},  # reabrir se o problema voltar
    "fechado": set(),
}

EQUIPE = ("tecnico", "admin")


def eh_equipe(usuario: UsuarioToken) -> bool:
    return usuario.perfil in EQUIPE


def calcular_prazo(prioridade: str, inicio: datetime) -> datetime:
    return inicio + timedelta(hours=HORAS_SLA[prioridade])


def abrir(db: Session, dados: ChamadoCriar, usuario: UsuarioToken) -> Chamado:
    if dados.ativo_id is not None:
        clientes.obter_ativo(dados.ativo_id, usuario.autorizacao)    # chamada HTTP ao Inventário
    return registrar_abertura(db, dados, usuario.id)


def registrar_abertura(db: Session, dados: ChamadoCriar, solicitante_id: int) -> Chamado:
    """Grava o chamado já conferido e avisa o solicitante."""
    agora = datetime.now()
    chamado = Chamado(
        **dados.model_dump(), solicitante_id=solicitante_id, status="aberto", criado_em=agora,
        prazo_sla=calcular_prazo(dados.prioridade, agora),
    )
    db.add(chamado)
    db.flush()  # gera o id do chamado, ainda dentro da transação
    eventos.registrar(db, "ChamadoAberto", {
        "chamado_id": chamado.id, "destinatario_id": solicitante_id, "prazo_sla": chamado.prazo_sla.isoformat()})
    return repositorio.salvar(db, chamado)  # um único commit: chamado + evento


def obter(db: Session, chamado_id: int, usuario: UsuarioToken) -> Chamado:
    chamado = repositorio.buscar_por_id(db, chamado_id)
    # Para quem não pode ver, responde "não encontrado": não revela que o chamado existe
    if chamado is None or not (eh_equipe(usuario) or chamado.solicitante_id == usuario.id):
        raise NaoEncontrado(f"Chamado {chamado_id} não encontrado.")
    return chamado


def listar(db: Session, usuario: UsuarioToken, status: str | None = None, tecnico_id: int | None = None) -> list[Chamado]:
    solicitante_id = None if eh_equipe(usuario) else usuario.id
    return repositorio.listar(db, status, tecnico_id, solicitante_id)


def atribuir(db: Session, chamado_id: int, tecnico_id: int, usuario: UsuarioToken) -> Chamado:
    if not eh_equipe(usuario):
        raise SemPermissao("Só técnicos e administradores atribuem chamados.")
    chamado = obter(db, chamado_id, usuario)
    if chamado.status in ("resolvido", "fechado"):
        raise RegraDeNegocio("Não é possível atribuir um chamado resolvido ou fechado.")
    tecnico = clientes.obter_tecnico(tecnico_id, usuario.autorizacao)  # chamada HTTP a Usuários
    return registrar_atribuicao(db, chamado, tecnico["id"])


def registrar_atribuicao(db: Session, chamado: Chamado, tecnico_id: int) -> Chamado:
    """Grava a atribuição a um técnico já conferido e avisa o técnico."""
    chamado.tecnico_id = tecnico_id
    if chamado.status == "aberto":
        chamado.status = "em_atendimento"
    eventos.registrar(db, "ChamadoAtribuido", {"chamado_id": chamado.id, "destinatario_id": tecnico_id})
    return repositorio.salvar(db, chamado)  # um único commit: atribuição + evento


def mudar_status(db: Session, chamado_id: int, novo_status: str, usuario: UsuarioToken) -> Chamado:
    chamado = obter(db, chamado_id, usuario)
    # O solicitante só pode confirmar (fechar) ou reabrir o próprio chamado resolvido
    pode_solicitante = chamado.status == "resolvido" and novo_status in ("fechado", "em_atendimento")
    if not (eh_equipe(usuario) or pode_solicitante):
        raise SemPermissao("Você não pode mudar o status deste chamado.")
    if novo_status not in TRANSICOES[chamado.status]:
        raise RegraDeNegocio(f"Não é possível ir de '{chamado.status}' para '{novo_status}'.")
    if novo_status == "em_atendimento" and chamado.tecnico_id is None:
        raise RegraDeNegocio("Atribua um técnico antes de iniciar o atendimento.")
    chamado.status = novo_status
    if novo_status == "resolvido":
        eventos.registrar(db, "ChamadoResolvido", {"chamado_id": chamado.id, "destinatario_id": chamado.solicitante_id})
    return repositorio.salvar(db, chamado)  # um único commit: status + evento


def comentar(db: Session, chamado_id: int, dados: ComentarioCriar, usuario: UsuarioToken) -> Comentario:
    chamado = obter(db, chamado_id, usuario)
    if chamado.status == "fechado":
        raise RegraDeNegocio("Chamados fechados não recebem comentários.")
    return repositorio.salvar_comentario(db, Comentario(
        chamado_id=chamado.id, autor_id=usuario.id, texto=dados.texto, criado_em=datetime.now()
    ))


def painel(db: Session, usuario: UsuarioToken) -> dict:
    chamados = listar(db, usuario)
    agora = datetime.now()
    atrasados = sum(1 for c in chamados if c.status in ("aberto", "em_atendimento") and c.prazo_sla < agora)
    return {"total": len(chamados), "por_status": dict(Counter(c.status for c in chamados)), "atrasados": atrasados}
