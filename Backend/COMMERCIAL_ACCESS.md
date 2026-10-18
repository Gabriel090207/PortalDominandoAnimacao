# PASSO 70 — Cancelamento imediato e vencimento

## Regra atual

Acesso exige conta enabled, ativação active, direito concedido dentro do período e
assinatura vinculada active. O fim do período é exclusivo: now == valid_until nega.
O relógio é consciente de fuso e fornecido pelo Backend; não há rotina agendada nova.
O cancelamento preserva o período registrado como histórico, mas deixa de autorizá-lo
imediatamente em uma nova verificação com dados persistidos atuais.

Antes, can_access_portal recebia apenas Entitlement e ignorava a assinatura. Agora
exige PortalEntitlement: projeção em memória com purchase_id, subscription_id,
subscription_status e fim de validade obrigatório. Não é documento novo, migração ou
campo gravado no Firestore. Entitlement sem evidência de assinatura falha fechado.
A regra pura não faz RPC: os consumidores devem fornecer fatos resolvidos do Backend,
frescos por decisão, nunca dados do navegador ou uma projeção em cache de sessão.

## Vínculos e consulta compartilhada

O resolvedor existente em admin_access_eligibility lê candidatos de purchases por
user_id, status active e período corrente, em páginas de **um documento**, usando
cursor de snapshot (sem offset/scan global). Para cada candidato lê pontualmente:

- entitlement pelo digest existente de purchase_id + portal;
- assinatura pelo subscription_id da compra.

Valida schemas, usuário, compra, períodos, produto, oferta, escopo, intervalo mensal e
ID canônico da assinatura derivado do sale_id. Um registro ausente ou vínculo divergente
não concede acesso. Status desconhecido, corrupção ou falha de I/O propagam como erro
para o chamador sanitizar; não são permissão nem sucesso. Candidato cancelado/inválido
não veta outra compra realmente elegível do usuário: o cursor permite examinar a próxima.
A paginação é indexada e restrita aos candidatos comerciais atuais do cliente; o custo
pode crescer com a quantidade desses candidatos, não com todos os usuários/histórico.
O Emulator valida o cursor real do SDK; disponibilidade/custo de índices de produção
não foram verificados nesta etapa e precisam de revisão antes da publicação.

O estado atual do produto permite vendas distintas (sale_id diferentes) do mesmo
produto/plano e cliente. Isso não adiciona suporte a múltiplos produtos ou planos.
Não se usa a mera existência de algum cancelamento histórico como veto global.

## Ativação, retomada e suspensão

Ativação e retomada continuam chamando a mesma elegibilidade dentro da própria
transação, antes de qualquer escrita administrativa. Ambas recebem 409 quando só
existem candidatos cancelados/inválidos. Falha de infraestrutura/dado corrompido
continua 503 sanitizado. A assinatura passa a integrar o conjunto lido na transação,
permitindo revalidação em caso de mudança concorrente antes do commit.

Already_active permanece um no-op sem concessão comercial: não altera o usuário nem
promete acesso. Suspensão continua independente de compra/assinatura, sem alterações.
Compra/renovação não retiram pending ou suspended; conta blocked continua negada.

O Backend ainda não tem endpoints protegidos do portal dos membros implementados:
esta etapa corrige a regra interna e os consumidores reais de ativação/retomada.
Rotas futuras deverão resolver fatos frescos e aplicar can_access_portal; não há
promessa de invalidação de uma futura sessão de membros que ainda não existe.

## Webhooks e histórico

Nenhum código de webhook foi alterado. SUBSCRIPTION_CANCELED continua transacional,
idempotente, autenticado e com proveniência, mudando somente a assinatura e seu recibo.
Usuários, compras, entitlements, activation_status e account_status são preservados.

Uma renovação inédita da assinatura canceled continua review_required e não gera
novo direito. Replay comprovado de evento já aplicado não restaura status posteriores.
Um novo sale_id pode originar outra assinatura válida pelas regras já existentes.
O contrato atual não permite reabrir a mesma assinatura cancelada por uma cobrança
tardia; isso foi preservado, sem inventar distinção de reativação financeira.

Reembolso e chargeback permanecem apenas registrados para revisão, como antes.
**Sua política de revogação continua pendente do PASSO 71**: esta mudança não resolve
os riscos de acesso anteriormente identificados para esses dois eventos.

## Compatibilidade e testes

Legados sem vínculos/documentos comerciais verificáveis não autorizam acesso, sem
reparo automático. O modelo de armazenamento e todos os documentos existentes são
preservados. O consumidor de can_access_portal precisa fornecer PortalEntitlement,
não um Entitlement isolado. Todos os consumidores existentes foram atualizados.

Fixtures administrativas agora incluem assinatura real coerente com compra/direito.
O teste antigo que permitia acesso durante período pago após cancelamento foi alterado
explicitamente para a nova decisão do usuário; não foi removido ou enfraquecido.
Testes cobrem cancelamento antes da expiração, limites temporais, renovação, restrições
administrativas, histórico preservado, vínculo ausente/divergente, falha de infraestrutura,
segunda assinatura válida e cursor real. Nenhum dado ou serviço de produção é usado.

## Resultado da validação

- Suíte unitária final: **1.213 aprovados e 52 subtestes aprovados** (18 casos novos).
- Regressão final no Firestore Emulator: **112 aprovados** (10 casos novos).
- Reexecução específica dos dez cenários novos: 10 aprovados.
- git diff --check e comparação de integridade aprovados. Admin/, Frontend/,
  app.main, parser/webhook Kirvano e repositório de suspensão não foram alterados.
- A primeira regressão teve 109 aprovações e uma falha no teste preexistente
  test_concurrent_restriction_never_reactivated[suspend], com
  CustomerSuspensionUnavailable. Três repetições isoladas e a regressão completa
  posterior passaram. A causa original não foi confirmada e a intermitência não
  foi considerada resolvida. Não se alterou a implementação de suspensão nem seu
  limite de cinco tentativas para mascarar a falha.
- O teste histórico de acesso após cancelamento mudou de expectativa por decisão
  explícita do PASSO 70; é distinto da falha concorrente acima.
- Permanece o aviso preexistente Starlette/httpx, sem instalar dependências.

Todos os testes de integração usaram localhost e demo-dominando-animacao-test com
AnonymousCredentials e guardas existentes. Nada foi consultado ou escrito em produção,
nenhum router foi publicado e nenhum documento real foi migrado ou apagado.
