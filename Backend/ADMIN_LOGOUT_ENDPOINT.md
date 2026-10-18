# POST /admin/auth/logout (router não publicado)

A fábrica create_admin_auth_router inclui logout no router isolado. Nenhuma rota
foi incluída em app.main. A composição recebe o AdminSessionService existente;
não inicializa Firebase, segredos, login ou serviços na importação.

O endpoint aplica AdminRequestSecurity(requires_json=False): Origin HTTPS exato
configurado e X-Admin-Request: 1 obrigatórios e sem duplicidade. Logout não tem
corpo: rejeita qualquer corpo não vazio e query string com 400 sanitizado. Não
aceita token ou identificador em JSON, URL ou Authorization como alternativa.
GET recebe 405 sem executar o serviço. Não altera CORS nem webhook Kirvano.

read_admin_session_token expõe o leitor estrito já usado por autenticação HTTP:
exige exatamente um cookie __Host-admin_session de 64 caracteres hexadecimais
minúsculos. Ausência, formato inválido e duplicidade (mesmo valor inclusive)
retornam 401 sem chamar persistência. Nenhum outro token é procurado.

Não exigir AdminHTTPAuthentication.validate antes de revogar permite logout de
sessões expiradas, de administrador desabilitado ou já revogadas. Somente a posse
do cookie identifica qual sessão revogar; esse endpoint não concede acesso a
qualquer dado ou função administrativa. O leitor é compartilhado, sem duplicação.

AdminSessionService.revoke(token) executa em threadpool, com motivo logout padrão.
O router não altera transações, retentativas ou regras do serviço/repositório.
True significa revogação confirmada; False, com token previamente validado pelo
leitor, significa leitura transacional confirmada de sessão inexistente ou já
revogada. Ambos resultam em 200 {"success":true} e remoção idempotente do cookie.
Sessão expirada existente também passa por revogação. Nenhuma outra sessão é
revogada, criada ou renovada, e a primeira data/motivo não são substituídos.

Somente após retorno booleano confirmado, remove_admin_session_cookie emite a
remoção com Max-Age=0, expiração imediata, Secure, HttpOnly, SameSite=Lax, Path=/,
sem Domain. Outros cookies não são removidos. O token não aparece no JSON ou logs.

Falhas de infraestrutura, timeout, resultado incerto e retorno inesperado geram
503 sanitizado sem Set-Cookie e sem success:true. Não se presume rollback: uma
sessão pode ter sido revogada apesar de perda de confirmação. O cliente mantém
seu cookie para poder tentar novamente; repetição após a revogação já confirmada
no servidor torna-se sucesso idempotente. Não há retentativa adicional no router.

Todos os resultados gerenciados pelo router incluem Cache-Control:no-store,
inclusive erros 400/401/403/405/503. O cliente futuro não deve anunciar encerramento
confirmado em caso de 503. Se a própria resposta/cookie se perder após commit,
uma nova chamada ainda é segura. Outras camadas HTTP anteriores ao router devem
ser verificadas na publicação futura.

Testes usam mocks e serviço existente com persistência transacional em memória.
O cenário de commit seguido de erro é determinístico e não simula garantias novas
do Firestore. A lógica transacional real permanece coberta pela suíte existente;
não houve necessidade de alterar/executar banco real nesta etapa.

Pendências: composição e publicação autorizadas, origens finais, CORS, frontend,
HTTPS/same-site e origem de rede confiável para o login. Login e GET session
permanecem no router isolado; nenhuma alteração de produção foi realizada.
