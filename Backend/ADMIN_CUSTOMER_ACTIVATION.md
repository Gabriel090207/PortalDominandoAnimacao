# Ativação manual — passo 58

POST /admin/customers/{customer_id}/activate, na composição administrativa
isolada. Não registrado em app.main nem publicado. Nenhuma UI foi modificada.

## Contrato e autoridade

Exige sessão válida, Origin autorizado, X-Admin-Request: 1, application/json e
activate_customer, já presente em owner e operator. Não altera a matriz. O actor
é exclusivamente o Admin devolvido pela dependência de sessão/autorização real.

Corpo obrigatório, único, limitado a 4096 bytes:

```json
{"confirm_activation":true}
```

A decisão humana é explícita; não prova situação financeira em tempo real nem
substitui as validações do servidor. JSON malformado, chaves duplicadas, campos
extras, confirmação false/número/string, query parameters e IDs inválidos são
rejeitados. Não recebe admin_id, prova de compra, estado ou customer_id no corpo.

200 após commit confirmado:

```json
{"customer_id":"synthetic-customer","activation_status":"active","result":"activated"}
```

Se o cliente já está active e enabled, com administrador ainda elegível, retorna
200 com result=already_active, sem escrever nem criar nova auditoria. Isso é uma
observação idempotente do estado, não afirma autoria da ativação anterior, nova
ativação ou direito atual de acesso. Não exige criar auditoria retroativa para
cadastros já ativos. Conta blocked ou ativação suspended resultam em 409, mesmo
se o pedido pretendia reativá-las. Não existem novos estados.

400 corpo/query/ID inválido, 413 corpo excessivo, 415 Content-Type inválido,
401 sessão ausente/inválida, 403 Origin/CSRF/permissão, 404 cliente inexistente,
409 pré-condições de ativação não atendidas, 503 escrita não confirmada/falha
interna. Respostas sanitizadas e no-store pelo router. GET não ativa (405).
Caminhos sem correspondência de rota podem ter 404 fora do tratamento no-store,
como nos demais endpoints atuais. Não há logs de inputs ou detalhes internos.

## Regras reais preservadas

O webhook elegível cria usuário enabled/pending, compra active e entitlement
granted; isso sozinho não permite acesso. Compras usam user_id e subscription_id;
a identidade da compra deriva de escopo/sale_id/charge_number. Renovações elegíveis
podem adicionar compra/direito da mesma assinatura. Reenvios comprovados preservam
os efeitos; cancelamento não apaga os direitos existentes.

Para pending, a transação:

1. Lê e valida users/{id}, com a mesma projeção cadastral existente.
2. Exige account_status=enabled e activation_status=pending.
3. Relê o administrador e exige enabled, mesmo role e auth_version da autoridade
   validada. Isso não modifica autenticação nem substitui a validação de sessão.
4. Consulta purchases por user_id exato, status active, valid_from <= agora e
   valid_until > agora, limit(1). Não confunde mera existência com aprovação.
5. Lê o entitlement correspondente pelo digest já utilizado na integração:
   kirvano-entitlement/version=1/purchase_id/resource=portal.
6. Valida os contratos comerciais existentes, user_id, purchase_id e igualdade
   dos períodos. Reutiliza can_access_portal com apenas a ativação proposta como
   active: exige enabled, direito granted/portal/vigente e mesmo usuário.
7. Atualiza exclusivamente activation_status e cria a auditoria atomicamente.

Não lê/modifica assinatura para impor uma nova regra. can_access_portal hoje não
exige status da assinatura: depende de conta, ativação e entitlement vigente.
Cancelamento pode preservar um direito até o fim do período. Não foi criada uma
regra adicional que negue esse direito automaticamente. Não cria/estende direitos,
não muda compra, assinatura, conta, e-mail ou campos desconhecidos do cadastro.

## Transação, auditoria e concorrência

AdminActivationRepository usa o cliente injetado existente e firestore.transactional.
Todas as leituras precedem as escritas. Os documentos lidos participam da
verificação de concorrência do Firestore. A tentativa perdedora reavalia o estado;
um usuário já ativo não gera outra transição ou auditoria. O ID da auditoria é
aleatório, create-only, estável entre tentativas SDK da mesma chamada.

Apenas o SDK realiza suas retentativas normais de contenção. Não existe retry
externo após timeout, Aborted/esgotamento ou resultado incerto. O resultado só
é devolvido após o decorador confirmar o commit. Falhas, inclusive perda simulada
da confirmação depois de commit, geram 503. O operador deve verificar o estado por
acesso confiável antes de insistir; repetir não deve ser interpretado como prova
de que a tentativa anterior não gravou.

Coleção activation_audit já declarada, agora com contrato durável mínimo:
schema_version, admin_id, customer_id, operation=activate_customer,
previous_activation_status=pending, activation_status=active,
human_confirmation=true e occurred_at. O horário vem do relógio UTC do servidor
(reavaliado na tentativa), não do navegador; não é um timestamp exato de commit.
Ativação e auditoria estão no mesmo commit. Falha de create da auditoria antes
do commit não deixa usuário ativo. Não contém e-mail, token, cookie, hash,
payload, segredo ou dados de pagamento. Acesso/IAM e retenção operacionais da
coleção exigem a mesma administração segura das demais coleções backend.

A sessão é validada na dependência antes da transação; não é adicionada uma nova
transação que prenda o documento de sessão à operação. Uma revogação que ocorra
após a autorização inicial não cancela magicamente uma requisição já em curso.
O recheck do administrador limita mudanças de status/role/auth_version concorrentes.

## Performance, índices e limites

Para transição efetiva, leituras habituais: usuário + administrador revalidado +
no máximo uma compra + um entitlement, além da validação prévia da sessão/admin.
Duas escritas: update parcial de usuário e create de auditoria. Retentativas
podem aumentar custo. Operações Firestore rodam fora do event loop, em threadpool;
leituras usam timeout 10s. Não há nova inicialização Firebase/import-time I/O.

A consulta com igualdades e duas faixas pode exigir índice composto de purchases:
user_id ASC, status ASC, valid_from ASC, valid_until ASC (o índice sugerido pelo
Firestore para a query real deve ser conferido antes da publicação). Não cria
índices nem migra dados nesta etapa. O emulador não comprova índices de produção.
Falta de índice resulta em 503, sem escrita. Consultas com múltiplas faixas também
podem cobrar entradas de índice, além de documentos; medir no ambiente autorizado.

A seleção é conservadora e limitada a um registro vigente: se a compra selecionada
tiver direito ausente/revogado/inconsistente, retorna conflito, sem tentar varrer
ou reparar os demais registros. Mesmo que outro registro pudesse ser elegível,
a inconsistência exige revisão interna, não concessão automática. Não há garantia
de encontrar toda combinação possível de dados legados ou inconsistentes.

O relógio é conferido durante a transação, não equivale a uma garantia de vigência
até depois do commit. O portal continua reavaliando o direito no instante de
acesso; uma expiração posterior nunca é prorrogada pela ativação.

## Conferência humana e pendências

Reembolso e chargeback completos continuam pendentes. Um registro active pode não
refletir a situação financeira atual. Confirmar conscientemente a ação pode exigir
conferência direta na Kirvano; não há consulta externa nem validação financeira
automática. O endpoint não garante que o cliente conseguirá acessar: o portal
continua aplicando suas condições no momento do acesso.

Antes da publicação: revisar índices/IAM, confirmação operacional da origem Render,
configuração HTTP de produção e futura UI de confirmação explícita. Nenhuma dessas
configurações foi alterada, e não foi implementada suspensão/bloqueio/retomada.

## Testes

46 novos testes unitários: autorização, corpo/protocolo, estados, vínculos,
validade, preservação de campos/comércio, auditoria/idempotência, falhas pré-commit,
resultado incerto e Aborted/ValueError associado sem retry externo. Os testes
pré-existentes continuam verificando compra aprovada + pending nega acesso.

5 novos cenários no emulador: owner/operator, concorrência com uma única transição
e auditoria, falha de auditoria antes do commit e perda simulada de confirmação
após commit. No teste concorrente, esgotamento SDK é aceito apenas como resultado
não confirmado específico, nunca como sucesso; não se presume qual operação vence.
O cenário de perda de confirmação é injeção determinística após commit real no
emulador, não reprodução de uma falha de rede real em produção.

A suíte administrativa relevante no emulador teve 15 cenários aprovados. Testes
usam exclusivamente localhost/projeto demo/credenciais anônimas e guardas existentes.
Nenhum acesso ou alteração em produção; Admin/ e Frontend/ preservados.
