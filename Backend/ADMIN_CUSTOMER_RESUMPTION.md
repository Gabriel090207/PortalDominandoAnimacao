# PASSO 66 — Retomada manual de acesso

> Atualização PASSO 70: assinatura cancelada não sustenta acesso, mesmo durante o período anteriormente pago. Ativação e retomada verificam a assinatura vinculada. Consulte [COMMERCIAL_ACCESS.md](COMMERCIAL_ACCESS.md); as descrições do período pago abaixo refletem o comportamento histórico anterior quando divergirem.

## Diferença entre ativação e retomada

O domínio existente permanece inalterado: account_status enabled/blocked e
activation_status pending/active/suspended. A ativação inicial pending -> active
continua separada. A retomada só permite enabled/suspended -> enabled/active.
Somente activation_status é atualizado, sem substituir o documento do usuário.
Pending e blocked são conflitos; não há desbloqueio implícito.

## Evidência conservadora de proveniência

O estado suspended isolado e uma auditoria de suspensão isolada não comprovam
ativação inicial legítima. Para uma transição efetiva exigem-se, na própria transação:

1. Usuário habilitado e suspenso, validado pela projeção persistida existente.
2. Auditoria completa CustomerActivationAudit: activate_customer, pending -> active,
   confirmação humana true, schema 1, admin_id válido e customer_id correspondente.
3. Auditoria completa CustomerSuspensionAudit: suspend_customer, active -> suspended,
   com os mesmos requisitos de integridade e vinculação.
4. Cronologia created_at do usuário <= ativação <= suspensão <= agora UTC.
5. Compra e entitlement atualmente elegíveis, revalidados conforme abaixo.

As evidências são documentos reais da coleção activation_audit, produzidos pelos
mecanismos transacionais existentes. Nenhum default é usado para preencher campo
histórico ausente: exige-se o conjunto completo de campos e valores válidos.
Auditorias de outro cliente, incompletas, sem confirmação, com transição incompatível,
versão inválida ou cronologia inválida não autorizam retomada.

São duas queries de igualdade (customer_id + operation), cada uma limitada a um
resultado, sem varrer toda a coleção e sem ordenação ou índice novo implantado.
A evidência selecionada prova existência de ativação inicial e suspensão posterior;
não pretende reconstruir a última transição ou ordenar todo o histórico. Se o registro
selecionado for inconsistente, a operação falha conservadoramente, mesmo que haja
outros registros. Ciclos legítimos posteriores continuam usando a ativação inicial
original. O estado atual e o histórico são lidos sob a mesma transação.

O modelo confia na integridade dos registros internos do Backend, como a auditoria
existente; isto não é assinatura criptográfica nem verificação retroativa dos fatos
financeiros históricos. Auditoria de ativação comprova a decisão administrativa do
fluxo que exigia compra/direito válidos; compra/direito atuais são checados novamente.
Não se exige que o administrador histórico ainda esteja habilitado hoje.

Legados sem qualquer uma dessas evidências recebem 409. Não há fallback por e-mail,
mera existência de compra, papel owner ou estado suspended. Não há migração,
reconstrução/fabricação de auditoria ou reparo automático. Sua liberação exige decisão
futura separada e evidência confiável; resume não substitui a ativação inicial.

## Elegibilidade comercial compartilhada

A verificação antes contida na ativação foi extraída, sem alterar critérios, para
admin_access_eligibility.has_eligible_portal_access. Tanto ativação quanto retomada
consultam compra user_id correspondente, status active, valid_from <= agora e
valid_until > agora, com limite 1. Depois leem o entitlement por seu identificador
canônico existente, validam schema e vínculo user_id/purchase_id/período, e chamam
can_access_portal com o estado PROPOSTO active. Suspended não precisa passar pela
regra de acesso antes da transição. Dados corrompidos/erros de I/O não viram permissão.

Não existe regra nova baseada apenas no status da assinatura. Cancelamento Kirvano
preserva período pago e os direitos existentes; vale a mesma regra da ativação.
O acesso efetivo após a transição continua condicionado a can_access_portal em cada
avaliação; a resposta de retomada não promete acesso permanente nem regularidade
financeira definitiva. Nenhuma compra, assinatura, entitlement ou pagamento é alterado.

SALE_APPROVED e SUBSCRIPTION_RENEWED não alteram o estado administrativo de usuários
existentes. SUBSCRIPTION_CANCELED altera assinatura e preserva o estado do usuário.
Os testes do passo anterior e a regressão do atual verificam esses fluxos, sem mudar
webhooks ou implementar reembolso/chargeback.

## HTTP isolado

POST /admin/customers/{customer_id}/resume

Entrada única: {"confirm_resumption":true}. Mesmo padrão de confirmação da suspensão:
JSON estrito, até 4096 bytes, sem extras/duplicações/query; GET não executa a operação.

Resposta efetiva:
{"customer_id":"identificador","activation_status":"active","result":"resumed"}

Conta enabled já active retorna result=already_active após revalidar o ator, sem
escrita nem auditoria adicional. Esse no-op não exige histórico/compra novos, pois
não altera ou concede estado; também não afirma elegibilidade comercial atual.
Conta blocked ou ativação pending nunca recebem esse resultado.

Reutiliza resume_customer (owner/operator conforme matriz atual), sessão validada,
Origin, JSON, X-Admin-Request: 1 e Cache-Control: no-store. O admin_id não vem do corpo.
Status/papel/auth_version do ator são relidos no mesmo snapshot transacional.
Firestore síncrono roda em threadpool. Não há alteração em autenticação/CSRF/Origin.

400: ID/corpo/query inválidos; 413: tamanho; 415: Content-Type; 401: sessão;
403: autorização/Origin/CSRF; 404: cliente ausente; 409: pré-condição ou proveniência;
503: indisponibilidade, dado comercial corrompido ou escrita não confirmada.
Mensagens sanitizadas, sem payloads, credenciais, cookies ou tokens.

## Auditoria, concorrência e falhas

A transição cria CustomerResumptionAudit na coleção activation_audit existente:
admin_id, customer_id, operation resume_customer, suspended -> active,
human_confirmation true, schema_version 1 e occurred_at UTC. Históricos existentes
não são modificados. A referência create-only é estável entre tentativas do SDK.
A atualização do usuário e a auditoria são confirmadas atomicamente.

O limite local explícito é **oito tentativas nativas**: a retomada tem o mesmo
conjunto de leituras comerciais/usuario/ator da ativação, acrescido de duas consultas
históricas. A ativação já possui evidência local de contenção e orçamento de oito;
por isso a operação com conjunto de leitura maior usa esse orçamento em vez do
padrão de cinco da suspensão simples. Isso é uma escolha inicial limitada, não uma
prova de que oito é ótimo nem garantia de progresso em produção. Ativação mantém
oito e suspensão mantém cinco; nenhum ajuste global ou retry externo foi introduzido.

O SDK instalado repete Aborted do commit até seu limite, reexecutando as leituras.
Erros do callback não recebem essa mesma política. Exaustão (ValueError causado por
Aborted) e falhas de commit incerto resultam em 503; não se repete escrita externa nem
se anuncia sucesso. Um 503 não prova ausência de commit. Consultar estado/auditoria
por acesso confiável antes de decidir nova tentativa manual.

Duas retomadas concorrentes produzem uma transição efetiva e uma auditoria. Na corrida
com suspensão, ambos os ordenamentos são legítimos: suspensão idempotente seguida de
retomada termina active; retomada seguida de nova suspensão termina suspended, com uma
auditoria para cada transição efetiva. Não se presume qual operação vencerá.
Mudança concorrente de conta, compra, direito ou evidência é relida após conflito.
Bloqueio HTTP ainda não existe; a mudança de account_status é simulada no emulador
para verificar que não há desbloqueio implícito, sem implementar nova operação.

## Custos e limites operacionais

Na transição normal: leituras de usuário e ator, duas queries históricas limitadas,
query comercial limitada, leitura do entitlement e duas escritas, além da validação
HTTP da sessão. Conflitos podem repetir leituras e aumentar latência/custo.
A seleção comercial limitada a uma compra mantém o comportamento conservador da
ativação: não busca outra compra se o direito da selecionada não for elegível.
Antes de publicação, índices/configuração efetivos precisam ser verificados em uma
etapa operacional autorizada: o Emulator não comprova disponibilidade de índices
em produção. Nenhum índice foi implantado ou banco real acessado neste passo.

## Escopo e testes

Somente Backend/; router permanece fora de app.main. Nenhum endpoint foi publicado,
botão de retomada implementado, domínio alterado, credencial modificada ou dependência
instalada. Admin/ e Frontend/ foram preservados. Não há bloqueio/desbloqueio novo.
Testes usam mocks e emulador 127.0.0.1:8080, projeto demo-dominando-animacao-test,
AnonymousCredentials e guardas existentes contra produção.
Injeções determinísticas distinguem falha antes do commit, abort confirmado após
rollback, exaustão e perda simulada de confirmação após commit real. Esta última
não reproduz falha de rede real e não promete ausência de gravação.

Resultado final: **1.161 testes unitários e 52 subtestes aprovados**; **96 testes no
Firestore Emulator aprovados** (suíte relevante de 95 e um cenário adicional de
cancelamento real do fluxo Kirvano com retomada durante período pago). São 75 novos
casos unitários e 22 novos casos de integração de retomada. Nenhuma falha final.
Regressão inclui ativação, suspensão, permissões, consulta por e-mail, compra,
composição e webhooks. git diff --check aprovado, inclusive arquivos novos.
Comparação SHA-256 com snapshot inicial confirmou Admin/ e Frontend/ intactos
(excluídos dependências, caches e artefatos de build). Aviso preexistente de
compatibilidade/depreciação Starlette/httpx; nenhuma dependência foi instalada.
O primeiro início do emulador teve timeout da revisão automática de permissões;
a única repetição foi autorizada e os testes foram executados normalmente.
