# Segurança

Este projeto é didático, mas segue práticas de segurança reais. Esta página explica o que está protegido
na versão em microsserviços, quais são os limites conhecidos e o que fica como responsabilidade de quem
for colocar o sistema em produção.

## O que continua protegido como no monólito

Cada serviço mantém as proteções que valiam para o monólito. Os testes de segurança foram adaptados
e rodam em cada um.

| Risco | Proteção |
|---|---|
| Acesso sem login | Todas as rotas, exceto `/auth/login`, `/saude`, a tela e `/docs`, exigem token JWT (`Authorization: Bearer ...`), e **cada serviço confere o token**. |
| Senhas vazadas do banco | Senhas guardadas só como hash **scrypt** com sal aleatório, no banco do Usuários. A senha nunca é salva nem devolvida pela API. |
| Adivinhar senhas | Bloqueio temporário após 5 tentativas erradas (por e-mail e endereço). Mensagem igual para e-mail inexistente e senha errada. |
| Token falsificado | Token assinado (HS256), com validade, emissor e algoritmo fixos (tokens `alg: none` são recusados). Os serviços exigem todos os campos e só aceitam perfis conhecidos. |
| Ver ou mexer no que não é seu | Permissões por perfil: o solicitante só vê os próprios chamados e notificações; só técnicos e administradores atribuem e resolvem e cadastram equipamentos; só administradores criam usuários. |
| Agir em nome de outra pessoa | O solicitante, o autor do comentário e o perfil vêm do token assinado, nunca do corpo da requisição. Campos extras são recusados. |
| Descobrir o que existe | Chamado de outra pessoa responde "não encontrado" (404). A lista de usuários não mostra e-mails. |
| XSS na tela | Todo texto vindo da API é escapado; não há scripts embutidos; a política CSP só permite scripts do próprio servidor. |
| Clickjacking e outros | `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, no gateway e em cada serviço. |
| Dados enormes | Limites em todos os campos e corpo limitado a 64 KB, no gateway (também sem `Content-Length`) e em cada serviço. |
| SQL injection | Acesso ao banco só pelo SQLAlchemy, com parâmetros. |
| Erros que vazam detalhes | Erros de banco e de comunicação entre serviços respondem com mensagem genérica; os detalhes ficam só no log. |
| Dependências vulneráveis | Versões fixas, `pip-audit` em cada projeto no GitHub Actions e Dependabot semanal em cada pasta. |

## O que muda com os microsserviços

### Bancos separados

- Cada serviço tem o seu SQLite num volume Docker só dele: `usuarios-dados`, `inventario-dados` e `chamados-dados`.
- Nenhum serviço monta o volume de outro. O gateway não monta volume nenhum.
- Os hashes de senha ficam **só** no banco do Usuários: Inventário e Chamados nunca os veem.
- Um serviço comprometido expõe só os próprios dados. Para pedir os dos outros, ele passa pela API e pelas
  permissões do token.

### Segredo JWT compartilhado

- **Geração:** o contêiner `segredo-jwt` ([infra/segredo-jwt](infra/segredo-jwt)) roda uma vez antes de tudo
  e gera 48 bytes aleatórios com `secrets`.
  - A gravação é atômica e nunca sobrescreve um segredo existente.
  - O arquivo fica com permissão `0400` e a pasta com `0500`.
  - O gerador roda como uid 10001, sem capacidades e sem rede.
- **Uso:**
  - os três serviços leem o mesmo arquivo (`JWT_SEGREDO_ARQUIVO=/segredos/jwt`), num volume montado **só para leitura**;
  - o gateway não tem acesso ao segredo.
- **Onde o segredo não aparece:** no código, no Git, no `.env`, nas variáveis de ambiente (`docker inspect`)
  e nos logs. As mensagens de erro também não o mostram.
- **Segredo ausente ou curto:** com menos de 32 caracteres, o gerador e os serviços **recusam subir**. Assim,
  nenhum serviço assina ou aceita tokens com um segredo diferente dos outros.
- **Risco:** é um segredo **simétrico** compartilhado. Quem tiver acesso a qualquer um dos três serviços pode
  emitir tokens válidos para os outros. Veja as recomendações abaixo.

### Autenticação e autorização entre serviços

- Só o Usuários emite tokens (login). Os outros só validam.
- O Chamados chama Usuários e Inventário repassando o `Authorization` **do próprio usuário**, como veio.
  - Não existe "token de serviço" com poderes extras, então o serviço chamado aplica as permissões de quem
    fez o pedido.
  - Um `401` ou `403` vindo de outro serviço vira `503` genérico, e nunca é confundido com erro de regra de negócio.
- Chamadas internas têm tempo limite (3 s no Chamados, 10 s no gateway), não seguem redirecionamentos
  e ignoram proxies configurados no ambiente.

### Rede interna e portas

- **Só o gateway publica porta**, e só em `127.0.0.1:8000`, ou seja, apenas para o próprio computador.
  Os serviços não publicam portas.
- **Redes:**
  - `borda` tem só o gateway;
  - `interna` (`internal: true`) tem o gateway e os serviços, sem saída para a internet e sem alcance a partir de fora;
  - um contêiner na rede de borda não alcança os serviços nem por nome nem por IP (testado).
- **Endereço do cliente:**
  - o gateway **descarta** `X-Forwarded-For`, `X-Real-IP` e `Forwarded` enviados pelo cliente e escreve o
    seu, com o endereço real da conexão;
  - o próprio uvicorn do gateway roda com `--no-proxy-headers`;
  - os serviços só aceitam `X-Forwarded-For` vindo do IP fixo do gateway (`FORWARDED_ALLOW_IPS`);
  - forjar o cabeçalho não contorna o bloqueio de tentativas de login (testado: a 6ª tentativa recebe 429).
- **Logs:** o gateway registra só o método, o caminho e o tipo do erro, nunca cabeçalhos nem tokens.

### Contêineres

Todos, inclusive o gerador:

- sistema de arquivos **somente leitura** (`read_only: true`);
- `cap_drop: ALL` e `no-new-privileges`;
- usuário sem privilégios (uid 10001);
- `/tmp` em memória (16 MB, `noexec`, `nosuid`, `nodev`) só nos serviços com banco;
- healthcheck sem ferramentas extras na imagem, feito pelo próprio Python.

## Limitações conhecidas

- **Tokens validados localmente continuam valendo até vencer.** Inventário e Chamados não consultam o
  Usuários a cada pedido. Um usuário desativado, ou com o perfil rebaixado, ainda é aceito por esses dois
  serviços até o token expirar (`TOKEN_MINUTOS`, 60 min por padrão). O Usuários recusa na hora.
  Para revogar todos os tokens de uma vez, troque o segredo: `docker volume rm helpdesk_jwt-segredo`.
- **IP de origem no Docker Desktop.** No Windows e no macOS, todo acesso vindo do próprio computador chega
  ao gateway com o mesmo IP da ponte do Docker. O bloqueio por "e-mail + endereço" acaba tratando todos
  os acessos locais como um só endereço. O bloqueio por e-mail continua valendo.
- **Limite de tentativas em memória.** Funciona com uma instância do Usuários. Com várias, cada uma
  teria a sua contagem. A contagem também zera quando o serviço reinicia.
- **Sem HTTPS e sem criptografia entre serviços.** O tráfego dentro da rede interna é HTTP simples.
- **Documentação aberta.** `/docs` e `/openapi.json` ficam ligados por padrão, para a aula.

## Credenciais de demonstração

- Com `DADOS_EXEMPLO=1` (o padrão), o sistema cria 5 contas com senha **conhecida e pública**
  (`Helpdesk2026`, ou o valor de `SENHA_EXEMPLO`), listadas no README.
- Essa senha aparece como valor padrão no `docker-compose.yml`. Não é um segredo: ela só existe para a demonstração.
- **Nunca** use essas contas fora da aula.

## Antes de usar em produção

- **Dados de exemplo:** rode com `DADOS_EXEMPLO=0` e crie as contas reais pelo administrador. Rode também com `DOCS=0`.
- **HTTPS:** coloque o gateway atrás de HTTPS, por exemplo um proxy reverso com certificado. Ajuste o
  `--no-proxy-headers` do gateway para confiar **só** no IP desse proxy.
- **Segredo:** guarde o segredo JWT num cofre (Docker/Kubernetes secrets, Vault…) com rotação.
  - Melhor ainda: troque o HS256 por **chaves assimétricas** (RS256 ou EdDSA). Assim, só o Usuários tem a chave
    privada, e os outros serviços só a pública: um serviço invadido não consegue emitir tokens.
- **Revogação:** reduza `TOKEN_MINUTOS` ou adote uma lista de revogação, para que a desativação de um usuário
  valha na hora.
- **Banco:** troque o SQLite por um banco gerenciado (PostgreSQL), **um por serviço**, com credenciais
  diferentes e backup.
- **Tráfego interno:** proteja as chamadas entre serviços, por exemplo com mTLS ou uma malha de serviços.
- **Tentativas de login:** mova o limite para um armazenamento compartilhado (Redis) se houver mais de uma
  instância do Usuários.
- **Logs:** centralize os logs e monitore o `/saude` agregado do gateway.

## Como relatar um problema

Encontrou uma falha? Não abra uma issue pública: envie os detalhes diretamente ao professor.
