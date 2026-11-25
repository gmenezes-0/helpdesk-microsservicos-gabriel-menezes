"""Testes da tela do HelpDesk servida pelo gateway e da documentação unificada."""
from pathlib import Path

WEB = Path(__file__).parent.parent / "app" / "web"


# ---------- tela ----------

def test_tela_e_servida_sem_mudancas(cliente, servicos):
    r = cliente.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.content == (WEB / "index.html").read_bytes()
    assert servicos.pedidos == []  # a tela não depende dos serviços


def test_script_e_estilo(cliente):
    js = cliente.get("/app.js")
    assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
    assert js.content == (WEB / "app.js").read_bytes()
    css = cliente.get("/estilo.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")


def test_tela_continua_chamando_a_api_pelo_mesmo_endereco():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'const API = "";' in js  # endereço relativo: tudo passa pelo gateway


def test_tela_escapa_o_html():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "const esc =" in js and "onclick" not in js


# ---------- documentação ----------

def test_docs_abre_o_swagger(cliente):
    r = cliente.get("/docs")
    assert r.status_code == 200 and "swagger-ui" in r.text and "/openapi.json" in r.text


def test_openapi_junta_as_rotas_dos_tres_servicos(cliente):
    doc = cliente.get("/openapi.json").json()
    assert set(doc["paths"]) == {"/saude", "/auth/login", "/auth/eu", "/usuarios", "/usuarios/{usuario_id}",
                                 "/ativos", "/ativos/{ativo_id}", "/chamados", "/chamados/painel", "/notificacoes"}
    assert set(doc["paths"]["/usuarios"]) == {"get", "post"}
    esquemas = doc["components"]["schemas"]
    assert {"UsuarioSaida", "AtivoSaida", "ChamadoSaida", "HTTPValidationError"} <= set(esquemas)
    assert doc["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_openapi_mostra_a_saude_do_gateway_e_nao_a_dos_servicos(cliente):
    saude = cliente.get("/openapi.json").json()["paths"]["/saude"]
    assert "Mostra quais serviços estão no ar" in saude["get"]["description"]


def test_openapi_sem_um_servico_lista_os_outros(cliente, servicos):
    servicos.falha["inventario.teste"] = "conexao"
    doc = cliente.get("/openapi.json").json()
    assert "/ativos" not in doc["paths"] and "/chamados" in doc["paths"] and "/auth/login" in doc["paths"]
    assert "inventario" in doc["info"]["description"]


def test_openapi_inclui_o_servico_de_notificacoes(cliente, servicos):
    doc = cliente.get("/openapi.json").json()
    assert "/notificacoes" in doc["paths"] and "NotificacaoSaida" in doc["components"]["schemas"]
    servicos.falha["notificacoes.teste"] = "conexao"
    doc = cliente.get("/openapi.json").json()
    assert "/notificacoes" not in doc["paths"] and "/chamados" in doc["paths"]
