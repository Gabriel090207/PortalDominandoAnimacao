# Dependências HTTP administrativas isoladas

app/api/admin_dependencies.py disponibiliza AdminHTTPAuthentication(session_service).
A composição futura injeta um AdminSessionService existente; o módulo não cria
clientes Firebase nem inicializa configuração, login ou rotas. Não é importado
por main.py. Nenhum domínio está fixado no componente.

Uso futuro em FastAPI: Depends(authentication) exige sessão válida;
Depends(authentication.require_permission(AdminPermission.READ_CUSTOMERS)) também
exige a permissão. O chamador constrói authentication uma vez e registra as
rotas apenas em uma etapa futura autorizada. Nenhuma rota foi publicada aqui.

O único transporte aceito é o cookie __Host-admin_session, com o formato atual de
64 caracteres hexadecimais minúsculos. O parser lê todos os campos Cookie brutos
ASGI, preservando duplicidade que request.cookies poderia ocultar. Rejeita cookie
ausente, vazio, malformado, entre aspas ou duplicado, inclusive valores idênticos
ou distribuídos entre vários headers. Nomes de cookies são case-sensitive; nomes
de headers não são. Não procura tokens em URL, Authorization ou outros headers.

O cookie isoladamente não autentica. A dependência aguarda
AdminSessionService.validate em threadpool, fora do event loop. Esse serviço
consulta sessão e administrador e aplica validade absoluta de oito horas,
revogação, vínculo de identidade, status e versão de autenticação existentes.
Não cria, renova, revoga nem modifica sessões. A dependência rejeita resultados
inesperados do serviço com erro interno. O Admin retornado é usado pela matriz
role_has_permission; alegações de papel/permissão do frontend são ignoradas.

Respostas fixas: 401 para ausência/invalidade da sessão, 403 para permissão
insuficiente e 503 para falha de validação/armazenamento. Nenhum token ou detalhe
de infraestrutura é incluído. Não há logs produzidos pelo componente. A camada de
observabilidade futura também deve excluir cookies e dados sensíveis; não ativar
captura de variáveis locais ou corpos/headers de autenticação em diagnósticos.

Pendências: composição/lifecycle do serviço, endpoints, emissão/remoção do cookie,
HTTPS, domínios configuráveis, CSRF para mutações, CORS, cache no-store e tratamento
HTTP completo. Esta dependência autentica/autoriza, mas não implementa CSRF.
A validação operacional Render/Cloudflare continua necessária para a origem do
futuro login/rate limiting. O componente não interpreta headers de IP.
As proteções não foram aplicadas ao webhook Kirvano ou às rotas existentes.

Testes usam aplicação FastAPI criada somente nos testes, mocks e repositório
isolado. Não dependem do Firebase de produção e não emitem cookies em respostas.
