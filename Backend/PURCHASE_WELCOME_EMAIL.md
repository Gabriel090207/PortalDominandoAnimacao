# PASSO 93 — compra aprovada e intenção de boas-vindas

Continuação: o [PASSO 94](PURCHASE_WELCOME_DISPATCH.md) prepara adapter, reserva,
snapshot e resultados, sem habilitar gatilho ou envio real. As descrições abaixo
registram o escopo original do PASSO 93.

## Fluxo confirmado e preservado

`POST /webhooks/kirvano` valida um único `security-token`, JSON e limite de corpo
antes do processamento. O segredo continua fora de logs. O serviço classifica o
payload pelo contrato comercial existente: SALE_APPROVED elegível, APPROVED,
recorrência mensal, produto/oferta autorizados, e-mail válido, cobrança e período
válidos. Nem toda venda Kirvano é automaticamente elegível neste portal.

O cadastro automático já existia: identidade HMAC do e-mail normalizado aponta
para um `user_id` estável; uma transação grava inbox/variante, usuário, identidade,
assinatura, compra e direito comercial. E-mail usa a normalização compartilhada,
sem DNS. Uma nova compra com o mesmo e-mail reutiliza o usuário. Estados existentes
não são restaurados por reenvios. A compra aponta para `user_id` e `subscription_id`;
seu ID determinístico deriva de escopo, venda e número da cobrança.

Usuário novo permanece `account_status=enabled`, `activation_status=pending`.
Direito comercial persistido não dispensa ativação manual nem as outras regras de
acesso. A lista Admin lê `users` por ID com paginação até 50; pesquisa faz igualdade
no e-mail normalizado, limitada a dois resultados para detectar ambiguidade. Não há
filtro que esconda clientes pendentes. Não foram alterados DTOs, lista ou visual Admin.

Antes desta etapa, nome não era persistido. Agora `customer.name`, quando disponível,
é metadado opcional: texto não vazio até 200 caracteres, sem controles Unicode.
Guarda-se como `users.display_name` no cadastro ou quando falta em um usuário
reutilizado por uma nova aprovação. Não sobrescreve nome existente; reenvio e
renovação não mudam o nome. A API Admin atual não projeta esse campo.
Não é identidade verificada nem muda fingerprints, IDs ou critérios comerciais.
HTML escapa esse valor antes de exibir. Nome ausente/inadequado usa saudação genérica.
A documentação oficial mostra `customer.name` em exemplos de webhook, mas não
comprova que sempre estará presente numa aprovação; a implementação não o exige:
https://help.kirvano.com/hc/central-de-ajuda/articles/1775656489-ex

## Intenção atômica, não envio

Reutiliza a coleção já declarada `transactional_emails`. A primeira criação de
uma compra elegível SALE_APPROVED adiciona um `create` à mesma transação comercial.
Não há chamada de provedor dentro ou depois do webhook.

ID: SHA-256 de uma tupla versionada contendo propósito e `purchase_id`. Campos:
`schema_version`, `kind=purchase_welcome`, `template_version`, `status=pending`,
`purchase_id`, `user_id`, `origin_event_id`, `recipient` normalizado,
`customer_name` opcional e `created_at` server timestamp. Sem senha, token,
chave de API, payload inteiro ou dados financeiros. `WelcomeEmailIntent` define o
contrato de leitura. Contém PII mínima; aplicar as mesmas restrições de acesso,
retenção e cuidado com backups das coleções de clientes. Não logar documentos.

Todos os reads precedem os writes. A intenção usa `create`, não sobrescrita.
Falha da transação não deixa intenção/compra/usuário parciais. Reenvio comprovado
não altera intenção ou data. Intenção preexistente sem compra nova é inconsistência
segura: aborta, não sobrescreve. Novas aprovações de outras compras podem criar
outra intenção, inclusive para o mesmo cliente, conforme o escopo por compra.

SUBSCRIPTION_RENEWED, SUBSCRIPTION_CANCELED, SALE_REFUNDED, SALE_CHARGEBACK,
eventos inválidos/revisão e rejeição de security-token não geram novas intenções.
Compras anteriores sem intenção não são retroativamente preenchidas pelo reenvio.
Essa recuperação histórica exigiria decisão explícita, não faz parte deste passo.

Incerteza de commit: consultar internamente compra, aplicação do evento e intenção
pelo ID determinístico antes de decidir como recuperar. Um retry comercial com
commit efetivo continua idempotente; se não houve commit, uma transação futura pode
criar o conjunto. Ausência de confirmação não significa ausência de gravação.
Não remover intenção para forçar nova notificação. A semântica de resposta do
webhook não mudou (200 recebido/revisão, 401 token, 503 falha de persistência).
Nova aprovação acrescenta uma leitura e uma escrita de intenção; reenvio comprovado
retorna antes dessa leitura adicional. Não há varredura de outbox nem novo índice
exigido por esta preparação.

## Conteúdo e porta de envio

`render_purchase_welcome` é puro e exige um intent válido e `WelcomeEmailContact`.
Produz subject, HTML responsivo em tabelas/estilos inline e texto puro. Paleta:
#050913, #141b2d, #00e0ff, #33e8ff, branco e #a0b3d0. Não depende de imagens remotas,
JavaScript, CSS externo ou tipografia externa. Hover e media query são melhorias
opcionais; o conteúdo funciona sem elas. Compatibilidade visual real em Gmail,
Outlook e celulares ainda precisa ser homologada.

Explica compra aprovada, boas-vindas e liberação manual. Orienta informar e-mail da
compra no WhatsApp, mas NÃO coloca esse e-mail, nome ou identificadores na URL.
Não promete acesso automático nem inclui senha ou código de login.

Contato: passar explicitamente a URL oficial `https://wa.me/<numero-internacional>`.
Aceita apenas esse host/caminho numérico, sem query, fragmento ou redirecionador.
Acrescenta mensagem fixa de solicitação, codificada, sem dados do comprador.
Sem contato válido, erro sanitizado, sem link falso. Não foi criado telefone real
nem uma variável de ambiente obrigatória no webhook. A futura composição do envio
poderá carregar uma configuração `PURCHASE_WELCOME_WHATSAPP_URL`, ainda não ativada.

`WelcomeEmailProvider` é somente um Protocol, sem implementação real ou dispatcher.
Nos testes, só um fake recebe o conteúdo e ID idempotente; não altera `pending`.
Renderização, registro transacional e provedor ficam separados. Importar os módulos
não lê credenciais, não envia mensagens e não cria cliente HTTP.

## Resend — preparação futura

Documentação oficial consultada nesta etapa:
- https://resend.com/docs/api-reference/emails/send-email
- https://resend.com/docs/dashboard/emails/idempotency-keys

A API aceita remetente, destinatário, assunto, HTML e texto puro; o retorno de ID
é aceitação pelo provedor, não comprovação de entrega na caixa de entrada.
`Idempotency-Key` permite repetir o mesmo payload sem reenvio dentro de **24 horas**.
Logo, não garante exactly-once indefinido e não substitui estado durável local.

Para um primeiro envio autorizado faltam: chave Resend guardada no servidor,
remetente/domínio de envio verificados conforme a documentação do provedor,
contato WhatsApp oficial, destinatário controlado, adapter e execução interna
explicitamente autorizada. Nomes propostos `RESEND_API_KEY` e
`PURCHASE_WELCOME_FROM` são apenas documentação; não foram configurados/carregados.
Não deve haver chave no frontend ou no Git.

Antes de ativar envio, definir claim transacional exclusivo entre instâncias,
snapshot imutável de destinatário/remetente/HTML/texto e chave idempotente estável,
estados de aceitação/resultado incerto, registro do ID Resend, limites de retentativa
e reconciliação. A requisição externa deve ocorrer FORA da transação Firestore.
Timeout após possível aceitação exige reconciliação; não reenviar cegamente após
24h ou marcar como enviado antes da confirmação. O modelo atual cobre somente
intenção pendente, não simula essas garantias ainda não implementadas.

Opção mais simples sem nova hospedagem: uma ferramenta interna no Backend existente
para despachar um lote limitado mediante execução autorizada, mantendo a outbox
como fonte durável. Automação poderá ser avaliada depois. FastAPI BackgroundTasks
sozinho não é fila durável e não garante execução após encerramento do processo.
Não foram criados worker externo, agendador, fila paga ou retentativas automáticas.

## Validação

- 100 testes comerciais/transacionais existentes aprovados após a mudança.
- 30 novos testes unitários: primeira compra, atomicidade antes de commit,
  duplicidade, mesmo e-mail, compra histórica, eventos excluídos, nome opcional,
  HTML escapado, texto puro, contato, fake, privacidade e falha HTTP sanitizada.
- Suíte Backend: **1461 testes e 52 subtestes aprovados**, sem falhas; 254 testes
  Emulator desmarcados nessa execução. Um aviso preexistente do TestClient.
- 3 testes próprios no Emulator: compra pesquisável/listada e pendente, commit
  realmente rejeitado sem efeitos parciais e duplicidade concorrente real.
  **3 aprovados** na execução final. A primeira execução teve 1 falha no teste
  (limit=100 contrário ao máximo 50); corrigido apenas para usar contrato existente.
- Emulator fixado em loopback/projeto demo, credenciais anônimas, UUIDs próprios,
  limpeza somente dos documentos criados; limpeza global e Firebase real proibidos.
- `git diff --check` sem problemas.

Nenhum e-mail real, dado real, configuração externa, publicação ou PASSO 94.
