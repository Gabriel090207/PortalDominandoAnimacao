# Transporte interno do cookie administrativo

app/api/admin_cookies.py fornece issue_admin_session_cookie e
remove_admin_session_cookie para respostas Starlette/FastAPI. Não registra rotas,
não é conectado ao main e não inicializa Firebase ou configurações. Nenhum domínio
é fixado. Os atributos não são configuráveis: __Host-admin_session, HttpOnly,
Secure, SameSite=Lax, Path=/, sem Domain, inclusive na remoção. Não há bypass para
HTTP local; os testes simulam HTTPS.

Após autenticação bem-sucedida, a futura rota passa o IssuedAdminSession retornado
pelo serviço existente e uma Response contendo somente dados públicos. O componente
valida o contrato AdminSession novamente, exige token SecretStr no formato atual,
data timezone-aware, sessão já iniciada, não revogada e ainda não expirada. Não
consulta Firestore nem comprova a procedência/persistência do objeto: deve receber
o resultado diretamente do fluxo confiável de autenticação, nunca dados do cliente.

Max-Age usa o número inteiro de segundos restantes, arredondado para baixo e
limitado à duração de oito horas existente no domínio. Fração restante inferior a
um segundo é rejeitada, sem cookie, para evitar arredondamento que ultrapasse o
prazo. Expires é o expires_at original em UTC truncado para segundos. O tempo é
capturado no momento da emissão (now injetável em testes); não contar oito horas
a partir de cada resposta. O backend continua sendo autoridade para expiração,
pois trânsito/relógios de navegador não garantem entrega instantânea.

A remoção usa delete_cookie com mesmo nome/Path, sem Domain, Max-Age=0 e expiração
imediata. Ambas as operações definem Cache-Control: no-store e acrescentam apenas
o Set-Cookie administrativo, preservando cookies de outras funcionalidades.
O token aparece necessariamente em Set-Cookie na emissão; não é colocado no JSON,
URLs ou logs. Sistemas de observabilidade futuros devem ocultar Set-Cookie e Cookie.

Remover cookie NÃO revoga sessão. O logout futuro deverá confirmar revoke no
servidor antes de informar sucesso e remover o cookie. Falha ou commit incerto
exige resposta sanitizada de indisponibilidade, sem confirmação de logout. O helper
não recebe resultado de revogação, portanto essa ordem é contrato do chamador;
o endpoint e sua integração de falhas ainda não existem. Nenhuma lógica de
revogação foi adicionada ou modificada.

O componente não cria sessões, não renova sessões automaticamente, não autentica
nem autoriza. Falhas de entrada na emissão geram AdminCookieError fixo e sanitizado.
A sessão permanece em SecretStr até a escrita do header. A resposta fornecida
pela rota não deve serializar IssuedAdminSession nem outros objetos sensíveis.

Pendências: rotas de login/logout, composição, origem/IP confiável no Render,
CSRF, CORS e domínios finais. Frontend/API devem operar por HTTPS, preferencialmente
no mesmo site; SameSite=Lax não habilita XHR entre netlify.app e onrender.com.
A consulta de sessão continua usando AdminSessionService.validate através de
AdminHTTPAuthentication. Nenhuma configuração de produção foi aplicada.
