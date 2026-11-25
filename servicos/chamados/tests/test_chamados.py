"""Testes das regras de chamados (os mesmos do monólito, com Usuários e Inventário simulados)."""
from datetime import datetime


def abrir(cliente, contas, ativo, quem="ana", prioridade="alta", **extra):
    dados = {"titulo": "PC não liga", "descricao": "Nada acontece", "prioridade": prioridade, "ativo_id": ativo["id"], **extra}
    return cliente.post("/chamados", headers=contas[quem]["headers"], json=dados)


def test_abrir_calcula_sla_e_notifica(cliente, contas, ativo):
    r = abrir(cliente, contas, ativo, prioridade="critica")
    assert r.status_code == 201
    c = r.json()
    assert c["solicitante_id"] == contas["ana"]["id"]
    horas = (datetime.fromisoformat(c["prazo_sla"]) - datetime.fromisoformat(c["criado_em"])).total_seconds() / 3600
    assert round(horas) == 4
    avisos = cliente.get("/notificacoes", headers=contas["ana"]["headers"]).json()
    assert avisos[0]["tipo"] == "ChamadoAberto"


def test_sla_de_cada_prioridade(cliente, contas, ativo):
    for prioridade, horas in {"critica": 4, "alta": 8, "media": 24, "baixa": 72}.items():
        c = abrir(cliente, contas, ativo, prioridade=prioridade).json()
        diferenca = datetime.fromisoformat(c["prazo_sla"]) - datetime.fromisoformat(c["criado_em"])
        assert round(diferenca.total_seconds() / 3600) == horas, prioridade


def test_abrir_sem_equipamento(cliente, contas, rede):
    r = cliente.post("/chamados", headers=contas["ana"]["headers"],
                     json={"titulo": "Sem acesso", "descricao": "Não navega", "prioridade": "baixa"})
    assert r.status_code == 201 and r.json()["ativo_id"] is None
    assert rede.pedidos_para("inventario.teste") == []  # sem equipamento, nem consulta o Inventário


def test_abrir_com_ativo_inexistente(cliente, contas, ativo):
    r = abrir(cliente, contas, ativo, ativo_id=999)
    assert r.status_code == 404 and r.json()["detail"] == "Ativo 999 não encontrado."
    assert cliente.get("/chamados", headers=contas["carla"]["headers"]).json() == []  # nada foi gravado


def test_atribuir_muda_status_e_avisa_tecnico(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    r = cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["carla"]["headers"], json={"tecnico_id": contas["carla"]["id"]})
    assert r.json()["status"] == "em_atendimento" and r.json()["tecnico_id"] == contas["carla"]["id"]
    avisos = cliente.get("/notificacoes", headers=contas["carla"]["headers"]).json()
    assert avisos[0]["tipo"] == "ChamadoAtribuido"


def test_so_tecnico_pode_ser_atribuido(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    r = cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["carla"]["headers"], json={"tecnico_id": contas["ana"]["id"]})
    assert r.status_code == 422 and r.json()["detail"] == f"Usuário {contas['ana']['id']} não é técnico."


def test_atribuir_a_tecnico_inexistente(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    r = cliente.patch(f"/chamados/{cid}/atribuir", headers=contas["carla"]["headers"], json={"tecnico_id": 99})
    assert r.status_code == 404 and r.json()["detail"] == "Usuário 99 não encontrado."


def test_nao_atribui_chamado_resolvido(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": contas["carla"]["id"]})
    cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"})
    r = cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": contas["carla"]["id"]})
    assert r.status_code == 422


def test_fluxo_completo_de_status(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": contas["carla"]["id"]})
    assert cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"}).status_code == 200
    avisos = cliente.get("/notificacoes", headers=contas["ana"]["headers"]).json()
    assert avisos[-1]["tipo"] == "ChamadoResolvido"
    # o próprio solicitante confirma e fecha
    r = cliente.patch(f"/chamados/{cid}/status", headers=contas["ana"]["headers"], json={"status": "fechado"})
    assert r.json()["status"] == "fechado"


def test_solicitante_reabre_chamado_resolvido(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": contas["carla"]["id"]})
    cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"})
    r = cliente.patch(f"/chamados/{cid}/status", headers=contas["ana"]["headers"], json={"status": "em_atendimento"})
    assert r.status_code == 200 and r.json()["status"] == "em_atendimento"


def test_chamado_fechado_nao_muda_mais(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": contas["carla"]["id"]})
    cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"})
    cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "fechado"})
    for status in ("aberto", "em_atendimento", "resolvido"):
        assert cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": status}).status_code == 422


def test_transicao_invalida(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    r = cliente.patch(f"/chamados/{cid}/status", headers=contas["carla"]["headers"], json={"status": "fechado"})
    assert r.status_code == 422


def test_iniciar_atendimento_sem_tecnico(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    r = cliente.patch(f"/chamados/{cid}/status", headers=contas["carla"]["headers"], json={"status": "em_atendimento"})
    assert r.status_code == 422


def test_comentar_usa_o_usuario_logado(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    r = cliente.post(f"/chamados/{cid}/comentarios", headers=contas["carla"]["headers"], json={"texto": "Verificando a fonte."})
    assert r.status_code == 201 and r.json()["autor_id"] == contas["carla"]["id"]
    assert len(cliente.get(f"/chamados/{cid}", headers=contas["ana"]["headers"]).json()["comentarios"]) == 1


def test_solicitante_comenta_no_proprio_chamado(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    r = cliente.post(f"/chamados/{cid}/comentarios", headers=contas["ana"]["headers"], json={"texto": "Obrigada!"})
    assert r.status_code == 201


def test_chamado_fechado_nao_recebe_comentario(cliente, contas, ativo):
    cid = abrir(cliente, contas, ativo).json()["id"]
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{cid}/atribuir", headers=tec, json={"tecnico_id": contas["carla"]["id"]})
    cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "resolvido"})
    cliente.patch(f"/chamados/{cid}/status", headers=tec, json={"status": "fechado"})
    assert cliente.post(f"/chamados/{cid}/comentarios", headers=tec, json={"texto": "oi"}).status_code == 422


def test_painel(cliente, contas, ativo):
    abrir(cliente, contas, ativo)
    abrir(cliente, contas, ativo, prioridade="baixa")
    p = cliente.get("/chamados/painel", headers=contas["carla"]["headers"]).json()
    assert p["total"] == 2 and p["por_status"] == {"aberto": 2} and p["atrasados"] == 0


def test_painel_do_solicitante_conta_so_os_seus(cliente, contas, ativo):
    abrir(cliente, contas, ativo, quem="ana")
    abrir(cliente, contas, ativo, quem="bia")
    assert cliente.get("/chamados/painel", headers=contas["bia"]["headers"]).json()["total"] == 1


def test_filtros_da_lista(cliente, contas, ativo):
    c1 = abrir(cliente, contas, ativo).json()["id"]
    abrir(cliente, contas, ativo)
    tec = contas["carla"]["headers"]
    cliente.patch(f"/chamados/{c1}/atribuir", headers=tec, json={"tecnico_id": contas["carla"]["id"]})
    assert [c["id"] for c in cliente.get("/chamados", params={"status": "em_atendimento"}, headers=tec).json()] == [c1]
    assert [c["id"] for c in cliente.get("/chamados", params={"tecnico_id": 4}, headers=tec).json()] == [c1]


def test_dados_exemplo_criam_os_mesmos_chamados_do_monolito(sessao, rede):
    from app import dados_exemplo
    from app.chamados import repositorio
    from app.notificacoes import servico as notificacoes
    with sessao() as db:
        dados_exemplo.carregar(db)
        dados_exemplo.carregar(db)  # na segunda vez, com o banco cheio, não cria de novo
        lista = [(c.id, c.solicitante_id, c.ativo_id, c.status, c.tecnico_id) for c in repositorio.listar(db)]
        avisos = [(n.tipo, n.destinatario_id) for n in notificacoes.listar(db)]
    assert lista == [(1, 2, 1, "em_atendimento", 4), (2, 3, 2, "aberto", None), (3, 3, None, "aberto", None)]
    assert avisos == [("ChamadoAberto", 2), ("ChamadoAberto", 3), ("ChamadoAberto", 3), ("ChamadoAtribuido", 4)]
    assert rede.pedidos == []  # ao iniciar, nenhuma chamada HTTP
