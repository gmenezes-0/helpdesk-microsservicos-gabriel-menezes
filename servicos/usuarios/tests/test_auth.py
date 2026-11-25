"""Testes de autenticação: login, tokens JWT e bloqueio de tentativas."""
from datetime import datetime, timedelta, timezone

import jwt

from app import config
from tests.conftest import SENHA


def test_login_devolve_token_com_perfil(cliente, contas):
    r = cliente.post("/auth/login", json={"email": "carla@x.com", "senha": SENHA})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["token_type"] == "bearer" and corpo["usuario"]["perfil"] == "tecnico"
    dados = jwt.decode(corpo["access_token"], config.JWT_SEGREDO, algorithms=["HS256"], issuer=config.JWT_EMISSOR)
    # os outros serviços conferem o token sem acessar este banco: precisam do id e do perfil
    assert dados["sub"] == str(contas["carla"]["id"]) and dados["perfil"] == "tecnico"


def test_login_ignora_maiusculas_no_email(cliente, contas):
    assert cliente.post("/auth/login", json={"email": "ANA@X.com", "senha": SENHA}).status_code == 200


def test_eu_devolve_quem_esta_logado(cliente, contas):
    r = cliente.get("/auth/eu", headers=contas["ana"]["headers"])
    assert r.status_code == 200
    assert r.json() == {"id": contas["ana"]["id"], "nome": "Ana", "email": "ana@x.com", "perfil": "solicitante"}


def test_rotas_exigem_login(cliente, contas):
    for metodo, rota in [("get", "/usuarios"), ("get", "/usuarios/1"), ("post", "/usuarios"), ("get", "/auth/eu")]:
        assert getattr(cliente, metodo)(rota).status_code == 401, rota


def test_esquema_diferente_de_bearer_e_recusado(cliente, contas):
    token = contas["ana"]["headers"]["Authorization"].split()[1]
    assert cliente.get("/auth/eu", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_login_com_senha_errada(cliente, contas):
    r = cliente.post("/auth/login", json={"email": "ana@x.com", "senha": "errada123"})
    assert r.status_code == 401 and r.json()["detail"] == "E-mail ou senha inválidos."


def test_login_com_email_inexistente_tem_a_mesma_mensagem(cliente, contas):
    r = cliente.post("/auth/login", json={"email": "ninguem@x.com", "senha": "errada123"})
    assert r.status_code == 401 and r.json()["detail"] == "E-mail ou senha inválidos."


def test_bloqueio_apos_varias_senhas_erradas(cliente, contas):
    for _ in range(config.LOGIN_MAX_FALHAS):
        cliente.post("/auth/login", json={"email": "ana@x.com", "senha": "errada123"})
    # mesmo com a senha certa, fica bloqueado por um tempo
    assert cliente.post("/auth/login", json={"email": "ana@x.com", "senha": SENHA}).status_code == 429
    # o bloqueio é por e-mail: outra conta continua entrando
    assert cliente.post("/auth/login", json={"email": "bia@x.com", "senha": SENHA}).status_code == 200


def test_usuario_inativo_nao_entra_e_perde_o_acesso(cliente, contas, sessao):
    from app.usuarios.modelos import Usuario
    with sessao() as db:
        u = db.get(Usuario, contas["ana"]["id"])
        u.ativo = False
        db.commit()
    assert cliente.post("/auth/login", json={"email": "ana@x.com", "senha": SENHA}).status_code == 401
    assert cliente.get("/auth/eu", headers=contas["ana"]["headers"]).status_code == 401


def test_token_adulterado(cliente, contas):
    token = contas["ana"]["headers"]["Authorization"] + "x"
    assert cliente.get("/auth/eu", headers={"Authorization": token}).status_code == 401


def test_token_assinado_com_outro_segredo(cliente, contas):
    falso = jwt.encode({"sub": str(contas["admin"]["id"]), "iss": config.JWT_EMISSOR,
                        "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                       "segredo-de-outra-pessoa-com-mais-de-32-caracteres", algorithm="HS256")
    assert cliente.get("/auth/eu", headers={"Authorization": f"Bearer {falso}"}).status_code == 401


def test_token_sem_assinatura_alg_none(cliente, contas):
    falso = jwt.encode({"sub": str(contas["admin"]["id"]), "iss": config.JWT_EMISSOR,
                        "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                       None, algorithm="none")
    assert cliente.get("/auth/eu", headers={"Authorization": f"Bearer {falso}"}).status_code == 401


def test_token_de_outro_emissor(cliente, contas):
    agora = datetime.now(timezone.utc)
    falso = jwt.encode({"sub": str(contas["admin"]["id"]), "iss": "outro-sistema", "iat": agora,
                        "exp": agora + timedelta(hours=1)}, config.JWT_SEGREDO, algorithm="HS256")
    assert cliente.get("/auth/eu", headers={"Authorization": f"Bearer {falso}"}).status_code == 401


def test_token_expirado(cliente, contas):
    antigo = datetime.now(timezone.utc) - timedelta(hours=2)
    vencido = jwt.encode({"sub": str(contas["ana"]["id"]), "iss": config.JWT_EMISSOR, "iat": antigo,
                          "exp": antigo + timedelta(minutes=5)}, config.JWT_SEGREDO, algorithm="HS256")
    assert cliente.get("/auth/eu", headers={"Authorization": f"Bearer {vencido}"}).status_code == 401
