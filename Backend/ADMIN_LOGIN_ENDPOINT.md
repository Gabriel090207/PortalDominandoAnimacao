# POST /admin/auth/login (router isolado, não publicado)

A fábrica create_admin_auth_router continua fora de app.main. Recebe session_service,
security_config e, para login, login_service e trusted_origin_dependency. O serviço
injetado deve ser AdminLoginService composto com política/HMAC já existentes; não
usar AdminAuthService diretamente. Não há configuração, cliente Firebase ou segredo
carregado na importação. Ausência de login_service ou origem confiável gera 503.

trusted_origin_dependency é um callable(request), função síncrona em threadpool ou
função async, que retorna origem de rede já validada por camada confiável. Não é o
header Origin. Nesta entrega só existe injeção sintética de teste. O router não lê
CF-Connecting-IP, X-Forwarded-For, peer ou IP no JSON como alternativa. O contrato
de confiança é responsabilidade da composição, e um callable arbitrário não
comprova a fronteira do Render/Cloudflare. Não publicar até validação operacional.

A proteção HTTP existente valida Origin HTTPS exato configurado e X-Admin-Request: 1,
sem duplicidades. Exige application/json. O corpo é lido em streaming até 4096 bytes
(limite de transporte suficiente para credenciais atuais e JSON normal; escapes ou
campos grandes podem excedê-lo). Aceita somente objeto com email e password strings,
sem campos extras, chaves duplicadas ou constantes JSON não padronizadas. Não aceita
query string. Erros não ecoam dados. Não valida sintaxe do e-mail antecipadamente:
endereços inválidos continuam sujeitos à admissão por origem e ao bucket reservado.

AdminLoginService.authenticate executa em threadpool. O coordenador existente
confirma os dois buckets antes de consultar admins/Argon2/criar sessão. Falhas ou
commit incerto não liberam autenticação. Não existe nova fila, retentativa HTTP,
reset ou segunda criação de sessão.

200 retorna somente {"admin_id":"synthetic-admin"} e emite cookie através de
issue_admin_session_cookie, preservando __Host-admin_session, Secure, HttpOnly,
SameSite=Lax, Path=/ e ausência de Domain. O serviço retorna IssuedAdminSession,
que não contém email/role. Para evitar outra consulta só para apresentação, GET
/admin/auth/session continua fornecendo email, role e permissões calculadas pelo
servidor. Login não aceita nem concede permissões do navegador.

401 credenciais inválidas (mesma resposta para inexistente/desabilitado/senha errada).
403 Origin/CSRF rejeitado. 429 limitação, com Retry-After exato do coordenador, sem
identificar bucket. 503 indisponibilidade de serviço/admissão/origem/capacidade ou
falha de emissão da sessão/cookie. 400 corpo/estrutura/query inválidos, 413 tamanho,
415 formato. Todas as respostas gerenciadas pelo router usam no-store; erros não
emitem cookie. Infraestrutura externa ou falhas anteriores ao roteamento ainda
precisam ser verificadas na integração pública.

Um erro de transporte/emissão após uma sessão persistida pode deixar sessão sem
cookie entregue; não presumir rollback ou repetir autenticação automaticamente.
Não há revogação compensatória nova nem alteração de sessões anteriores.
Nenhum segredo/token é colocado em JSON/URL/logs; Set-Cookie é necessariamente
sensível e deve ser ocultado na observabilidade futura, assim como Cookie e corpo.

Pendências: callable de origem com fronteira comprovada, composição real autorizada
com HMAC dedicado e política, domínios finais HTTPS/same-site, CORS e frontend com
credenciais, publicação explícita. GET permanece disponível somente no router de
teste. Logout HTTP não foi implementado; Kirvano permanece independente.
