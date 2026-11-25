"""Testes das rotas de usuários e dos dados de exemplo."""


def test_admin_cria_usuario(cliente, contas):
    r = cliente.post("/usuarios", headers=contas["admin"]["headers"],
                     json={"nome": "Davi", "email": "davi@x.com", "perfil": "tecnico", "senha": "Forte1234"})
    assert r.status_code == 201
    assert "senha" not in r.json() and "senha_hash" not in r.json()


def test_email_repetido_e_recusado(cliente, contas):
    dados = {"nome": "Ana 2", "email": "ANA@x.com", "perfil": "solicitante", "senha": "Forte1234"}
    assert cliente.post("/usuarios", headers=contas["admin"]["headers"], json=dados).status_code == 422


def test_usuario_inexistente(cliente, contas):
    assert cliente.get("/usuarios/99", headers=contas["ana"]["headers"]).status_code == 404


def test_obter_usuario_mostra_perfil_sem_email(cliente, contas):
    # rota usada pelo serviço de Chamados para conferir se a pessoa é técnica
    r = cliente.get(f"/usuarios/{contas['carla']['id']}", headers=contas["ana"]["headers"])
    assert r.status_code == 200
    assert r.json() == {"id": contas["carla"]["id"], "nome": "Carla", "perfil": "tecnico"}


def test_lista_publica_nao_mostra_email(cliente, contas):
    lista = cliente.get("/usuarios", headers=contas["ana"]["headers"]).json()
    assert lista and all("email" not in u for u in lista)


def test_lista_filtra_por_perfil(cliente, contas):
    lista = cliente.get("/usuarios", params={"perfil": "tecnico"}, headers=contas["ana"]["headers"]).json()
    assert [u["nome"] for u in lista] == ["Carla"]


def test_dados_exemplo_criam_os_mesmos_usuarios_do_monolito(sessao):
    from app import dados_exemplo
    from app.usuarios import servico
    with sessao() as db:
        dados_exemplo.carregar(db)
        dados_exemplo.carregar(db)  # na segunda vez, com o banco cheio, não cria de novo
        lista = [(u.id, u.email, u.perfil) for u in servico.listar(db)]
    assert lista == [(1, "admin@empresa.com", "admin"), (2, "ana@empresa.com", "solicitante"),
                     (3, "bruno@empresa.com", "solicitante"), (4, "carla@empresa.com", "tecnico"),
                     (5, "diego@empresa.com", "tecnico")]
