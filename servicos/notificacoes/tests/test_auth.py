"""Testes da conferência local do token JWT (mesmas regras do Inventário e do Chamados)."""
import base64
import json
import warnings
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app import config
from tests.conftest import cabecalho, gerar_token


def test_rota_exige_login(cliente):
    r = cliente.get("/notificacoes")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_token_valido_e_aceito(cliente, contas):
    assert cliente.get("/notificacoes", headers=contas["ana"]["headers"]).status_code == 200


def test_esquema_diferente_de_bearer(cliente):
    assert cliente.get("/notificacoes", headers={"Authorization": f"Basic {gerar_token(2, 'solicitante')}"}).status_code == 401


def test_token_adulterado(cliente, contas):
    assert cliente.get("/notificacoes", headers={"Authorization": contas["ana"]["headers"]["Authorization"] + "x"}).status_code == 401


def test_trocar_o_usuario_no_token_invalida_a_assinatura(cliente):
    """O id vem das claims assinadas: não dá para ler os avisos de outra pessoa trocando o sub."""
    cabeca, conteudo, assinatura = gerar_token(2, "solicitante").split(".")
    dados = json.loads(base64.urlsafe_b64decode(conteudo + "=" * (-len(conteudo) % 4)))
    dados["sub"] = "4"
    novo = base64.urlsafe_b64encode(json.dumps(dados).encode()).rstrip(b"=").decode()
    assert cliente.get("/notificacoes", headers=cabecalho(f"{cabeca}.{novo}.{assinatura}")).status_code == 401


def test_token_assinado_com_outro_segredo(cliente):
    falso = gerar_token(1, "admin", segredo="segredo-de-outra-pessoa-com-mais-de-32-caracteres")
    assert cliente.get("/notificacoes", headers=cabecalho(falso)).status_code == 401


def test_token_sem_assinatura_alg_none(cliente):
    agora = datetime.now(timezone.utc)
    falso = jwt.encode({"sub": "2", "perfil": "solicitante", "iss": config.JWT_EMISSOR, "iat": agora,
                        "exp": agora + timedelta(hours=1)}, None, algorithm="none")
    assert cliente.get("/notificacoes", headers=cabecalho(falso)).status_code == 401


def test_token_com_outro_algoritmo(cliente):
    agora = datetime.now(timezone.utc)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        outro = jwt.encode({"sub": "2", "perfil": "solicitante", "iss": config.JWT_EMISSOR, "iat": agora,
                            "exp": agora + timedelta(hours=1)}, config.JWT_SEGREDO, algorithm="HS512")
    assert cliente.get("/notificacoes", headers=cabecalho(outro)).status_code == 401


def test_token_de_outro_emissor(cliente):
    assert cliente.get("/notificacoes", headers=cabecalho(gerar_token(2, "solicitante", iss="outro"))).status_code == 401


def test_token_expirado(cliente):
    antigo = datetime.now(timezone.utc) - timedelta(hours=2)
    vencido = gerar_token(2, "solicitante", iat=antigo, exp=antigo + timedelta(minutes=5))
    assert cliente.get("/notificacoes", headers=cabecalho(vencido)).status_code == 401


@pytest.mark.parametrize("claim", ["perfil", "sub", "exp", "iat", "iss"])
def test_token_sem_claim_obrigatoria(cliente, claim):
    assert cliente.get("/notificacoes", headers=cabecalho(gerar_token(2, "solicitante", sem=(claim,)))).status_code == 401


@pytest.mark.parametrize("perfil", ["root", "", None, ["admin"]])
def test_perfil_desconhecido(cliente, perfil):
    assert cliente.get("/notificacoes", headers=cabecalho(gerar_token(2, perfil))).status_code == 401


@pytest.mark.parametrize("sub", ["0", "-1", "abc", ""])
def test_usuario_invalido_no_token(cliente, sub):
    assert cliente.get("/notificacoes", headers=cabecalho(gerar_token(2, "solicitante", sub=sub))).status_code == 401
