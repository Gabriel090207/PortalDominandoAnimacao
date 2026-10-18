# Suspensão manual de acesso — PASSO 64

## Estados e transição

O domínio existente possui `account_status = enabled | blocked` e
`activation_status = pending | active | suspended`. Suspensão restringe a ativação;
bloqueio restringe a conta. Não são operações equivalentes.

Somente `enabled/active -> enabled/suspended` é permitido. `enabled/suspended`
retorna `already_suspended` sem nova escrita/auditoria. Pendente e conta bloqueada
retornam conflito, inclusive quando uma conta bloqueada já está suspensa.
A suspensão não depende de compra vigente. Somente `activation_status` é atualizado,
com `transaction.update`, preservando campos desconhecidos.

`can_access_portal` já exige conta habilitada, ativação ativa e entitlement válido
vinculado ao cliente. Não foi alterado: suspenso não acessa mesmo com direito válido.
Isso é uma regra interna; as futuras rotas do portal precisarão consultá-la.

## Contrato HTTP isolado

`POST /admin/customers/{customer_id}/suspend`

Entrada única: `{"confirm_suspension":true}`. Sem query string, até 4096 bytes,
JSON estrito sem duplicações/campos extras. Não existe operação por GET.

Resposta confirmada:
`{"customer_id":"customer-a","activation_status":"suspended","result":"suspended"}`.
Repetição confirmada troca somente `result` por `already_suspended`.

Reutiliza sessão, `suspend_customer`, Origin, CSRF `X-Admin-Request: 1`, JSON e
`Cache-Control: no-store`. Owner e operator seguem a matriz existente.
O ator vem exclusivamente da sessão validada; seu status, papel e auth_version
são relidos transacionalmente. Firestore síncrono executa em threadpool.

Erros: 400 contrato/ID inválido, 413 tamanho, 415 mídia, 401 sessão,
403 permissão/Origin/CSRF, 404 inexistente, 409 estado incompatível,
503 operação não confirmada. Detalhes internos não são expostos.

O router continua fora de `app.main`; nada foi publicado. Não há botão novo.

## Persistência, auditoria e concorrência

Reutiliza o cliente compartilhado da composição e a coleção `activation_audit`.
O contrato específico da auditoria usa o mesmo formato da ativação, discriminado
por `operation=suspend_customer`, sem alterar o contrato da auditoria de ativação.
Registra schema_version, admin_id, customer_id, estado anterior/posterior,
confirmação humana e instante UTC. Nenhum dado financeiro ou segredo é registrado.
A escrita do usuário e a criação da auditoria são atômicas. Referência de auditoria
estável entre tentativas; retorno idempotente não gera auditoria adicional.

São duas leituras de documento e duas escritas na transição, além da validação da
sessão HTTP. Não há consulta comercial, novo índice, coleção ou dependência.
Cada tentativa transacional pode repetir leituras; contenção aumenta custo/latência.

Usa limite explícito de **cinco tentativas nativas**, o padrão do SDK, sem retry
externo. A suspensão tem duas leituras diretas e não executa as consultas comerciais
da ativação. Não há evidência para copiar oito; a ativação mantém oito inalterado.
O SDK instalado repete Aborted no commit; erros no callback não recebem essa mesma
política. Exaustão (inclusive ValueError causado por Aborted) resulta em 503.
Timeout/erro com commit incerto não é repetido externamente nem anunciado como sucesso.
503 pode ocorrer após commit: consultar estado e auditoria por acesso confiável.
Concorrência é serializada/revalidada pelo Firestore; não se presume vencedor.
Cinco tentativas não garantem progresso sob toda contenção possível.

## Independência da Kirvano

SALE_APPROVED e SUBSCRIPTION_RENEWED criam dados comerciais e criam usuário pendente
somente quando ausente; não substituem a restrição de usuário existente.
SUBSCRIPTION_CANCELED altera assinatura, sem remover a suspensão. Testes reais no
emulador verificam esses três fluxos após suspensão. Nenhum webhook foi alterado.
Compras, assinatura, pagamentos e entitlements não são modificados pela suspensão.

## Retomada futura (não implementada)

A representação permite uma operação separada `suspended -> active`. Ela deverá
exigir permissão resume_customer, confirmação, auditoria e condições comerciais
válidas (compra e entitlement), revalidadas atomicamente; conta bloqueada não deve
ser desbloqueada implicitamente. Nunca aceitar pending nessa operação.
Suspender pending é rejeitado justamente para impedir contorno da ativação inicial.
Dados antigos já suspensos podem não ter proveniência: uma implementação futura
precisará definir como comprovar ativação inicial legítima por histórico confiável,
sem presumir que todo estado suspended foi produzido por este endpoint.
Não há retomada, bloqueio ou desbloqueio neste passo.

## Validação e isolamento

Testes usam dados sintéticos; integração exige host 127.0.0.1:8080, projeto
`demo-dominando-animacao-test`, AnonymousCredentials e guardas existentes antes da
construção/limpeza do cliente. Nenhuma operação usa Firebase de produção.
Injeções de falha distinguem pré-commit, auditoria, commit abortado confirmado,
exaustão e perda simulada de confirmação após commit real. A última simula um
resultado incerto; não reproduz uma falha de rede real nem promete ausência de commit.

Resultado da validação do passo: 1.086 testes unitários e 52 subtestes aprovados;
74 testes no emulador aprovados (13 novos de suspensão e regressão administrativa/
Kirvano). Os 43 novos casos unitários cobrem os contratos da suspensão. Duas
expectativas históricas de rota inexistente foram atualizadas: agora exigem CSRF
na rota de suspensão e 404 para cliente ausente com requisição autorizada, mantendo
resume/block/unblock inexistentes. Nenhuma falha final. Aviso preexistente de
compatibilidade/depreciação Starlette/httpx; sem instalação de dependências.
