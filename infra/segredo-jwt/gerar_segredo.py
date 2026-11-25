"""Gera o segredo que assina os tokens JWT, uma única vez, no volume compartilhado.

- 48 bytes aleatórios de `secrets` (gerador criptograficamente seguro), em base64 url-safe.
- Nunca sobrescreve: se o arquivo já existe, só confere se é válido e mantém.
  A criação é atômica (arquivo temporário + os.link, que falha se o destino existir),
  então um segredo pela metade nunca fica visível para os serviços.
- Permissões: arquivo 0400 e pasta 0500, ambos do usuário 10001 (o mesmo dos serviços,
  que montam o volume só para leitura).
- O valor do segredo nunca é impresso.

Credenciais do RabbitMQ (só quando MQ_SEGREDOS_PASTA está definida), num volume à parte:
- uma senha aleatória e distinta para cada cliente (chamados, notificacoes), cada uma na
  sua subpasta, para que cada serviço monte só a própria (volume com subpath);
- rabbitmq/definicoes.json: usuários (só com hash da senha, nunca o texto), vhost,
  permissões mínimas, exchange, filas, ligações e fila de mensagens mortas;
- nunca sobrescreve: se tudo já existe, confere a consistência e mantém; se só uma parte
  existe, para com erro (decisão de quem opera, como no segredo JWT).
"""
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
from pathlib import Path

PASTA = Path(os.getenv("SEGREDO_PASTA", "/segredos"))
ARQUIVO = PASTA / "jwt"
BYTES_ALEATORIOS = 48     # 384 bits; vira um texto de 64 caracteres
TAMANHO_MINIMO = 32       # o mesmo mínimo que os serviços exigem

MQ_PASTA = Path(os.environ["MQ_SEGREDOS_PASTA"]) if os.getenv("MQ_SEGREDOS_PASTA") else None
MQ_BYTES_SENHA = 32       # 256 bits; vira um texto de 43 caracteres
MQ_VHOST = "helpdesk"
EXCHANGE_EVENTOS = "helpdesk.eventos"
EXCHANGE_MORTAS = "helpdesk.eventos.dlx"
FILA_EVENTOS = "notificacoes.eventos"
FILA_MORTAS = "notificacoes.eventos.dlq"
LIMITE_ENTREGAS = 5       # depois disso, a mensagem vai para a fila de mensagens mortas

# Permissões mínimas (configure, write, read): Chamados só publica na exchange de eventos;
# Notificações só lê a própria fila. Ninguém declara, apaga ou liga filas e exchanges.
CLIENTES_MQ = {
    "chamados": ("^$", f"^{re.escape(EXCHANGE_EVENTOS)}$", "^$"),
    "notificacoes": ("^$", "^$", f"^{re.escape(FILA_EVENTOS)}$"),
}


def falhar(mensagem: str) -> None:
    print(f"[segredo-jwt] ERRO: {mensagem}", file=sys.stderr)
    sys.exit(1)


def conferir_existente() -> None:
    info = ARQUIVO.lstat()
    if not stat.S_ISREG(info.st_mode):
        falhar(f"{ARQUIVO} existe, mas não é um arquivo comum.")
    if info.st_uid != os.getuid():
        falhar(f"{ARQUIVO} pertence a outro usuário (uid {info.st_uid}).")
    if len(ARQUIVO.read_text(encoding="utf-8").strip()) < TAMANHO_MINIMO:
        # Não substitui sozinho: trocar o segredo invalida todos os logins e deve ser decisão de quem opera
        falhar(f"{ARQUIVO} tem menos de {TAMANHO_MINIMO} caracteres. Apague o volume jwt-segredo para gerar outro.")
    os.chmod(ARQUIVO, 0o400)
    print("[segredo-jwt] Segredo já existia: mantido sem alteração.")


def criar() -> None:
    os.chmod(PASTA, 0o700)  # escrita liberada só durante a criação
    temporario = PASTA / f".jwt.{os.getpid()}.tmp"
    fd = os.open(temporario, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        os.write(fd, secrets.token_urlsafe(BYTES_ALEATORIOS).encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(temporario, ARQUIVO)  # falha se outro gerador criou o arquivo antes
    except FileExistsError:
        temporario.unlink()
        conferir_existente()
        return
    temporario.unlink()
    print("[segredo-jwt] Segredo novo gerado.")


def preparar_jwt() -> None:
    if not PASTA.is_dir():
        falhar(f"A pasta {PASTA} não existe (o volume jwt-segredo foi montado?).")
    if PASTA.stat().st_uid != os.getuid():
        falhar(f"A pasta {PASTA} pertence a outro usuário (uid {PASTA.stat().st_uid}).")
    try:
        if ARQUIVO.exists() or ARQUIVO.is_symlink():
            conferir_existente()
        else:
            criar()
        os.chmod(PASTA, 0o500)  # ninguém mais cria nem troca arquivos aqui
    except OSError as erro:
        falhar(f"não foi possível preparar o segredo ({type(erro).__name__}).")


# ---------- credenciais e definições do RabbitMQ ----------

def hash_senha_rabbitmq(senha: str, sal: bytes | None = None) -> str:
    """Formato rabbit_password_hashing_sha256: base64(sal de 4 bytes + SHA-256(sal + senha))."""
    sal = secrets.token_bytes(4) if sal is None else sal
    return base64.b64encode(sal + hashlib.sha256(sal + senha.encode("utf-8")).digest()).decode("ascii")


def hash_confere(senha: str, hash_b64: str) -> bool:
    try:
        bruto = base64.b64decode(hash_b64, validate=True)
    except (ValueError, TypeError):
        return False
    return len(bruto) == 36 and secrets.compare_digest(hash_b64, hash_senha_rabbitmq(senha, bruto[:4]))


def definicoes_rabbitmq(senhas: dict[str, str]) -> dict:
    """Definições importadas pelo RabbitMQ na subida (load_definitions). Só hashes, nunca senhas."""
    def exchange(nome, tipo):
        return {"name": nome, "vhost": MQ_VHOST, "type": tipo, "durable": True,
                "auto_delete": False, "internal": False, "arguments": {}}

    def ligacao(origem, destino, chave):
        return {"source": origem, "vhost": MQ_VHOST, "destination": destino, "destination_type": "queue",
                "routing_key": chave, "arguments": {}}

    return {
        "users": [{"name": usuario, "password_hash": hash_senha_rabbitmq(senha),
                   "hashing_algorithm": "rabbit_password_hashing_sha256", "tags": []}
                  for usuario, senha in senhas.items()],
        "vhosts": [{"name": MQ_VHOST}],
        "permissions": [{"user": usuario, "vhost": MQ_VHOST, "configure": c, "write": w, "read": r}
                        for usuario, (c, w, r) in CLIENTES_MQ.items()],
        "exchanges": [exchange(EXCHANGE_EVENTOS, "topic"), exchange(EXCHANGE_MORTAS, "fanout")],
        "queues": [
            {"name": FILA_EVENTOS, "vhost": MQ_VHOST, "durable": True, "auto_delete": False,
             "arguments": {"x-queue-type": "quorum", "x-delivery-limit": LIMITE_ENTREGAS,
                           "x-dead-letter-exchange": EXCHANGE_MORTAS}},
            {"name": FILA_MORTAS, "vhost": MQ_VHOST, "durable": True, "auto_delete": False,
             "arguments": {"x-queue-type": "quorum"}},
        ],
        "bindings": [ligacao(EXCHANGE_EVENTOS, FILA_EVENTOS, "chamado.*"), ligacao(EXCHANGE_MORTAS, FILA_MORTAS, "")],
    }


def arquivos_mq() -> dict[str, Path]:
    """Cada arquivo na sua subpasta: o serviço monta só a subpasta dele."""
    return {"definicoes": MQ_PASTA / "rabbitmq" / "definicoes.json",
            **{usuario: MQ_PASTA / usuario / "senha" for usuario in CLIENTES_MQ}}


def _gravar_somente_leitura(caminho: Path, conteudo: str) -> None:
    fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        os.write(fd, conteudo.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def criar_mq() -> None:
    os.chmod(MQ_PASTA, 0o700)  # escrita liberada só durante a criação
    senhas = {usuario: secrets.token_urlsafe(MQ_BYTES_SENHA) for usuario in CLIENTES_MQ}
    if len(set(senhas.values())) != len(senhas):  # praticamente impossível; nunca aceitar senhas iguais
        falhar("as senhas geradas para o RabbitMQ não são distintas.")
    # Tudo é montado numa pasta temporária e só então movido para o lugar:
    # os serviços nunca veem um arquivo pela metade.
    temporaria = Path(tempfile.mkdtemp(prefix=".novo-", dir=MQ_PASTA))
    try:
        for usuario, senha in senhas.items():
            (temporaria / usuario).mkdir(mode=0o700)
            _gravar_somente_leitura(temporaria / usuario / "senha", senha)
        (temporaria / "rabbitmq").mkdir(mode=0o700)
        _gravar_somente_leitura(temporaria / "rabbitmq" / "definicoes.json",
                                json.dumps(definicoes_rabbitmq(senhas), indent=2))
        for subpasta in (*CLIENTES_MQ, "rabbitmq"):  # definições por último
            os.rename(temporaria / subpasta, MQ_PASTA / subpasta)
            os.chmod(MQ_PASTA / subpasta, 0o500)
        temporaria.rmdir()
    finally:
        shutil.rmtree(temporaria, ignore_errors=True)  # só sobra algo aqui se a criação falhou
    print("[segredo-jwt] Credenciais e definições do RabbitMQ geradas.")


def conferir_mq() -> None:
    arquivos = arquivos_mq()
    for caminho in arquivos.values():
        info = caminho.lstat()
        if not stat.S_ISREG(info.st_mode):
            falhar(f"{caminho} existe, mas não é um arquivo comum.")
        if info.st_uid != os.getuid():
            falhar(f"{caminho} pertence a outro usuário (uid {info.st_uid}).")
    senhas = {usuario: arquivos[usuario].read_text(encoding="utf-8").strip() for usuario in CLIENTES_MQ}
    if any(len(senha) < TAMANHO_MINIMO for senha in senhas.values()) or len(set(senhas.values())) != len(senhas):
        falhar("as senhas do RabbitMQ estão curtas ou repetidas. Apague o volume de credenciais para gerar outras.")
    try:
        texto = arquivos["definicoes"].read_text(encoding="utf-8")
        usuarios = {u["name"]: u for u in json.loads(texto)["users"]}
    except (ValueError, KeyError, TypeError):
        falhar("as definições do RabbitMQ estão corrompidas. Apague o volume de credenciais para gerar outras.")
    if set(usuarios) != set(CLIENTES_MQ) or any(
            not hash_confere(senhas[u], usuarios[u].get("password_hash", "")) for u in CLIENTES_MQ):
        falhar("as definições do RabbitMQ não correspondem às senhas. Apague o volume de credenciais para gerar outras.")
    if any(senha in texto for senha in senhas.values()):
        falhar("as definições do RabbitMQ contêm senha em texto puro.")
    for caminho in arquivos.values():
        os.chmod(caminho, 0o400)
    print("[segredo-jwt] Credenciais do RabbitMQ já existiam: mantidas sem alteração.")


def preparar_mq() -> None:
    if not MQ_PASTA.is_dir():
        falhar(f"A pasta {MQ_PASTA} não existe (o volume de credenciais do RabbitMQ foi montado?).")
    if MQ_PASTA.stat().st_uid != os.getuid():
        falhar(f"A pasta {MQ_PASTA} pertence a outro usuário (uid {MQ_PASTA.stat().st_uid}).")
    try:
        existentes = [c for c in arquivos_mq().values() if c.exists() or c.is_symlink()]
        if not existentes:
            criar_mq()
        elif len(existentes) == len(arquivos_mq()):
            conferir_mq()
        else:
            # Nunca completa nem troca só uma parte: as senhas e os hashes precisam nascer juntos
            faltando = sorted(str(c.relative_to(MQ_PASTA)) for c in arquivos_mq().values() if c not in existentes)
            falhar(f"credenciais do RabbitMQ incompletas (faltam: {', '.join(faltando)}). "
                   "Apague o volume de credenciais para gerar outras.")
        os.chmod(MQ_PASTA, 0o500)
    except OSError as erro:
        falhar(f"não foi possível preparar as credenciais do RabbitMQ ({type(erro).__name__}).")


def main() -> None:
    preparar_jwt()
    if MQ_PASTA is not None:  # sem a variável, o gerador faz só o que sempre fez
        preparar_mq()


if __name__ == "__main__":
    main()
