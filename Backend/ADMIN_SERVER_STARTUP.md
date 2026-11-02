# PASSO 92 — entrada preparada, sem publicação

`app.admin_server:create_app` é uma factory Uvicorn que reutiliza
`create_admin_entrypoint` e a composição administrativa existente. Importar o
módulo não inicializa Firebase nem carrega configuração. `app.main:app` continua
inalterado, sem routers Admin. Não há segundo backend.

## Seleção e configuração

O padrão é Admin indisponível: `/admin` e `/admin/*` retornam 503 sem alcançar
login ou operações. As rotas públicas continuam delegadas ao mesmo `app.main`.
Configuração inválida, falha de construção ou vínculo Firestore incorreto também
desabilitam todo o ramo Admin, sem imprimir a exceção original.

Somente `ADMIN_HTTP_MODE=public-authenticated` no ambiente do **processo** solicita
a construção administrativa. Ausência ou `disabled` não lê sequer o `.env`.
O `.env` sozinho nunca pode habilitar essa entrada.

Na seleção explícita, todos os campos abaixo são obrigatórios. O processo tem
prioridade sobre valores do `Backend/.env`, inclusive quando seu valor é inválido.
O parser lê o arquivo sem interpolação e sem modificar o ambiente.

| Configuração | Contrato |
| --- | --- |
| `ADMIN_HTTP_ENVIRONMENT` | Exatamente `production` |
| `ADMIN_HTTP_ORIGIN` | Uma origem HTTPS serializada do Admin, sem caminho, credenciais ou wildcard |
| `ADMIN_API_ORIGIN` | Origem HTTPS distinta da API; restringe o Host somente no ramo Admin |
| `FIREBASE_PROJECT_ID` | Projeto esperado, explicitamente confirmado; não aceita `demo-*` |
| `ADMIN_ADMISSION_HMAC_SECRET` | Mesmo contrato seguro já existente: 64 caracteres hexadecimais minúsculos; nunca usar o segredo sintético dos testes |
| `ADMIN_ADMISSION_POLICY_CONFIG` | JSON completo do contrato `configured-v1`, abaixo |

Não há valor opcional que habilite acesso, renove sessões ou relaxe segurança.
Origens locais e literais IP são rejeitados nessa entrada de produção. Nomes
definitivos continuam pendentes; nenhum domínio do cliente foi fixado no código.
Preferir origens HTTPS canônicas sem porta padrão explícita.

Exemplo **não secreto** da estrutura JSON da política, a ser escolhida
explicitamente em uma futura operação autorizada:

```json
{"schema_version":1,"policy":{"origin":{"capacity":10,"refill_tokens":1,"refill_period_seconds":30},"origin_identity":{"capacity":5,"refill_tokens":1,"refill_period_seconds":60},"identity":{"capacity":5,"refill_tokens":1,"refill_period_seconds":60},"aggregate":{"capacity":20,"refill_tokens":1,"refill_period_seconds":30}}}
```

Não há promoção automática da referência local. O parser reutiliza os modelos,
validações e algoritmo existentes; exige quatro buckets e rejeita campos extras,
JSON duplicado, constantes não finitas, esquema incorreto e valores inválidos.
Políticas persistidas incompatíveis continuam falhando de forma segura durante
a admissão: não são migradas, apagadas ou redefinidas. Mudanças futuras exigem o
procedimento coordenado de `ADMIN_ADMISSION_CONFIGURATION.md`; todas as instâncias
devem compartilhar política e segredo. Não rotacionar o HMAC para limpar limites.

## Firestore e separação de ambientes

Reutiliza `firebase_service.get_firestore_client`, incluindo prioridade existente
de `FIREBASE_CREDENTIALS_JSON` sobre `FIREBASE_CREDENTIALS_PATH` e cache do SDK.
Não cria um carregador alternativo de credenciais nem exige bootstrap.
`FIREBASE_PROJECT_ID` confirma o vínculo do cliente; não substitui a credencial.
Variáveis `GOOGLE_CLOUD_PROJECT`, `GCLOUD_PROJECT` ou `GCP_PROJECT`, quando
presentes, devem coincidir com esse projeto.

A presença de `FIRESTORE_EMULATOR_HOST`, `DATASTORE_EMULATOR_HOST` ou
`FIRESTORE_TEST_PROJECT_ID`, mesmo vazia, impede a construção antes de obter o
cliente. Isso inclui valores encontrados no `.env`. Após obter o cliente, verifica
novamente o ambiente e exige projeto correspondente, banco `(default)` e ausência
de `_emulator_host`. Essa inspeção usa metadados do SDK e não faz consultas ao
banco. Os atributos privados de vínculo precisam ser revalidados em upgrades do SDK.

O serviço Firebase existente pode carregar seu `.env` ao inicializar em uma futura
execução autorizada. Nenhuma execução real desse carregador foi necessária nos
testes desta etapa. IAM, índices e disponibilidade do projeto real não são
comprovados por parsing/mocks. Confirmar previamente permissões mínimas de leitura,
escrita e transações nas coleções utilizadas, índices e projeto/banco correto.
Erros de Firestore em requisições continuam 503, sem liberar autenticação.

## Segurança preservada

O ramo Admin mantém HTTPS, CORS restrito à origem configurada com credenciais,
Origin, CSRF/X-Admin-Request, autorização, Argon2id, quatro buckets atômicos e
sessões de oito horas sem renovação automática. Cookie `__Host-admin_session`:
Secure, HttpOnly, SameSite=Lax, Path=/, sem Domain. Host incorreto ou duplicado
é rejeitado apenas no ramo Admin. O Host não autentica usuários ou proxies.

Para esse cookie funcionar de modo compatível, Admin na HostGator e API no Render
precisam ter domínios HTTPS do mesmo site registrável, confirmado operacionalmente.
O parser não verifica DNS, certificados ou Public Suffix List. Não presumir que
dois nomes configurados comprovam essa condição. O portal existente fica intacto.

CF-Connecting-IP continua informação operacional com validação sintática, sem
fallback para XFF, X-Real-IP ou peer. A garantia de sobrescrita de valores enviados
pelo cliente no Render continua não comprovada. IP não autentica, não autoriza e
não é proteção única: identidade e agregado independem dele. Contenção e negação
de serviço no bucket agregado permanecem riscos, mesmo com a recuperação limitada
do PASSO 91. Não há garantia de disponibilidade sob ataque.

Health, rotas públicas e webhook Kirvano mantêm caminhos, métodos, segurança,
contratos e implementação originais. Não recebem Host, sessão, CORS ou CSRF Admin.

## Operação futura — não executada

Somente após autorização, revisão das configurações, domínios/HTTPS, IAM, índices
e homologação operacional, o serviço Render **existente** poderia usar:

```sh
uvicorn app.admin_server:create_app --factory --host 0.0.0.0 --port "$PORT"
```

Executar a partir de `Backend`, conforme o diretório de execução do serviço.
Não incluir segredos na linha de comando ou no Git. Configurar o ambiente pelo
mecanismo operacional já existente apenas com autorização. Cada worker constrói
sua própria composição; Firestore/HMAC/política são compartilhados logicamente.
Esta etapa não alterou o Start Command, variáveis, workers ou configuração de proxy.

Rollback futuro: retirar a seleção administrativa (`ADMIN_HTTP_MODE=disabled`) e
reiniciar controladamente, ou restaurar o Start Command anterior
`uvicorn app.main:app --host 0.0.0.0 --port "$PORT"`. Não apagar sessões, buckets,
auditoria ou administradores. A API pública/Kirvano permanece na aplicação original.

## Validação local

`tests/test_admin_server.py` usa somente configurações/segredos sintéticos e
repositório em memória; bloqueia a construção Firebase padrão. Exercita seleção,
parsing, bloqueio de Emulator, vínculo de cliente, login/sessão/logout, cookie,
CORS, 401/403/503, importação inerte e preservação pública. A suíte completa cobre
os contratos de composição, autenticação, admissão e webhook reutilizados.
Não é necessário Emulator para a nova lógica de startup: não altera transações.
Nenhuma homologação real de Render, HostGator ou navegador é afirmada aqui.
