# GET /admin/customers/{customer_id} — consulta individual não publicada

A consulta foi acrescentada ao router administrativo de clientes já incluído em
compose_admin_http. Não foi registrada em app.main. Reutiliza cliente Firestore,
AdminSessionService, Origin e read_customers. Não inicializa Firebase na importação.

AdminCustomersRepository.get_by_id acessa somente users.document(customer_id).get,
com field_paths da mesma projeção da listagem e timeout=10. Não há where, stream,
busca por e-mail, joins, índices adicionais ou leitura de cursor. A função interna
_project_customer é compartilhada entre consulta individual e paginação, para
preservar o contrato/validações já existentes e evitar regras divergentes.
AdminCustomersService.get_customer delega ao repositório. HTTP executa em threadpool.

A resposta reutiliza AdminCustomer: customer_id, email, account_status,
activation_status e created_at. customer_id é o ID real do documento, não outro
campo inventado. Schema/versões auxiliam validação mas não são retornados. Campos
sensíveis e desconhecidos não são lidos pela projeção nem serializados. Documento
com schema/estado/timestamp incompatível retorna 503 sanitizado, sem dados parciais.

customer_identifier valida antes de construir a referência: ID não vazio, UTF-8
com até 1500 bytes, sem separador Firestore /, . ou .. isolados, nomes reservados
__...__ ou caracteres de controle Unicode Cc. Preserva UUIDs e IDs UTF-8 legítimos,
sem alterar caixa/normalizar. A mesma checagem estrutural reforça o cursor/listagem
para controles; não altera IDs persistidos. A coleção é sempre users. Valores não
viram caminhos arbitrários; não há decodificação extra de percent-encoding no SDK.
A rota de um segmento rejeita caminhos adicionais no roteamento antes da leitura.

Proteção: AdminHTTPAuthentication.require_permission(READ_CUSTOMERS) e
AdminOriginSecurity, com as configurações existentes. Os papéis owner/operator
mantêm a matriz atual, sem confiança em papéis recebidos do navegador. Cookie
inválido/ausente, revogação e status administrativo impedem a leitura do cliente.
Query string é rejeitada com 400, inclusive tentativas de token alternativo.

Respostas: 200 projeção; 400 identificador/requisição inválidos; 401 sessão inválida;
403 Origin/permissão recusados; 404 Customer not found para documento inexistente;
503 falha de validação/leitura/infraestrutura. Mensagens fixas, sem logs de tokens,
IDs ou documentos. Todas as respostas gerenciadas pela rota incluem no-store;
404 de caminhos que nem correspondem à rota depende da camada de aplicação externa,
como já ocorre para outros caminhos desconhecidos. Nenhum cookie é emitido/renovado.

Custo normal: uma leitura de cliente (inclusive documento inexistente), mais cerca
de duas leituras da validação de sessão/admin existente, total aproximado três,
sem retentativas. Identificador inválido não acessa users; falha de autenticação
não chama a consulta. Projeção reduz dados transferidos, não o custo por documento.

Testes unitários verificam referência/get únicos, field_paths, timeout, ausência de
varredura/escritas, campos, falhas sanitizadas, autorização e threadpool. O emulador
usa somente projeto demo, credenciais anônimas, segredo/origem e dados sintéticos.
Compara documentos/update_time antes e depois de consulta/listagem/sessão para
confirmar que users, purchases, subscriptions, entitlements, admins e admin_sessions
permanecem sem alterações durante a leitura. Não foi acessado banco real.

Pronto para uma futura ficha básica de cliente no Admin. Histórico comercial,
compras, assinaturas, entitlements, ações de edição e acesso ao portal continuam
fora do escopo. Nenhuma regra comercial/Kirvano foi modificada. Publicação,
CORS/origens finais e integração visual permanecem pendentes de etapas autorizadas.
