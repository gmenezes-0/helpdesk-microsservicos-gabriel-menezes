"""Testes das rotas e regras de inventário."""


def test_tecnico_cadastra_ativo_e_filtra_por_setor(cliente, contas):
    h = contas["carla"]["headers"]
    r = cliente.post("/ativos", headers=h, json={"patrimonio": "PAT-1", "tipo": "impressora", "descricao": "HP", "setor": "RH"})
    assert r.status_code == 201
    assert r.json() == {"id": 1, "patrimonio": "PAT-1", "tipo": "impressora", "descricao": "HP", "setor": "RH"}
    cliente.post("/ativos", headers=h, json={"patrimonio": "PAT-2", "tipo": "computador", "descricao": "Dell", "setor": "TI"})
    assert len(cliente.get("/ativos", params={"setor": "RH"}, headers=h).json()) == 1
    assert [a["patrimonio"] for a in cliente.get("/ativos", headers=h).json()] == ["PAT-1", "PAT-2"]


def test_admin_cadastra_ativo(cliente, contas):
    r = cliente.post("/ativos", headers=contas["admin"]["headers"],
                     json={"patrimonio": "PAT-7", "tipo": "rede", "descricao": "Switch", "setor": "TI"})
    assert r.status_code == 201


def test_solicitante_nao_cadastra_ativo(cliente, contas):
    r = cliente.post("/ativos", headers=contas["ana"]["headers"],
                     json={"patrimonio": "PAT-9", "tipo": "outro", "descricao": "X", "setor": "TI"})
    assert r.status_code == 403


def test_solicitante_lista_e_consulta_ativos(cliente, contas, ativo):
    h = contas["ana"]["headers"]
    assert [a["id"] for a in cliente.get("/ativos", headers=h).json()] == [ativo["id"]]
    assert cliente.get(f"/ativos/{ativo['id']}", headers=h).json() == ativo


def test_ativo_inexistente(cliente, contas):
    # rota usada pelo serviço de Chamados para conferir o equipamento
    r = cliente.get("/ativos/999", headers=contas["ana"]["headers"])
    assert r.status_code == 404 and r.json()["detail"] == "Ativo 999 não encontrado."


def test_patrimonio_repetido_e_recusado(cliente, contas, ativo):
    r = cliente.post("/ativos", headers=contas["carla"]["headers"],
                     json={"patrimonio": "PAT-1", "tipo": "notebook", "descricao": "Outro", "setor": "RH"})
    assert r.status_code == 422 and r.json()["detail"] == "Já existe um ativo com este patrimônio."


def test_filtro_por_setor_sem_resultado(cliente, contas, ativo):
    assert cliente.get("/ativos", params={"setor": "Jurídico"}, headers=contas["ana"]["headers"]).json() == []


def test_dados_exemplo_criam_os_mesmos_ativos_do_monolito(sessao):
    from app import dados_exemplo
    from app.inventario import servico
    with sessao() as db:
        dados_exemplo.carregar(db)
        dados_exemplo.carregar(db)  # na segunda vez, com o banco cheio, não cria de novo
        lista = [(a.id, a.patrimonio, a.setor) for a in servico.listar(db)]
    assert lista == [(1, "PAT-0001", "Financeiro"), (2, "PAT-0002", "RH"), (3, "PAT-0003", "TI")]
