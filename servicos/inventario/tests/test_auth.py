"""Testes da conferência local do token JWT (sem banco de usuários)."""
import base64
import json
import warnings
from datetime import datetime, timedelta, timezone

import jwt

from app import config
from tests.conftest import cabecalho, gerar_token


def test_rotas_exigem_login(cliente):
    for metodo, rota in [("get", "/ativos"), ("get", "/ativos/1"), ("post", "/ativos")]:
        assert getattr(cliente, metodo)(rota).status_code == 401, rota


def test_401_pede_bearer(cliente):
    assert cliente.get("/ativos").headers["www-authenticate"] == "Bearer"


def test_token_valido_do_servico_de_usuarios_e_aceito(cliente, contas):
    assert cliente.get("/ativos", headers=contas["ana"]["headers"]).status_code == 200


def test_esquema_diferente_de_bearer_e_recusado(cliente):
    token = gerar_token(2, "solicitante")
    assert cliente.get("/ativos", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_token_adulterado(cliente, contas):
    token = contas["ana"]["headers"]["Authorization"] + "x"
    assert cliente.get("/ativos", headers={"Authorization": token}).status_code == 401


def test_trocar_o_perfil_no_token_invalida_a_assinatura(cliente):
    """O perfil vem das claims assinadas: o cliente não consegue se promover a técnico."""
    cabeca, conteudo, assinatura = gerar_token(2, "solicitante").split(".")
    dados = json.loads(base64.urlsafe_b64decode(conteudo + "=" * (-len(conteudo) % 4)))
    dados["perfil"] = "tecnico"
    novo = base64.urlsafe_b64encode(json.dumps(dados).encode()).rstrip(b"=").decode()
    r = cliente.post("/ativos", headers=cabecalho(f"{cabeca}.{novo}.{assinatura}"),
                     json={"patrimonio": "PAT-9", "tipo": "outro", "descricao": "X1", "setor": "TI"})
    assert r.status_code == 401


def test_token_assinado_com_outro_segredo(cliente):
    falso = gerar_token(1, "admin", segredo="segredo-de-outra-pessoa-com-mais-de-32-caracteres")
    assert cliente.get("/ativos", headers=cabecalho(falso)).status_code == 401


def test_token_sem_assinatura_alg_none(cliente):
    agora = datetime.now(timezone.utc)
    falso = jwt.encode({"sub": "1", "perfil": "admin", "iss": config.JWT_EMISSOR, "iat": agora,
                        "exp": agora + timedelta(hours=1)}, None, algorithm="none")
    assert cliente.get("/ativos", headers=cabecalho(falso)).status_code == 401


def test_token_com_outro_algoritmo_e_recusado(cliente):
    agora = datetime.now(timezone.utc)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # PyJWT avisa que a chave é curta para HS512; aqui isso não importa
        outro = jwt.encode({"sub": "1", "perfil": "admin", "iss": config.JWT_EMISSOR, "iat": agora,
                            "exp": agora + timedelta(hours=1)}, config.JWT_SEGREDO, algorithm="HS512")
    assert cliente.get("/ativos", headers=cabecalho(outro)).status_code == 401


def test_token_de_outro_emissor(cliente):
    assert cliente.get("/ativos", headers=cabecalho(gerar_token(1, "admin", iss="outro-sistema"))).status_code == 401


def test_token_expirado(cliente):
    antigo = datetime.now(timezone.utc) - timedelta(hours=2)
    vencido = gerar_token(2, "solicitante", iat=antigo, exp=antigo + timedelta(minutes=5))
    assert cliente.get("/ativos", headers=cabecalho(vencido)).status_code == 401


def test_token_sem_claims_obrigatorias(cliente):
    for claim in ("perfil", "sub", "exp", "iat", "iss"):
        sem = gerar_token(2, "solicitante", sem=(claim,))
        assert cliente.get("/ativos", headers=cabecalho(sem)).status_code == 401, claim


def test_token_com_perfil_desconhecido(cliente):
    for perfil in ("root", "", "ADMIN"):
        assert cliente.get("/ativos", headers=cabecalho(gerar_token(1, perfil))).status_code == 401, perfil


def test_token_com_perfil_que_nao_e_texto(cliente):
    assert cliente.get("/ativos", headers=cabecalho(gerar_token(1, ["admin"]))).status_code == 401


def test_token_com_id_invalido(cliente):
    for sub in ("abc", "0", "-3"):
        assert cliente.get("/ativos", headers=cabecalho(gerar_token(sub, "admin"))).status_code == 401, sub
