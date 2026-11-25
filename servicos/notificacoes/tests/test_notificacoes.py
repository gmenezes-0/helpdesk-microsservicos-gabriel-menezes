"""Testes de GET /notificacoes: formato da resposta, isolamento entre usuários e ordem."""
from app.eventos.processador import processar
from tests.conftest import evento


def test_cada_um_ve_so_os_proprios_avisos(cliente, sessao, contas):
    processar(evento("ChamadoAberto", destinatario_id=2), sessao)
    processar(evento("ChamadoAtribuido", destinatario_id=4), sessao)
    assert [a["tipo"] for a in cliente.get("/notificacoes", headers=contas["ana"]["headers"]).json()] == ["ChamadoAberto"]
    assert [a["tipo"] for a in cliente.get("/notificacoes", headers=contas["carla"]["headers"]).json()] == ["ChamadoAtribuido"]
    assert cliente.get("/notificacoes", headers=contas["bia"]["headers"]).json() == []


def test_admin_tambem_ve_so_os_proprios(cliente, sessao, contas):
    processar(evento(destinatario_id=2), sessao)
    assert cliente.get("/notificacoes", headers=contas["admin"]["headers"]).json() == []


def test_resposta_tem_os_mesmos_campos_do_monolito(cliente, sessao, contas):
    processar(evento(chamado_id=7, destinatario_id=2), sessao)
    [aviso] = cliente.get("/notificacoes", headers=contas["ana"]["headers"]).json()
    assert set(aviso) == {"id", "tipo", "destinatario_id", "mensagem", "criada_em"}
    assert aviso["mensagem"] == "Seu chamado #7 foi aberto. Prazo: 25/11 22:03." and aviso["destinatario_id"] == 2


def test_ordem_pela_data_do_fato_mesmo_chegando_fora_de_ordem(cliente, sessao, contas):
    processar(evento("ChamadoResolvido", ocorrido_em="2026-11-25T15:00:00"), sessao)  # chegou primeiro
    processar(evento("ChamadoAberto", ocorrido_em="2026-11-25T14:00:00"), sessao)
    tipos = [a["tipo"] for a in cliente.get("/notificacoes", headers=contas["ana"]["headers"]).json()]
    assert tipos == ["ChamadoAberto", "ChamadoResolvido"]


def test_sem_avisos_lista_vazia(cliente, contas):
    assert cliente.get("/notificacoes", headers=contas["ana"]["headers"]).json() == []
