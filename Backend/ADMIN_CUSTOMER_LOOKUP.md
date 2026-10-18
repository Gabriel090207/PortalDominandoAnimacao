# Busca administrativa por e-mail — passo 55

POST /admin/customers/lookup, exclusivamente leitura, no router administrativo
isolado e na composição existentes. Não registrado em app.main nem publicado.

## Contrato

Corpo JSON único, no máximo 4096 bytes:

```json
{"email":"cliente@example.com"}
```

Exige sessão válida, Origin autorizado, X-Admin-Request: 1, application/json e
read_customers, igualmente para owner e operator. Reutiliza AdminRequestSecurity
(incluindo rejeição de headers de protocolo ausentes/duplicados) e a dependência
de autenticação real. Nenhuma alteração de matriz, login, sessões ou rate limiting.
Não aceita query parameters, campos extras, estruturas alternativas, valores
não-string, JSON malformado, constantes não JSON ou chaves duplicadas. E-mail em
header não é uma fonte de consulta: somente o campo JSON é utilizado. Não há
rota de busca por e-mail no caminho. O frontend futuro deve enviar o corpo;
nenhuma interface foi modificada.

Resposta 200 reutiliza AdminCustomer:

```json
{
  "customer_id": "synthetic-customer",
  "email": "cliente@example.com",
  "account_status": "enabled",
  "activation_status": "pending",
  "created_at": "2026-01-01T00:00:00Z"
}
```

400: query/corpo/e-mail inválido; 413: corpo excessivo; 415: tipo de conteúdo
inválido; 401: sessão ausente/inválida; 403: Origin/CSRF/permissão recusados;
404: nenhum cadastro; 409: mais de um cadastro; 503: falha Firestore/registro
inconsistente. Erros fixos e sanitizados, sem repetir e-mail ou dados de origem.
Respostas geridas pelo router têm Cache-Control: no-store. A ordem das
verificações pode fazer uma falha de segurança preceder a validação do corpo.

## Vínculo real, normalização e legado

O webhook recebe customer.email. classify_commercial_event utiliza normalize_email;
receive_commercial_event deriva a identidade HMAC normalizada e a transação
comercial resolve email_identities.user_id. Quando cria o usuário, persiste
users/{id}.email_normalized e email_normalization_version=1, e as compras passam
a referenciar esse mesmo ID em user_id. A busca não consulta compras nem deriva
identidade de um e-mail semelhante.

normalize_email é compartilhada pelo webhook e pela busca: remove espaços externos,
converte para minúsculas, valida sem DNS e mantém pontos e aliases. Não remove
+tag nem presume que endereços diferentes são a mesma pessoa. A projeção de cada
cadastro verifica a versão e consistência da normalização existente.

O fluxo comercial serializa a associação através da identidade HMAC, mas isso não
é uma restrição global de unicidade sobre todos os possíveis escritores de users.
Por isso a busca lê até dois documentos e responde 409 se houver ambiguidade,
sem escolher o primeiro, mesclar dados ou autorizar ações. A correção de registros
duplicados requer revisão interna separada; nenhuma migração foi implementada.

A busca exata é possível sem migração para documentos do modelo atual. Documentos
antigos que tenham somente email, ou valor não canônico em email_normalized, não
são adivinhados/varridos: podem não corresponder à consulta e resultar em 404.
Um documento correspondente mas incompatível com o contrato resulta em 503.
A existência desses casos na produção NÃO foi investigada. Não há fallback
aproximado, migração ou atualização automática. Localizar tais registros exigiria
investigação de dados separada e autorizada.

## Persistência e custo

AdminCustomersService.lookup_customer delega a AdminCustomersRepository.find_by_email.
Consulta: users.where(email_normalized == valor_normalizado).select(campos da
projeção existente).limit(2).stream(timeout=10), fora do event loop via threadpool.
Não utiliza offset, substring, N+1, leitura adicional por documento ou full scan.
Não cria cliente Firebase nem inicializa app na importação.

Requer o índice single-field de email_normalized, normalmente automático, se não
houver isenção. Não exige índice composto. Não houve inspeção/criação/alteração
de índices de produção; o emulador não comprova sua disponibilidade em produção.

Consulta lê no máximo dois documentos de usuário, normalmente um. Consulta vazia
tem cobrança mínima de uma leitura. Com as leituras usuais de sessão/admin (~2),
estimativa ~3 leituras para resultado único/vazio e ~4 para ambiguidade. Falhas e
retentativas do SDK podem alterar o custo efetivo. E-mail inválido não consulta users.

Não há logs de e-mail, caches, mutações, criação de cliente, ativação, leitura de
assinaturas ou chamada à API externa Kirvano. O POST apenas consulta dados.

## Validação

38 novos testes unitários; suíte completa: 951 aprovados, 52 subtests.
10 cenários relevantes no Firestore Emulator aprovados, incluindo dois novos
(owner/operator), com dados sintéticos e guardas de localhost/projeto demo/
credenciais anônimas. Demonstram correspondência exata, normalização, aliases,
404, duplicidade 409, comportamento do legado e ausência de alterações comparando
dados e update_time de todas as coleções antes/depois. Testes existentes preservam
login, sessão, logout, listagem, ficha, confirmação, acesso e processamento Kirvano.
Um aviso preexistente de depreciação Starlette/httpx permanece.

Sem acesso à produção, publicação ou implementação de ativação. A busca não
confirma pagamento nem concede acesso. São etapas separadas e autorizadas.
