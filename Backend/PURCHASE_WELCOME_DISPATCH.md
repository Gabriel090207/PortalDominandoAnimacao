# PASSO 94 — adapter Resend e despacho controlado

Continuação: o [PASSO 95](PURCHASE_WELCOME_TRIGGER.md) conecta o gatilho opt-in e
prepara recuperação limitada. As descrições abaixo registram o escopo do PASSO 94.

Preparação interna, sem ativação, publicação, credencial real ou envio real.
Não altera compra, cliente, assinatura, entitlement, deduplicação ou resposta do
webhook. Não implementa endpoint, cron, fila externa ou disparo em BackgroundTasks.

## Contratos e composição

A intenção `WelcomeEmailIntent` do PASSO 93 continua representando uma intenção
pendente. `WelcomeDispatchRecord` a estende com estados e metadados de despacho,
sem duplicar o contrato da compra ou o template. Documentos pending existentes
continuam válidos sem migração. Não modifica a criação transacional Kirvano.

`create_purchase_welcome_dispatch(firestore_client=..., config=..., transport=...)`
compõe o repositório, adapter e serviço. É chamada interna explícita, não registrada
em `app.main`, `admin_server`, webhook ou tarefas de startup. Recebe o cliente
Firestore já existente, sem carregar Firebase. Não há transporte real padrão:
esta etapa só o executou com `httpx.MockTransport`.

HTTPX já está disponível nas dependências do Firebase Admin; nenhuma instalação
ou novo SDK foi necessária. Em uma composição futura autorizada, o transporte
real precisará ser fornecido explicitamente, com TLS normal, sem retries ocultos.
O adapter mantém seu cliente HTTP para um lote e oferece `provider.close()`;
o executor futuro deve fechá-lo em `finally`. Não fechar o cliente Firestore
compartilhado do webhook enquanto ele estiver em uso.

## Configuração explícita e desabilitada por padrão

`load_purchase_welcome_config()` somente habilita a funcionalidade quando o
**processo** contém `PURCHASE_WELCOME_SEND_ENABLED=true`. Sem seleção ou com
`false`, retorna `None` antes de ler arquivo. Valores diferentes são inválidos.
Não chama esse loader no webhook. Configuração ausente/inválida não impede compra.

Quando selecionado, exige:

| Nome | Validação |
| --- | --- |
| `RESEND_API_KEY` | SecretStr; formato ASCII de chave `re_...`, sem espaços/controles |
| `PURCHASE_WELCOME_FROM` | Remetente oficial como e-mail simples canônico, sem nome de exibição ou headers |
| `PURCHASE_WELCOME_WHATSAPP_URL` | Contrato existente `https://wa.me/<numero-internacional>`, sem query ou fragmento |

O loader usa valores do processo prioritários aos de `Backend/.env`, sem
interpolação, alteração do ambiente ou fallback sobre valor inválido. `.env`
sozinho não habilita envio. Não gera chaves nem revela valores em exceções/repr.
Verificação real do domínio remetente pelo Resend é requisito operacional, não
uma garantia oferecida pelo validador sintático. Nenhuma configuração foi alterada.

## Reserva e snapshot

`dispatch(intent_id)` aceita somente ID interno determinístico, não recebe e-mail,
HTML ou remetente do navegador. A transação de reserva:

1. Lê e valida o documento de `transactional_emails` e seu vínculo determinístico.
2. Prossegue somente se `pending`. Ausente, in_progress, accepted ou requires_review
   não podem adquirir uma nova reserva; o serviço retorna `not_dispatched`.
3. Confere compra persistida e ativa, usuário/e-mail, aplicação comercial e variante
   de origem `SALE_APPROVED`. Referências ausentes/divergentes falham sem HTTP.
4. Renderiza o template existente como operação pura e guarda snapshot completo
   de remetente, destinatário, assunto, HTML e texto, digest SHA-256, versão do
   template, chave idempotente, `reserved_at` e `attempt_id` aleatório de 256 bits.
5. Muda para `in_progress` e confirma a transação ANTES de chamar HTTP.

Todos os reads precedem os writes; o callback não realiza efeitos externos e pode
ser repetido pelo SDK. Apenas a invocação que recebe a reserva confirmada prossegue.
Falha/resultado incerto da reserva bloqueia HTTP, mesmo se o commit tiver ocorrido.
Não há retentativa externa adicional sobre reserva ou envio. Contenção pode causar
indisponibilidade sanitizada, nunca licença para enviar sem reserva.

O payload do HTTP usa exclusivamente o snapshot confirmado, inclusive se houver
mudança de template, remetente ou contato após a reserva. Um novo processo não
reconstrói nem substitui esse snapshot. Seu digest é validado na leitura. O digest
não é assinatura contra alguém com permissão de escrita no banco: IAM/regras devem
restringir documentos, snapshots e metadados ao Backend confiável.

Pending antigo, sem tentativa anterior, pode ter sua PRIMEIRA tentativa se seus
vínculos ainda forem válidos. A janela de 24h conta da requisição ao provedor, não
da criação da intenção. Não há campanha retroativa ou envio em lote automático.
A validade de acesso continua sendo responsabilidade das regras comerciais; esse
serviço não ativa, suspende, renova ou altera estados do cliente.

## Adapter e resultado

Envia exatamente `POST https://api.resend.com/emails`, com Authorization Bearer,
Idempotency-Key, `from`, `to`, `subject`, `html`, `text`. Destino não configurável,
sem redirect, proxies ambientais ou retries; timeout HTTP de 10 segundos por fase
do HTTPX (não é um prazo total de execução). Resposta lida com limite de 64 KiB,
JSON estrito sem chaves repetidas/constantes não finitas. ID de sucesso deve ter
formato UUID canônico. Não guarda resposta bruta, mensagem de erro livre ou segredo.

| Resultado observado | Estado final | Motivo sanitizado |
| --- | --- | --- |
| HTTP 200 com ID válido | accepted | accepted + provider_id |
| 400/404/405/422 JSON | requires_review | rejected |
| 401/403 JSON | requires_review | authentication |
| 429 JSON | requires_review | quota |
| 409 concurrent_idempotent_requests | requires_review | concurrent_request |
| Outro 409 | requires_review | idempotency_conflict |
| Timeout | requires_review | timeout |
| Falha de rede | requires_review | network |
| HTTP inesperado/5xx | requires_review | unknown_response |
| JSON/ID/resposta inválidos ou excessivos | requires_review | invalid_response |
| Falha interna inesperada | requires_review | internal_failure |

Se o corpo estiver inválido, registra `invalid_response`, sem presumir rejeição
mesmo que o status seja 4xx. `accepted` significa aceitação pelo provedor, não
entrega na caixa de entrada. Nenhum estado chamado delivered foi criado.

A finalização é uma segunda transação e exige mesmo attempt_id E status
in_progress. Resultado de outra tentativa ou finalização tardia não sobrescreve
estado final. Falha ao persistir sucesso retorna `WelcomeDispatchUnavailable`
sanitizado, não confirma o despacho nem tenta enviar de novo. O ID pode ficar só
no Resend se a escrita falhou: isso exige reconciliação operacional, não inventamos
uma confirmação local. Se a escrita confirmou mas o ACK se perdeu, a leitura futura
mostra accepted e continua impedindo novo envio.

## Idempotência e interrupção

Chave fixa `purchase-welcome/<intent_id SHA-256>`: 81 caracteres ASCII, derivada da
mesma compra, validada antes do HTTP. Nunca cria chave nova para contornar conflito.
A proteção durável é a reserva no Firestore, não a retenção do provedor.

Não há liberação automática de claims, nem mesmo em erro comprovado. In_progress,
accepted e requires_review não voltam a pending. Isso prioriza evitar duplicação;
uma falha antes do HTTP pode deixar uma mensagem não enviada aguardando revisão.
Não prometemos exactly-once entre Firestore e uma API externa.

`repository.review_interrupted(id, now=..., minimum_age=...)` é operação interna
explícita, sem gatilho. Após o limiar informado (padrão 10 minutos, somente para
triagem), muda uma reserva interrompida para requires_review/interrupted. Não é
lease, não autoriza reenvio e não comprova que a requisição parou. Um processo
pausado ainda pode retomar a sua única chamada; seu resultado tardio não substitui
uma decisão já em revisão. Não há segunda reserva concorrente possível.

Depois de timeout, falha de rede, processo morto ou falha de gravação, comparar
internamente estado/ID/tentativa/snapshot com o Resend por acesso autorizado.
Nenhum reconciliador ou comando de reset/reenvio foi implementado aqui. Após 24h,
não repetir cegamente: a deduplicação do provedor já pode ter expirado. Mesmo
rejeições/quota exigem decisão posterior; não existe retentativa automática agora.
Snapshots contêm PII mínima necessária ao e-mail e requerem acesso/retenção/backups
restritos; não devem aparecer em logs ou em interfaces públicas.

## Gatilho futuro e primeiro envio

Uma intenção pending não dispara nada por si só. O primeiro passo operacional
futuro é um executor interno de lote limitado no Backend Render existente, mediante
autorização, que selecione IDs pending e chame o serviço com configuração completa.
Para automação após publicação, ainda falta escolher e ativar um gatilho durável
para essa drenagem e revisão de reservas interrompidas no serviço existente.
Uma tarefa em memória pode sinalizar trabalho, mas não substitui reconsulta do
Firestore após reinício. Não há cron externo, nova hospedagem, Redis ou fila paga.

Antes do primeiro envio real: autorizar explicitamente a operação, verificar
remetente/domínio e chave Resend de envio, contato oficial, destinatário controlado,
TLS, acesso ao Firestore correto e procedimento de reconciliação. Configurar os
valores fora do Git e somente então compor um transporte real. Nenhuma dessas
operações foi executada nesta etapa; não há endpoint de disparo arbitrário.

## Documentação oficial consultada

- [Send Email](https://resend.com/docs/api-reference/emails/send-email): payload,
  API, ID e header idempotente.
- [Errors](https://resend.com/docs/api-reference/errors): validação, autenticação,
  quota, conflitos e falhas de serviço.
- [Idempotency Keys](https://resend.com/docs/dashboard/emails/idempotency-keys):
  mesma chave/payload, até 256 caracteres, retenção por 24h.

## Testes

Transporte exclusivamente `httpx.MockTransport`, segredos/e-mails fictícios,
Firebase real proibido. Unitários cobrem payload, configuração, snapshot, fencing,
perda de ACK, falhas antes/durante/depois do HTTP, resposta inválida, logs sanitizados,
pendência antiga e ausência de reenvio além de 24h. No Emulator, testes importam a
fixture não destrutiva do PASSO 93: loopback, projeto demo, credenciais anônimas,
UUIDs próprios e limpeza exata, nunca exclusão global.

Resultados finais: **54 novos testes unitários** de configuração/adapter/despacho
aprovados. Suíte Backend completa: **1515 testes e 52 subtestes aprovados**, zero
falhas; 257 testes Emulator desmarcados nessa execução. Há um aviso preexistente
de depreciação do TestClient. Emulator: **6 aprovados** (3 novos de despacho com
dois clientes independentes e 3 de regressão da compra/intenção). Nenhuma falha
encontrada nesta etapa. `git diff --check` sem problemas.
