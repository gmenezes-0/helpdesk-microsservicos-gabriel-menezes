# Segurança

Este projeto é didático, mas segue práticas de segurança reais. Esta página explica o que está protegido
na versão em microsserviços (com eventos pelo RabbitMQ), quais são os limites conhecidos e o que fica como
responsabilidade de quem for colocar o sistema em produção.

## O que continua protegido como no monólito

Cada serviço mantém as proteções que valiam para o monólito. Os testes de segurança foram adaptados
e rodam em cada um.

| Risco | Proteção |
|---|---|
| Acesso sem login | Todas as rotas, exceto `/auth/login`, `/saude`, a tela e `/docs`, exigem token JWT (`Authorization: Bearer ...`), e **cada serviço confere o token**. |
| Senhas vazadas do banco | Senhas guardadas só como hash **scrypt** com sal aleatório, no banco do Usuários. A senha nunca é salva nem devolvida pela API. |
| Adivinhar senhas | Bloqueio temporário após 5 tentativas erradas (por e-mail e endereço). Mensagem igual para e-mail inexistente e senha errada. |
| Token falsificado | Token assinado (HS256), com validade, emissor e algoritmo fixos (tokens `alg: none` são recusados). Os serviços exigem todos os campos e só aceitam perfis conhecidos. |
| Ver ou mexer no que não é seu | Permissões por perfil: o solicitante só vê os próprios chamados; cada pessoa só vê as próprias notificações; só técnicos e administradores atribuem, resolvem e cadastram equipamentos; só administradores criam usuários. |
| Agir em nome de outra pessoa | O solicitante, o autor do comentário, o perfil e o dono das notificações vêm do token assinado, nunca do corpo da requisição. Campos extras são recusados. |
| Descobrir o que existe | Chamado de outra pessoa responde "não encontrado" (404). A lista de usuários não mostra e-mails. |
| XSS na tela | Todo texto vindo da API é escapado; não há scripts embutidos; a política CSP só permite scripts do próprio servidor. |
| Clickjacking e outros | `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, no gateway e em cada serviço. |
| Dados enormes | Limites em todos os campos e corpo limitado a 64 KB, no gateway (também sem `Content-Length`) e em cada serviço. Mensagens da fila limitadas a 8 KB. |
| SQL injection | Acesso ao banco só pelo SQLAlchemy, com parâmetros. |
| Erros que vazam detalhes | Erros de banco e de comunicação entre serviços respondem com mensagem genérica; os detalhes ficam só no log. |
| Dependências vulneráveis | Versões fixas, `pip-audit` em cada projeto no GitHub Actions e Dependabot semanal em cada pasta, inclusive a imagem do RabbitMQ. |

## O que muda com os microsserviços

### Bancos separados

- Cada serviço tem o seu SQLite num volume Docker só dele: `usuarios-dados`, `inventario-dados`,
  `chamados-dados` e `notificacoes-dados`. O RabbitMQ tem o seu (`rabbitmq-dados`).
- Nenhum serviço monta o volume de outro. O gateway não monta volume nenhum.
- Os hashes de senha ficam **só** no banco do Usuários: os outros serviços nunca os veem.
- Um serviço comprometido expõe só os próprios dados. Para pedir os dos outros, ele passa pela API e pelas
  permissões do token, ou recebe eventos que só levam ids e datas.

### Segredos e credenciais

Ninguém digita, versiona ou passa por variável de ambiente nenhum segredo. Todos são gerados pelo contêiner
`segredo-jwt` ([infra/segredo-jwt](infra/segredo-jwt)), que roda uma vez antes de tudo, sem rede, sem root e sem
capacidades.

| Segredo | Onde fica | Quem lê |
|---|---|---|
| Segredo JWT (48 bytes aleatórios) | volume `jwt-segredo`, arquivo `jwt` (0400) | Usuários, Inventário, Chamados e Notificações, só leitura |
| Senha do usuário `chamados` no broker (32 bytes) | volume `mq-segredos`, `chamados/senha` (0400) | só o Chamados, montado como subpasta e só leitura |
| Senha do usuário `notificacoes` (32 bytes) | volume `mq-segredos`, `notificacoes/senha` (0400) | só o Notificações, idem |
| Definições do RabbitMQ (usuários, permissões, topologia) | volume `mq-segredos`, `rabbitmq/definicoes.json` (0400) | só o RabbitMQ, idem. Contém **só o hash** das senhas (SHA-256 com sal), nunca o texto |

- **Nunca sobrescreve.** Se os arquivos já existem, o gerador confere a consistência (recalcula o hash de cada
  senha) e mantém. Se só uma parte existe, ou algo está inválido, ele para com erro em vez de completar ou trocar,
  e nenhum serviço sobe.
- **Criação atômica.** Os arquivos nascem numa pasta temporária e só depois vão para o lugar: ninguém vê um
  arquivo pela metade.
- **Onde os segredos não aparecem:** no código, no Git, no `.env`, nas variáveis de ambiente (`docker inspect`)
  e nos logs (testado em todos os contêineres). As mensagens de erro também não os mostram.
- **Segredo JWT ausente ou curto:** os serviços recusam subir, para nunca assinar ou aceitar tokens com um segredo
  diferente dos outros.
- **Risco do segredo JWT:** é **simétrico** e compartilhado. Quem tiver acesso a qualquer um dos quatro serviços
  pode emitir tokens válidos para os outros. Veja as recomendações abaixo.

### Permissões no RabbitMQ

| Usuário | configure | write | read | Na prática |
|---|---|---|---|---|
| `chamados` | nada | `^helpdesk\.eventos$` | nada | Só publica na exchange de eventos |
| `notificacoes` | nada | nada | `^notificacoes\.eventos$` | Só lê a própria fila |

Verificado contra o broker real:
- o Chamados **não consegue consumir**, ler a DLQ, publicar direto na fila pela exchange padrão, declarar, apagar
  ou ligar filas;
- o Notificações **não consegue publicar**, nem na exchange de eventos, nem pela exchange padrão.

Esses pedidos recebem `403 ACCESS_REFUSED`.

Mais proteções do broker:
- **sem `guest`:** com as definições importadas, o RabbitMQ não cria o usuário padrão. A configuração da imagem,
  que liberava o `guest` de qualquer endereço, foi substituída;
- **sem administrador:** nenhum usuário tem tags. A operação local usa `rabbitmqctl` dentro do contêiner;
- **sem plugins:** nem painel web, nem a porta de métricas que a imagem liga por padrão;
- **só a porta AMQP 5672 na rede**, e só na rede interna. O clustering do Erlang e o EPMD escutam só no localhost;
- **imagem `rabbitmq:4.4.1-alpine` fixada por digest**, rodando como uid 10001, com a pasta de dados 0700,
  somente leitura, `cap_drop: ALL` e `no-new-privileges`.

### Eventos: contrato, deduplicação, DLQ e recuperação

- **Conteúdo:** o evento só leva ids e datas. Nada de token, e-mail, título ou descrição do chamado.
- **Contrato rígido no consumidor:** campos a mais ou faltando, tipos convertidos (`"7"` no lugar de `7`,
  `true` no lugar de `1`), tipo de evento desconhecido, outra versão, ids fora da faixa ou mensagem com mais de
  8 KB são recusados. O log registra só o motivo e o tamanho, nunca o conteúdo.
- **Mensagens mortas (DLQ):** mensagem fora do contrato vai direto para `notificacoes.eventos.dlq`
  (`basic_reject` sem requeue). Falha temporária (banco travado) volta para a fila com `basic_reject`. Depois de
  5 devoluções (`delivery-limit` da fila quorum), ela também vai para a DLQ, e uma mensagem problemática não
  trava a fila. O `basic_nack` não é usado porque, no RabbitMQ 4.4.1, ele não conta para esse limite.
- **Deduplicação:** a entrega é pelo menos uma vez (reconexões e republicações podem repetir uma mensagem).
  O `evento_id` é `UNIQUE` no banco de Notificações, e uma repetição nunca vira um segundo aviso.
- **Sem perda de eventos:** o Chamados grava o evento na **mesma transação** do chamado (caixa de saída) e só
  marca como publicado depois da confirmação do broker. Com o broker ou o Notificações fora, os eventos esperam
  (no banco do Chamados ou na fila durável, que sobrevive a reinícios) e são entregues quando o serviço volta.
- **Ack só depois do commit:** se o Notificações cair no meio, a mensagem volta para a fila.
- **Ninguém cria aviso pela API:** `/notificacoes` só tem `GET`. Avisos só nascem de eventos, e só o usuário
  `chamados` pode publicar eventos.

### Autenticação e autorização entre serviços

- Só o Usuários emite tokens (login). Os outros só validam.
- O Chamados chama Usuários e Inventário repassando o `Authorization` **do próprio usuário**, como veio.
  - Não existe "token de serviço" com poderes extras, então o serviço chamado aplica as permissões de quem
    fez o pedido.
  - Um `401` ou `403` vindo de outro serviço vira `503` genérico, e nunca é confundido com erro de regra de negócio.
- O token **não** vai nos eventos: a ligação entre Chamados e Notificações usa só as credenciais do broker.
- Chamadas internas têm tempo limite (3 s no Chamados, 10 s no gateway), não seguem redirecionamentos
  e ignoram proxies configurados no ambiente.

### Rede interna e portas

- **Só o gateway publica porta**, e só em `127.0.0.1:8000`, ou seja, apenas para o próprio computador.
  Os serviços e o RabbitMQ não publicam portas.
- **Redes:**
  - `borda` tem só o gateway;
  - `interna` (`internal: true`) tem o gateway, os serviços e o RabbitMQ, sem saída para a internet e sem alcance
    a partir de fora;
  - um contêiner na rede de borda não alcança os serviços nem o RabbitMQ, nem por nome nem por IP (testado).
- **Endereço do cliente:**
  - o gateway **descarta** `X-Forwarded-For`, `X-Real-IP` e `Forwarded` enviados pelo cliente e escreve o
    seu, com o endereço real da conexão;
  - o próprio uvicorn do gateway roda com `--no-proxy-headers`;
  - os serviços só aceitam `X-Forwarded-For` vindo do IP fixo do gateway (`FORWARDED_ALLOW_IPS`);
  - forjar o cabeçalho não contorna o bloqueio de tentativas de login (testado: a 6ª tentativa recebe 429).
- **Logs:** o gateway registra só o método, o caminho e o tipo do erro, nunca cabeçalhos nem tokens.

### Contêineres

Todos, inclusive o gerador e o RabbitMQ:

- sistema de arquivos **somente leitura** (`read_only: true`);
- `cap_drop: ALL` e `no-new-privileges`;
- usuário sem privilégios (uid 10001);
- `/tmp` em memória, limitado e com `noexec`, `nosuid` e `nodev`, só onde é preciso;
- healthcheck sem ferramentas extras na imagem.

## Limitações conhecidas

- **Tokens validados localmente continuam valendo até vencer.** Inventário, Chamados e Notificações não
  consultam o Usuários a cada pedido. Um usuário desativado, ou com o perfil rebaixado, ainda é aceito por esses
  serviços até o token expirar (`TOKEN_MINUTOS`, 60 min por padrão). O Usuários recusa na hora.
  Para revogar todos os tokens de uma vez, troque o segredo: `docker volume rm helpdesk_jwt-segredo`.
- **Tráfego interno sem TLS.** O HTTP entre serviços e o AMQP com o RabbitMQ não são cifrados. Ficam só na
  rede interna, mas quem estiver dentro dela pode observá-los.
- **O consumidor pode esvaziar a própria fila.** No AMQP, purgar uma fila exige só a permissão de leitura, que o
  consumidor precisa ter. O risco é o mesmo de ele consumir e descartar as mensagens.
- **DLQ sem alerta nem reprocessamento automático.** Mensagens mortas precisam ser vistas à mão (`rabbitmqctl`).
- **IP de origem no Docker Desktop.** No Windows e no macOS, todo acesso vindo do próprio computador chega
  ao gateway com o mesmo IP da ponte do Docker. O bloqueio por "e-mail + endereço" acaba tratando todos
  os acessos locais como um só endereço. O bloqueio por e-mail continua valendo.
- **Limite de tentativas em memória.** Funciona com uma instância do Usuários e zera quando o serviço reinicia.
- **Sem HTTPS.** A porta só aceita conexões do próprio computador.
- **Documentação aberta.** `/docs` e `/openapi.json` ficam ligados por padrão, para a aula.

## Credenciais de demonstração

- Com `DADOS_EXEMPLO=1` (o padrão), o sistema cria 5 contas com senha **conhecida e pública**
  (`Helpdesk2026`, ou o valor de `SENHA_EXEMPLO`), listadas no README.
- Essa senha aparece como valor padrão no `docker-compose.yml`. Não é um segredo: ela só existe para a demonstração.
- As credenciais do RabbitMQ **não** são de demonstração: são aleatórias e geradas em cada instalação.
- **Nunca** use as contas de exemplo fora da aula.

## Antes de usar em produção

- **Dados de exemplo:** rode com `DADOS_EXEMPLO=0` e crie as contas reais pelo administrador. Rode também com `DOCS=0`.
- **HTTPS:** coloque o gateway atrás de HTTPS, por exemplo um proxy reverso com certificado. Ajuste o
  `--no-proxy-headers` do gateway para confiar **só** no IP desse proxy.
- **Segredos:** guarde o segredo JWT e as senhas do broker num cofre (Docker/Kubernetes secrets, Vault…) com rotação.
  - Melhor ainda: troque o HS256 por **chaves assimétricas** (RS256 ou EdDSA). Assim, só o Usuários tem a chave
    privada, e os outros serviços só a pública: um serviço invadido não consegue emitir tokens.
- **Revogação:** reduza `TOKEN_MINUTOS` ou adote uma lista de revogação, para que a desativação de um usuário
  valha na hora.
- **Banco:** troque o SQLite por um banco gerenciado (PostgreSQL), **um por serviço**, com credenciais
  diferentes e backup.
- **Tráfego interno:** ative TLS no RabbitMQ (AMQPS) e proteja as chamadas HTTP entre serviços, por exemplo com
  mTLS ou uma malha de serviços.
- **Mensageria:** monitore a DLQ (alerta quando houver mensagens) e o tamanho da caixa de saída do Chamados.
- **Tentativas de login:** mova o limite para um armazenamento compartilhado (Redis) se houver mais de uma
  instância do Usuários.
- **Logs:** centralize os logs e monitore o `/saude` agregado do gateway.

## Como relatar um problema

Encontrou uma falha? Não abra uma issue pública: envie os detalhes diretamente ao professor.
