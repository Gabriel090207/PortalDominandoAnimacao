# Permissões operacionais — passo 60

Escopo: somente política de autorização de clientes. Nenhuma nova ação, conta,
rota publicada, permissão ou operação técnica foi implementada.

## Matriz antes e depois

| Permissão | Owner antes | Operator antes | Owner depois | Operator depois |
|---|---|---|---|---|
| read_customers | sim | sim | sim | sim |
| read_dashboard | sim | sim | sim | sim |
| read_audit | sim | sim | sim | sim |
| activate_customer | sim | sim | sim | sim |
| suspend_customer | sim | não | sim | sim |
| resume_customer | sim | não | sim | sim |
| block_customer | sim | não | sim | sim |
| unblock_customer | sim | não | sim | sim |

As quatro permissões adicionadas já existiam no enum e tinham somente owner como
papel autorizado. A inspeção de app não encontrou uso dessas quatro permissões em
operações técnicas nem endpoints/serviços de suspensão, retomada, bloqueio ou
desbloqueio implementados. Seus nomes se referem à operação de cliente prevista.
Owner mantém frozenset(AdminPermission); operator continua com uma allowlist
explícita e granular, agora com as quatro entradas aprovadas. Não se adicionou
curinga, equivalência de papéis, bypass ou autorização por dados do navegador.

O enum atual contém exatamente essas oito permissões; portanto os conjuntos
atualmente coincidem, mas os papéis continuam distintos. Uma futura permissão
técnica adicionada ao enum não será incluída automaticamente na allowlist do
operator. Não se afirma que já existe uma matriz de privilégios técnicos: não há
permissões de gestão de segredos/Firebase/infraestrutura/administradores nesse
enum. Tais mecanismos permanecem externos à concessão operacional e exigem suas
próprias fronteiras explícitas quando implementados.

## Fonte de verdade e persistência

Admin define role, status e auth_version, sem lista de permissões. AdminRecord
persiste esses campos com schema_version/hash e demais fatos administrativos.
AdminSessionRecord persiste admin_id, auth_version_at_issue, método, timestamps e
revogação: não contém role nem snapshot de permissões. Ambos rejeitam campos extras.
As conclusões são dos contratos reais; documentos de produção não foram acessados.

A validação da sessão relê o administrador atual pelo repositório e verifica
vínculo, status, versão de autenticação, prazo e revogação. A dependência HTTP
require_permission chama role_has_permission com o role desse Admin validado.
GET /admin/auth/session também calcula a lista a partir de AdminPermission e
role_has_permission. Alegações de papel/permissões em headers, corpo ou query não
se tornam autoridade. O frontend usa a lista retornada pelo servidor.

Por isso, para registros válidos do contrato atual, a alteração de código basta:
não há lista persistida a migrar. Novos operadores (quando forem provisionados por
um fluxo futuro autorizado) terão as permissões pelo papel operator. Operadores
já existentes não precisam de atualização de documento, auth_version, senha ou
recriação da sessão apenas para esta alteração de política por papel.

A nova matriz passa a valer em cada verificação executada por uma instância com
o código novo, mesmo para sessão válida criada sob a matriz anterior. Não houve
publicação; isso NÃO afirma que um operator real já recebeu essas capacidades.
Em deploy com versões misturadas, instâncias antigas ainda usam a política antiga:
coordenar atualização antes de considerar a política uniforme.

A interface mantém a lista de permissões em memória; precisa de nova consulta da
sessão (ex.: recarregar a aplicação) para atualizar controles visuais. O servidor
continua sendo a autoridade independentemente desse cache visual. Não foi criado
polling ou modificação no Admin. Expiração de oito horas e revogação permanecem
inalteradas; não há migração automática em login/importação.

Se um documento real for incompatível com o contrato (por exemplo, campos extras
não previstos), os loaders atuais falham de maneira segura. Não há inspeção nem
correção de registros reais nesta etapa; esse cenário exigiria investigação
operacional autorizada, não atualização automática de permissões.

## Provisionamento e separação técnica

A ferramenta existente provision_admin/provision_first_owner é exclusivamente
para o primeiro owner, com controle singleton transacional, opt-in e confirmação
de projeto. Nada neste passo a libera para operator ou cria provisionamento
administrativo geral. O domínio aceita role operator, mas não foi encontrado um
fluxo geral de criação/edição de operadores. Esse procedimento deve ser desenhado
em etapa separada, com identidade, autoridade e auditoria próprias; não reutilizar
o bootstrap nem promover operator a owner para obter capacidades operacionais.

Não há operação de atualização de operator a executar nesta etapa. Não foram
alterados credenciais, owner/operator reais, IAM, segredos ou ambiente. Não se
inspecionou a coleção admins em produção.

## Testes

32 novos testes unitários, além de atualização dos dois testes que descreviam a
matriz anterior. Validam a matriz exata, as permissões HTTP para cada papel,
rejeição de desconhecidos/curingas/nomes técnicos fora do enum, negação explícita
mesmo com alegações de owner no navegador, contratos sem snapshot de permissões
e mudança de política para uma sessão operator pré-existente sem mutação.

A negação de uma permissão conhecida é testada com política negadora injetada:
os dois papéis reais agora têm todas as oito permissões do enum. Não se inventa
um terceiro papel real para simular uma distinção que não existe no contrato.

2 novos cenários de emulador (owner/operator), usando documentos sintéticos e uma
sessão criada antes da transição de política, verificam a resposta real de sessão,
igualdade de documentos/update_time antes e depois e ausência das quatro rotas
ainda não implementadas. A simulação de política anterior troca somente a matriz
em memória no teste; não representa atualização de dados Firestore.

Suíte unitária completa: 1029 testes aprovados, 52 subtests. Nenhum acesso à
produção. Guardas do emulador exigem localhost/projeto demo e credenciais anônimas.
Um aviso preexistente Starlette/httpx permanece.

Nenhum cliente, compra, assinatura, entitlement ou administrador real foi alterado.
Nenhuma ação de suspensão/retomada/bloqueio/desbloqueio foi implementada. Os routers
administrativos continuam fora de app.main. Admin/ e Frontend/ foram preservados.

### Resultado da regressão no emulador

Primeira execução selecionada: 16 aprovados e 1 falha no teste existente
`test_concurrent_activation_one_transition_one_audit`. As duas chamadas retornaram
CustomerActivationUnavailable (representadas como unconfirmed no teste); a asserção
exigia exatamente um resultado activated. Essa observação não comprova se houve
commit e não identifica a causa original sanitizada. Não se conclui reativação,
falta de auditoria ou defeito causado pela matriz a partir desse resultado.

Repetição isolada: 1 aprovado. Repetição do conjunto: 17 aprovados. Os dois cenários
novos de permissões passaram nas duas execuções do conjunto. Nenhuma lógica de
ativação ou teste concorrente foi alterado. A intermitência permanece não resolvida:
contenção/timeout/retentativas no emulador são hipóteses, não causas confirmadas.
Recomenda-se investigação dedicada antes de considerar a regressão totalmente
estável; aprovação posterior não apaga a falha inicial. O teste concorrente usa
owner, cuja matriz não foi alterada neste passo.
