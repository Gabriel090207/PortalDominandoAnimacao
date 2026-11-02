# PASSO 96 — instalação controlada no lifespan

Implementação e validação com provedores fake. Não habilita envio, Admin, domínio,
serviço externo ou transporte real. Não modifica transações comerciais ou a rota
Kirvano nesta etapa. Reutiliza dispatcher, reserva, template, trigger e recuperação.

## Entrada pública e entrada administrativa

`app.main.create_app(welcome_installation=...)` constrói a mesma FastAPI pública,
com CORS, root, health e webhook existentes. A variável `app.main:app` continua
sendo construída por `create_app()` SEM instalação. O Start Command existente não
foi alterado. Importar módulos, criar a app padrão ou ter variáveis de Resend no
ambiente não instala nem envia e-mail. Não há router Admin em app.main.

A factory `app.admin_server.create_app` aceita `public_app` e/ou
`welcome_installation`. Se precisar criar a aplicação pública explícita, chama a
mesma factory de app.main. O dispatcher ASGI administrativo delega o lifespan à
mesma aplicação pública. Não instala um runtime no ramo Admin. Falha/ausência de
configuração Admin mantém esse ramo 503, sem impedir e-mail explicitamente
selecionado ou o webhook público. Instalar e-mail não habilita Admin.

Há dois caminhos alternativos, não cumulativos:

1. Criar `public = app.main.create_app(welcome_installation=selection)` e passá-la
   a `app.admin_server.create_app(public_app=public, ...)`, sem repetir a seleção.
2. Passar `welcome_installation=selection` à factory administrativa para ela criar
   a aplicação pública uma única vez.

Não registrar a mesma seleção novamente sobre public_app já preparada. Não
criar duas aplicações concorrentes para representar o mesmo backend.

## Seleção e dependências explícitas

`WelcomeRuntimeInstallation` é um descritor interno, sem I/O. Por padrão,
`enabled=False`. Para instalar, exige todos os itens:

- `enabled=True`, como booleano, além de `config.enabled=True`.
- `PurchaseWelcomeConfig` válido, reutilizado do PASSO 94.
- `WelcomeTriggerPolicy` válido, com corte temporal obrigatório, recuperação
  explicitamente selecionada e lote entre 1 e 20.
- Cliente Firestore já construído pelo chamador, com projeto esperado e `(default)`.
- `expected_project_id` informado e exatamente correspondente ao cliente.
- `provider_factory(config)` injetada, que crie um provedor NOVO com `send` e `close`.
  A factory deve somente construir o adapter/fake, sem enviar nem fazer sondagens.

Config e política são revalidadas antes de construir o provedor. Uma configuração
incompleta/inválida ou vínculo Firestore divergente não chama a factory do provedor.
Uma factory ausente, inválida ou que falha deixa o e-mail indisponível, sem derrubar
health/webhook. O descritor pode ser preparado antes do startup sem criar provedor.
Erros de programação como tipo incorreto de descritor ou preparação duplicada
são rejeitados com exceção sanitizada, antes de servir a app.

As variáveis continuam as existentes, sem novos segredos:

| Campo | Contrato |
| --- | --- |
| PURCHASE_WELCOME_SEND_ENABLED | true explícito no processo para o loader de envio; padrão false |
| RESEND_API_KEY | SecretStr validada, nunca registrada |
| PURCHASE_WELCOME_FROM | E-mail simples canônico; domínio/remetente verificados operacionalmente |
| PURCHASE_WELCOME_WHATSAPP_URL | Contato oficial conforme validador wa.me existente |
| PURCHASE_WELCOME_NOT_BEFORE | ISO-8601 com fuso, obrigatório no loader do trigger; instante autorizado fixo |
| PURCHASE_WELCOME_RECOVERY_ENABLED | true/false, padrão false |
| PURCHASE_WELCOME_RECOVERY_BATCH_SIZE | 1 a 20, padrão 5 |

Os loaders existentes continuam disponíveis. Esta factory NÃO os executa por
importação ou startup padrão; a composição futura autorizada deve carregar e
validar seus valores e fornecer config/política no descritor. Presença de variáveis,
isoladamente, nunca equivale à seleção da instalação. Nenhum valor real foi lido,
criado ou configurado nesta etapa. Não colocar chave no React ou no Git.

## Projeto e Emulator

A instalação confere os metadados `project`, `_database` e `_emulator_host` do SDK.
Por padrão rejeita projeto demo e qualquer Emulator. Não faz leitura/escrita para
validar a conexão. Projeto esperado deve ser o confirmado para o portal/Kirvano;
não é inferido por inspeção de credenciais privadas nem hardcoded no código.
Esse guard verifica vínculo local do cliente, não comprova IAM/índices/DNS remoto.
Atributos privados do SDK devem ser revalidados em atualizações da biblioteca.

Testes precisam de `allow_emulator=True` explícito e exatamente projeto
`demo-dominando-animacao-test`, host `127.0.0.1:8080`, banco `(default)`. Combinações
mistas (demo sem opt-in, host remoto, projeto diferente ou banco nomeado) falham
antes do provedor. Não existe criação automática de cliente Firebase nem fallback
para credenciais ou banco diferentes. O cliente compartilhado pertence ao chamador
e NÃO é fechado pelo runtime de e-mail.

## Ciclo de vida e duplicidade

A factory prepara o descritor; `purchase_welcome_lifespan` instala o runtime uma
vez, durante startup, chamando o instalador do PASSO 95. A composição aceita agora
provedor diretamente, ou transporte HTTP do adapter como alternativa exclusiva;
não se fornecem ambos. Nos testes desta etapa, a factory retorna somente fake.
Nenhum transporte real padrão foi adicionado.

Guard de preparação impede duas seleções no mesmo app e rejeita tentativa de
preparar um app que já tenha trigger manual. O instalador manual também rejeita
um app que já tenha seleção gerida preparada, impedindo instalação fora da ordem
do lifespan. Lock e marca de atividade impedem
um segundo lifespan concorrente de instalar outro runtime sobre o primeiro.
Uma segunda entrada que referencia a mesma app usa a mesma instalação. Não há
registro global de clientes que impeça apps sintéticas independentes nos testes.
A política de reservas no Firestore continua responsável pela concorrência entre
processos/instâncias distintos.

Se recuperação estiver habilitada, agenda UM lote limitado em threadpool. Não
aguarda Resend no startup para disponibilizar health. No shutdown gracioso aguarda
o lote finito, fecha o provedor criado por esse lifespan e remove o trigger gerido.
Novo lifespan constrói um novo provedor pela factory e consulta o estado durável,
sem reutilizar cliente HTTP fechado ou reabrir reservas. Se o processo for morto,
essa limpeza pode não executar; a proteção persiste no Firestore.

Status interno em app.state: prepared, installed, disabled, unavailable ou stopped.
Não é endpoint público, resposta HTTP com segredo nem prova de envio/entrega.
Runtimes manuais do PASSO 95 continuam com ciclo de vida do chamador; o novo
lifespan não toma posse nem fecha recursos que não instalou.

## Depois da compra e em reinícios

Com instalação válida: SALE_APPROVED elegível confirma transação de cliente,
compra e intenção pending; o webhook agenda tarefa pós-resposta; ela encontra a
intenção persistida, reserva in_progress em transação, chama o provedor fake fora
da transação e finaliza accepted com ID ou requires_review. Não promete entrega.
Falha de agendamento/envio não desfaz compra, assinatura, entitlement ou cliente.
O comprador permanece pendente de ativação manual. Reenvio de webhook não gera
nova intenção ou envio. Outros eventos continuam sem boas-vindas novas.

O teste HTTP TestClient espera pela execução de BackgroundTasks, mas no protocolo
ASGI a resposta é enviada antes da tarefa. O webhook não mantém transação comercial
aberta aguardando provedor. O processamento síncrono permanece em threadpool.

Recuperação só seleciona pending pós-corte, com limite configurado e índice descrito
no PASSO 95. Corte também é conferido dentro da reserva. Não retroceder o corte nem
usar um novo now() a cada boot. accepted, requires_review e in_progress não voltam
automaticamente a pending, mesmo após reinício ou 24h. Timeout/rede/commit incerto
exigem reconciliação, não retry cego. O Resend não deduplica indefinidamente.

## Limites e habilitação futura

Um lote de startup não garante drenagem contínua. Enquanto Render estiver suspenso,
não há processamento; sem reinício ou com backlog maior que o lote podem restar
pending. Recuperação interna controlada continua disponível, sem polling permanente,
cron externo, segundo servidor ou serviço pago. Não afirmar exactly-once ou entrega
garantida. Corrupção/índice ausente/falha Firestore podem bloquear o lote de forma
segura e exigem acompanhamento/reconciliação autorizados.

Para primeiro envio real ainda faltam autorização explícita, chave de envio,
remetente/domínio verificados, WhatsApp oficial, corte autorizado fixo, índice/IAM e
projeto/banco confirmados, factory de provedor real com TLS normal e destinatário
controlado. Será preciso fornecer esse descritor no bootstrap autorizado do serviço
existente; a app padrão permanece sem ele. Nada foi configurado no Render, e nenhum
Start Command ou domínio foi alterado. Não publicar Admin para habilitar este fluxo.

## Validação

- **25 novos testes unitários**: ausência, seleção desativada, configuração inválida,
  vínculo de cliente, instalação no startup, duplicidade, encerramento/reinício,
  mesma app pela entrada administrativa, importação/ambiente sem ativação e webhook.
- Suíte Backend: **1568 testes e 52 subtestes aprovados**, zero falhas na execução
  final. 281 cenários Emulator desmarcados nessa execução; aviso preexistente TestClient.
- **30 testes Emulator aprovados**, incluindo 12 novos sobre factories reais,
  startup/reinício, cliente consultável, corte, ausência/config inválida, falhas e
  estados protegidos; 18 regressões dos PASSOS 93–95. Provedores sempre fake.
- Na primeira execução unitária, uma asserção nova esperava cliente novo, mas a
  identidade por e-mail corretamente reutilizou o existente. Ajustado somente o
  teste; a regra comercial foi preservada. Nenhuma falha de produção identificada.
- Emulator loopback demo com credenciais anônimas, outbox em namespace UUID de
  testes e limpeza exata; não seleciona/altera pendências do usuário no Chrome.
- `git diff --check` sem problemas. Nenhum envio real, credencial real, publicação,
  alteração de infraestrutura ou PASSO 97.
