"""Gera o segredo que assina os tokens JWT, uma única vez, no volume compartilhado.

- 48 bytes aleatórios de `secrets` (gerador criptograficamente seguro), em base64 url-safe.
- Nunca sobrescreve: se o arquivo já existe, só confere se é válido e mantém.
  A criação é atômica (arquivo temporário + os.link, que falha se o destino existir),
  então um segredo pela metade nunca fica visível para os serviços.
- Permissões: arquivo 0400 e pasta 0500, ambos do usuário 10001 (o mesmo dos serviços,
  que montam o volume só para leitura).
- O valor do segredo nunca é impresso.
"""
import os
import secrets
import stat
import sys
from pathlib import Path

PASTA = Path(os.getenv("SEGREDO_PASTA", "/segredos"))
ARQUIVO = PASTA / "jwt"
BYTES_ALEATORIOS = 48     # 384 bits; vira um texto de 64 caracteres
TAMANHO_MINIMO = 32       # o mesmo mínimo que os serviços exigem


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


def main() -> None:
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


if __name__ == "__main__":
    main()
