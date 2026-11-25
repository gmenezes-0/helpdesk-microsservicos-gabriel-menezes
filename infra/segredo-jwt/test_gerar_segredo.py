"""Testes do gerador do segredo JWT (rodam em Linux: dependem de uid e permissões POSIX)."""
import importlib
import os
import stat
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="permissões POSIX")


@pytest.fixture
def gerador(tmp_path, monkeypatch):
    monkeypatch.setenv("SEGREDO_PASTA", str(tmp_path))
    sys.path.insert(0, os.path.dirname(__file__))
    modulo = importlib.reload(importlib.import_module("gerar_segredo"))
    yield modulo
    os.chmod(tmp_path, 0o700)  # deixa o pytest apagar a pasta
    sys.path.pop(0)


def test_gera_segredo_forte_com_permissoes_restritas(gerador, tmp_path, capsys):
    gerador.main()
    arquivo = tmp_path / "jwt"
    segredo = arquivo.read_text()
    assert len(segredo) >= 64 and len(segredo) >= gerador.TAMANHO_MINIMO
    assert stat.S_IMODE(arquivo.stat().st_mode) == 0o400
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o500
    assert list(tmp_path.iterdir()) == [arquivo]  # nenhum temporário sobrando
    assert segredo not in capsys.readouterr().out


def test_nao_sobrescreve_segredo_existente(gerador, tmp_path):
    gerador.main()
    primeiro = (tmp_path / "jwt").read_text()
    gerador.main()
    assert (tmp_path / "jwt").read_text() == primeiro


def test_cada_geracao_e_diferente(gerador, tmp_path):
    gerador.main()
    primeiro = (tmp_path / "jwt").read_text()
    os.chmod(tmp_path, 0o700)
    (tmp_path / "jwt").unlink()
    gerador.main()
    assert (tmp_path / "jwt").read_text() != primeiro


def test_segredo_curto_existente_e_erro_e_nao_e_trocado(gerador, tmp_path, capsys):
    (tmp_path / "jwt").write_text("Xq7pZ")
    with pytest.raises(SystemExit) as saida:
        gerador.main()
    assert saida.value.code == 1
    assert (tmp_path / "jwt").read_text() == "Xq7pZ"
    assert "Xq7pZ" not in capsys.readouterr().err  # nem o valor inválido aparece


def test_link_simbolico_no_lugar_do_segredo_e_recusado(gerador, tmp_path):
    alvo = tmp_path.parent / f"{tmp_path.name}-alvo"
    alvo.write_text("x" * 64)
    (tmp_path / "jwt").symlink_to(alvo)
    with pytest.raises(SystemExit):
        gerador.main()
    alvo.unlink()


def test_pasta_ausente_e_erro(tmp_path, monkeypatch):
    monkeypatch.setenv("SEGREDO_PASTA", str(tmp_path / "nao-existe"))
    sys.path.insert(0, os.path.dirname(__file__))
    modulo = importlib.reload(importlib.import_module("gerar_segredo"))
    sys.path.pop(0)
    with pytest.raises(SystemExit):
        modulo.main()
