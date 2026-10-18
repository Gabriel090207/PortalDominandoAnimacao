# Confirmação limitada de compra — passo 54

GET /admin/customers/{customer_id}/purchase-confirmation, no router administrativo
isolado já composto por compose_admin_http. Não registrado em app.main.

A utilização de read_customers nesta consulta foi expressamente autorizada para
owner e operator. A matriz permanece intacta. Ambos têm read_customers,
read_dashboard, read_audit e activate_customer; suspend_customer, resume_customer,
block_customer e unblock_customer continuam exclusivos de owner para revisão
posterior. Não houve ampliação de privilégios técnicos/provisionamento.

## Contrato

200, por exemplo:

```json
{
  "customer_id": "synthetic-customer",
  "approved_purchase_recorded": true,
  "current_payment_validity": "not_verified",
  "requires_kirvano_review": true
}
```

approved_purchase_recorded significa: foi encontrado um documento em purchases
com user_id exatamente igual ao ID solicitado e status ACTIVE (persistido como
active), validado pelo contrato comercial existente. Não significa aprovação em
tempo real, assinatura vigente, entitlement válido, ausência de reembolso ou
autorização para ativação. false significa ausência de registro correspondente
nesse estado; NÃO comprova que o cliente nunca pagou. Compras com pending,
canceled, expired, refunded ou chargeback não satisfazem a consulta. Falha de
infraestrutura/registro selecionado inválido produz 503, nunca false.

A validade atual permanece sempre not_verified; a conferência na Kirvano é
explicitamente necessária para confirmação comercial atual, sobretudo enquanto
SALE_REFUNDED e SALE_CHARGEBACK não têm tratamento comercial completo. A consulta
não chama essa API. Não agrega nem consulta assinatura/entitlement/evento.

## Modelo real e acesso manual

users/{id} é referenciado por purchases.user_id, sem associação por e-mail na
consulta. O webhook resolve a identidade pelo e-mail normalizado via identidade
HMAC persistida. purchase_id é um digest de escopo, sale_id e charge_number;
subscription_id é derivado do escopo e sale_id. SALE_APPROVED elegível cria compra
active, assinatura quando ausente e entitlement granted. SUBSCRIPTION_RENEWED
pode criar uma nova compra/entitlement da mesma assinatura, com vínculos
validados; reenvios comprovados não duplicam efeitos. SUBSCRIPTION_CANCELED
altera a assinatura preservando esses registros. Nem todo evento recebido vira
compra e uma compra não representa uma nova assinatura.

A compra contém user_id, subscription_id, charge_number, product_id, offer_id,
status, valid_from, valid_until, created_at e versões/proveniência internas.
Não há valor monetário nem nome comercial na compra. sale_id e interval estão
na assinatura; eventos possuem sua própria normalização/proveniência. Não se
expõem esses campos nesta resposta. O classificador atual aceita um produto,
uma oferta e frequência MONTHLY, sem modificar seus identificadores ou criar
catálogo. Isso não verifica a configuração externa atual da Kirvano.

O processamento de venda cria novo usuário enabled/pending; o entitlement não
altera activation_status. can_access_portal exige enabled + active + entitlement
portal vigente do mesmo usuário. O teste usa o processamento comercial real com
persistência sintética e demonstra que pending nega acesso mesmo com direito
vigente. Não implementa nem audita todos os futuros fluxos de ativação.

## Consulta e segurança

ID usa a validação existente. Uma leitura direta e projetada do usuário confirma
existência, sem repetir essa leitura. Ausência retorna 404 sem consultar compras.
A query em purchases aplica igualdade user_id + status, select dos campos exigidos
pelo validador comercial existente, limit(1), timeout 10s, sem offset/varredura/N+1.
Não precisa ordenar: qualquer registro elegível comprova a existência pretendida.
Não há paginação porque não é uma listagem. Nenhum campo do registro é retornado.

Estimativa usual: 1 leitura de usuário + até 1 documento de compra (consulta
vazia tem cobrança mínima), além das leituras de sessão/administrador (~2), ou
aproximadamente 4 leituras por consulta. Cliente inexistente não faz a query.
Retentativas/cobrança efetiva dependem do Firestore.

Os filtros de igualdade podem usar index merging dos índices single-field de
user_id e status mantidos automaticamente, se não houver isenções. Não se exige
ordenação/índice composto adicional nesta implementação. Índices de produção não
foram inspecionados; se estiverem desabilitados, deve-se revisar a configuração
antes da publicação. O emulador não comprova disponibilidade de índices em
produção. Nenhum índice foi criado ou alterado.

Session/Origin/read_customers são dependências existentes; Firestore roda em
threadpool. Erros 400/401/403/404/503 são sanitizados e as respostas geridas pelo
router usam no-store. Caminhos que não correspondem a nenhuma rota (ex. slash
codificado) podem gerar 404 fora desse tratamento, como nas rotas existentes.
Não há logs de dados comerciais, mutações, criação/renovação de sessões ou cookies.

## Validação e próximos passos

24 testes unitários novos; suíte unitária 913 aprovados e 52 subtests.
8 cenários relevantes no emulador aprovados (2 novos, owner/operator), verificando
filtros, múltiplas compras, isolamento por cliente, estados não aprovados, vazio,
404, regressão de listagem/ficha/sessão e igualdade de dados/update_time antes e
depois. Somente localhost/projeto demo/credenciais anônimas, com guardas existentes.
Há um aviso preexistente de depreciação Starlette/httpx.

Ativação manual exige etapa própria: transição validada de activation_status,
autorização activate_customer, auditoria identificando o administrador e critérios
comerciais expressamente aprovados. Esta resposta isolada não autoriza ativação.
Continuam pendentes publicação autorizada, validação operacional da origem Render,
e demais configurações HTTP de produção. Nada foi publicado ou acessado em produção.
