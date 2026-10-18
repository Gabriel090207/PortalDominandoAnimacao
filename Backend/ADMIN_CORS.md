# Política CORS administrativa preparada, não ativada

app/config/admin_cors.py fornece admin_cors_options(security_config), reutilizando
AdminRequestSecurityConfig e sua validação HTTPS estrita. Não instala middleware,
não cria app/router, não carrega ambiente nem altera main. As mesmas origens devem
ser fornecidas à composição administrativa/CSRF e ao CORS, evitando listas divergentes.
Nenhuma origem/default de desenvolvimento ou domínio provisório é fixado.

A política permite somente origens exatas, credenciais, métodos GET e POST, headers
Content-Type e X-Admin-Request. Expõe Retry-After, que o frontend precisa ler nos 429.
Não usa wildcard/regex/sufixo. Starlette acrescenta os headers CORS safelisted pelo
padrão (Accept, Accept-Language e Content-Language, além de Content-Type); isso não
é autorização de headers arbitrários. OPTIONS é interceptado como preflight pelo
middleware, sem constar como operação administrativa GET/POST da aplicação.

Nos testes existe somente um CORSMiddleware instalado, envolvendo externamente a
FastAPI de teste sem outro CORS. Exemplo futuro em uma fronteira já aprovada:
CORSMiddleware(app, **admin_cors_options(security_config)). Não executar isso em
cima do app.main atual que já contém middleware CORS. O helper apenas disponibiliza
opções, não impede que um chamador incorreto empilhe middlewares.

Preflight OPTIONS com Origin e Access-Control-Request-Method permitidos responde
200, credenciais true, ACAO exato e Vary: Origin. Métodos/headers não permitidos ou
origem desconhecida geram 400. Não exige cookie, autenticação, admissão ou Firestore.
O cache de preflight é o padrão da biblioteca; não armazena sessão ou credenciais.
As respostas reais administrativas continuam no-store. CORS não impede um cliente
não navegador de enviar requisições: o router ainda exige Origin/CSRF, origem de
rede confiável e AdminLoginService; consulta e logout mantêm suas regras próprias.

ACAO não é enviado a origens desconhecidas. Cabeçalhos auxiliares como
Access-Control-Allow-Credentials podem aparecer mesmo assim: sem ACAO autorizado,
o navegador não libera a resposta. Não refletir origens arbitrárias para facilitar
leitura de erros por uma origem maliciosa. Cookies continuam inalterados: HttpOnly,
Secure, SameSite=Lax, Path=/, sem Domain. CORS não expõe Set-Cookie ao JavaScript.

Erros 400/401/403/413/415/429/503 do router preservam CORS para origem autorizada e
Cache-Control:no-store. A arquitetura atual de app.main adiciona CORS por
add_middleware, dentro do ServerErrorMiddleware. Um 500 inesperado gerado pela
camada externa pode perder os headers CORS; teste isolado reproduz essa limitação.
Um único CORS externo inclui headers também no 500. CORS, porém, NÃO define cache
para erro externo ao router: teste documenta ausência de no-store no 500 padrão,
e outro confirma CORS+no-store com handler 500 sanitizado explícito na app de teste.
Esse handler NÃO foi instalado em main. Falhas do proxy/CDN anteriores à aplicação
também ficam fora dessas garantias.

## Integração futura com as rotas públicas

main já tem uma política mais ampla (origens públicas/local, métodos e headers *)
e não permite políticas diferentes por router com o CORSMiddleware padrão.
Adicionar outro middleware sobre a mesma aplicação não é a solução: ambas as
camadas podem alterar respostas/interceptar preflights de forma conflitante.

A menor solução futura, se os clientes públicos forem compatíveis, é aprovar uma
política global única com lista explícita de origens e somente os métodos/headers
necessários a TODOS os consumidores; remover/substituir a camada interna atual e
instalar UMA camada externa. A lista global poderia incluir clientes públicos,
mas a validação Origin administrativa continuaria restrita à lista específica.
Assim, não seria CORS estritamente diferente por rota, e essa consequência precisa
ser aprovada. Inventariar consumidores antes de restringir o global; o webhook
servidor-servidor não depende de CORS, mas não deve receber CSRF administrativo.

Se o requisito for preflight CORS estritamente distinto por rota, o middleware
atual não atende: exige desenho aprovado de uma única fronteira ASGI seletiva por
caminho, ou fronteiras de aplicação/host separadas. Isso não foi implementado nem
uma subaplicação foi montada nesta etapa. Também aprovar handler sanitizado/no-store
para erros administrativos inesperados, sem modificar erros públicos indiscriminadamente.

## React e homologação

O futuro cliente Axios administrativo usará withCredentials:true, corpo JSON e
X-Admin-Request:1 para login/logout. O token permanece HttpOnly; não ler Set-Cookie
nem armazenar token em localStorage. Tratar 429 por Retry-After e 503 sem presumir
logout confirmado. A lista de origens deve ser escolhida explicitamente para cada
ambiente; desenvolvimento também usa HTTPS, sem bypass automático para localhost.

Testes locais com cliente HTTP não reproduzem bloqueio de cookies de terceiros,
políticas do navegador, DNS/TLS ou proxies reais. Homologar em navegadores com os
domínios definitivos same-site e verificar Cache-Control nos intermediários.
A fronteira de confiança Render/Cloudflare continua pendente para o login.
Nenhuma configuração Render/Netlify, frontend ou CORS público foi alterada.
