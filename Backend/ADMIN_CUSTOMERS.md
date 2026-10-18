# GET /admin/customers — leitura paginada não publicada

## Modelo atual confirmado

Clientes estão em users/{document_id}. O ID do documento é o user_id referido por
email_identities, purchases, subscriptions e entitlements; não existe necessidade
de buscar essas coleções para listar os dados básicos. O escritor comercial atual
persiste schema_version=1, email_normalized, email_normalization_version,
account_status, activation_status e created_at. AccountStatus: enabled/blocked;
ActivationStatus: pending/active/suspended. A listagem não interpreta esses estados
como prova de direito comercial ou autorização para entrar no portal.

Assinaturas usam user_id e compras usam user_id/subscription_id. Entitlements usam
user_id/purchase_id e possuem status/período próprios. Nenhum desses registros é
consultado por linha, alterado ou agregado. A integração Kirvano não foi modificada,
e não há chamada à API do provedor ou disparo de webhooks.

## Arquitetura

admin_customers.py (domain) define projeção de resposta e cursor. O repositório
admin_customers_repository.py consulta somente users, o serviço interno
admin_customers_service.py expõe a listagem e api/admin_customers.py trata HTTP.
compose_admin_http compartilha o cliente e o AdminSessionService existentes.
Seu router retornado agora é um agregador sem prefixo, incluindo os routers de
autenticação e clientes com seus próprios prefixos, preservando todos os caminhos.
Nenhum cliente Firebase ou configuração é criado na importação.

A rota exige AdminOriginSecurity e AdminHTTPAuthentication.require_permission(
AdminPermission.READ_CUSTOMERS). Cookie inválido/ausente/revogado ou administrador
desabilitado resulta em 401. Origin/permissão rejeitada resulta em 403. Ambos os
papéis existentes, owner e operator, já possuem read_customers; teste de negação
simula a recusa da matriz, sem inventar terceiro papel ou alterar permissões.
A autorização precede a consulta. Operações síncronas executam em threadpool.

## Contrato e paginação

GET /admin/customers?limit=20&cursor=...

Resposta: items e next_cursor. Cada item contém SOMENTE customer_id (ID real do
documento), email, account_status, activation_status e created_at. Não são retornados
schema, versões, dados de autenticação ou documentos inteiros. Campos desconhecidos
não são expostos. O SDK usa projeção desses campos e versões necessárias à validação.
Documento incompatível/corrompido falha com 503, sem ser omitido silenciosamente.

Limit padrão 20, mínimo 1, máximo 50. Consulta order_by('__name__') ascendente com
limit+1; não há offset, contagem total, busca do documento cursor ou varredura para
paginação. Com lookahead, next_cursor é o último ID RETORNADO, e não o documento
extra. Sem documento extra, next_cursor é null. Página vazia é items=[], cursor null.
A ordem é lexicográfica por ID Firestore, não cronológica por criação.

Cursor é base64url canônico sem padding do ID UTF-8, limitado pelas regras de ID
Firestore (até 1500 bytes, sem /, . ou .. e nomes reservados __...__). Não é assinatura,
segredo nem prova de autorização. Pode ser construído para pular parte da listagem;
isso não amplia acesso, pois sempre consulta a coleção fixa users após autorização.
Não permite caminhos de coleção/documento arbitrários. Não contém e-mail. Não há
chave HMAC nova/reutilizada para cursors. Inserções/remoções entre páginas não formam
um snapshot congelado; IDs inseridos antes do cursor poderão exigir uma nova listagem.

Parâmetros desconhecidos, duplicados, cursor inválido e limite inválido resultam em
400 sanitizado. Falhas de leitura/contrato resultam em 503. Respostas gerenciadas pelo
router usam Cache-Control:no-store, sem cookies novos ou mensagens internas.
O endpoint ignora qualquer papel do navegador; não aceita token em query.

## Índices e custos

A ordenação usa o índice nativo do nome/ID do documento, sem filtro ou índice
composto adicional. Não há migração/indexação configurada nesta entrega. A projeção
reduz campos transferidos, mas não elimina cobrança por documento retornado.

Até limit+1 documentos lidos por página na consulta de clientes: padrão até 21,
máximo até 51. Página vazia tem cobrança mínima de uma leitura da consulta no
Firestore. Acrescentar aproximadamente duas leituras da validação existente de
sessão/admin: até 23/53 no caso normal, sem retentativas. Não há leitura extra para
resolver cursor, N+1, agregação de compras ou escrita. Retentativas/erros de rede
podem elevar custos; não confundir limite de resultados com teto de todo tráfego.

## Validação e pendências

Mocks verificam projeção, timeout, limit+1, cursor por referência sem get, autorização
e erros. Emulador usa somente projeto demo, credenciais anônimas e dados sintéticos:
IDs fora de ordem, duas páginas, fim/vazio, campos e composição real. Compara dados
e update_time antes/depois para confirmar ausência de gravações nas coleções de
clientes, compras, assinaturas, entitlements, administradores e sessões existentes.

Não há frontend/tabela nesta entrega. Próximo passo pode adicionar o método tipado
no Admin e tabela mínima consumindo items/next_cursor, sem presumir métricas ou
acessos comerciais. Publicação depende de autorização, composição, CORS/origens
finais e homologação. GET /admin/customers NÃO está em app.main e não foi publicado.
