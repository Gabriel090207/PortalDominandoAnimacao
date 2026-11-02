# PASSO 77 — preparação técnica para produção

Auditoria de leitura em 22/10/2026. **Admin validado localmente não equivale a
Admin habilitado/homologado em produção. Não publicar ainda.** Nenhum segredo,
arquivo privado .env, credencial, painel externo ou banco real foi acessado.

## 1. Arquitetura e evidências

- O último Start Command informado pelo usuário foi `uvicorn app.main:app --host
  0.0.0.0 --port $PORT`; não foi confirmado em painel nesta auditoria.
- `app/main.py` registra somente raiz, health e webhook Kirvano. Admin permanece
  fora do backend público; isto é uma proteção intencional, não uma falha.
- `app/admin_composition.py` compõe repositórios/serviços/router por aplicação e
  recebe cliente Firestore, configuração HMAC, origens HTTPS e uma dependência
  explícita de origem de rede. Falta dependência confiável de produção: sem ela,
  login retorna 503. A composição não inicializa Firebase ou publica rotas sozinha.
- `app/tools/admin_local.py` é exclusivamente local: loopback, projeto demo,
  credenciais anônimas, TLS temporário e proxy headers desabilitados. **Não é o
  entry point de produção.** Não reutilizar seu resolvedor loopback no Render.
- React usa BrowserRouter e `/clientes` como início. `/painel` é alias protegido;
  ficha individual permanece em `/clientes/:customerId`. Sessão não confirmada
  não libera páginas. Falha de rede não é tratada como logout confirmado.
- Axios exige `VITE_API_URL` HTTPS, usa credenciais, JSON e X-Admin-Request.
  VITE_* é público no build; nenhum segredo deve estar ali.
- Vite tem modo HTTPS local explícito. Build: `npm run build`, saída `Admin/dist`.
  Não foi encontrado configuração própria de deploy Render/Netlify do Admin,
  rewrite SPA ou arquivo de headers do Admin. O `_redirects` do Frontend não
  configura esta aplicação separada. Configurações feitas em painéis não foram
  consultadas e não podem ser presumidas ausentes.

### Níveis de comprovação

| Camada | Confirmado |
|---|---|
| Implementação | Serviços, contratos, rotas-factory e controles descritos neste relatório |
| Testes automáticos anteriores | 1.236 testes Backend + 52 subtestes, 46 novos testes de auditoria no Emulator, 326 testes Admin aprovados |
| Navegador local | Usuário confirmou ativar, suspender e retomar; estado/auditoria conferidos no PASSO 76 |
| Produção | Domínios, cookies entre hosts reais, ingresso, índices, IAM, deploy e carga não homologados |

Os números acima são evidências anteriores; nenhuma suíte foi reexecutada nesta
auditoria. Foi executada apenas uma verificação sintética, em memória e sem rede,
do ProxyHeadersMiddleware instalado: com trusted_hosts="*", selecionou o primeiro
endereço de X-Forwarded-For. Isso não demonstra explorabilidade na infraestrutura
real Render, cuja fronteira ainda precisa ser comprovada. O emulator não foi tocado.

## 2. Autenticação, sessão e permissões — implementados

- Argon2id: memory_cost 19456 KiB, time_cost 2, parallelism 1, salt 16 e hash 32
  bytes. Verificação concorrente limitada a uma por processo. Conta ausente,
  senha incorreta, e-mail inválido ou admin desabilitado usam falha genérica e
  verificação dummy para reduzir enumeração temporal, sem prometer tempo constante.
- Consulta de admin por e-mail normalizado com limit(2), sem scan; duplicidade,
  corrupção e falhas de infraestrutura são rejeitadas com erro sanitizado.
- Token opaco de 32 bytes aleatórios, serializado em 64 caracteres hexadecimais.
  Firestore guarda o digest SHA-256 com separador de domínio, não o token puro.
- Sessão de oito horas, sem renovação automática. Validação considera validade,
  revogação, administrador habilitado, vínculo e auth_version. Criação e leitura
  consistente usam transações; logout confirma revogação antes de limpar cookie.
- HTTP diferencia 401 (sessão/credenciais inválidas), 403 (permissão/origem),
  429 (admissão limitada), 503 (indisponibilidade), além dos erros de protocolo.
  Tokens não são aceitos por URL. Cookie ausente/inválido/duplicado é rejeitado.
- Chamadas síncronas são delegadas ao threadpool; não houve troca por I/O bloqueante
  direto nos handlers async. Respostas administrativas usam Cache-Control: no-store.
- Owner e operator têm as mesmas oito permissões operacionais atuais. Owner usa
  o conjunto completo do enum e operator uma allowlist explícita: futuras
  permissões técnicas não devem ser adicionadas automaticamente ao operator.
- Login/sessão não concedem permissões enviadas pelo cliente. Auditoria registra
  o admin autenticado; ações revalidam papel/status/auth_version na transação.

**IMPORTANTE:** não há fluxo geral de criação de operator, recuperação de acesso
ou manutenção de administradores. O bootstrap existente é somente para o primeiro
owner e não deve ser reaberto. Definir procedimento interno autorizado antes de
operar com novos administradores; não é necessário criar um painel de gestão.

## 3. Cookies, Origin e CSRF

Cookie: `__Host-admin_session`, Secure, HttpOnly, SameSite=Lax, Path=/, sem Domain,
Max-Age limitado ao prazo restante e Expires UTC. O cookie pertence ao **host da
API**, não precisa ser compartilhado com o host do Admin. Não ampliar Domain.

Recomendação: Admin e API em HTTPS sob o mesmo site registrável, com hosts finais
confirmados pelo usuário. Exemplos históricos admin/api-membros/membros não são
configuração aprovada nem evidência de DNS existente. Não tocar em
`portal.dominandoanimacao.com` e não propor wildcard do domínio inteiro.

Netlify e Render em seus domínios padrão são cross-site: o cookie Lax atual não
serve como pressuposto de autenticação XHR nesse arranjo. Trocar para None não é
correção automática das restrições de cookies de terceiros. Usar domínios próprios
same-site preserva o contrato atual, sujeito à homologação nos navegadores reais.

`AdminRequestSecurityConfig` exige origens HTTPS exatas. CORS administrativo já
tem factory: credenciais, GET/POST, Content-Type/X-Admin-Request e exposição de
Retry-After. Reutilizar a mesma allowlist para Origin e CORS; não empilhar no
CORS público atual, que tem finalidades e configuração diferentes.

Origin é obrigatório inclusive para consultas de sessão. Mutações exigem também
X-Admin-Request=1, Content-Type e corpo de confirmação estritos. Esse marcador é
público, não um segredo ou prova de identidade. Origin + marcador/preflight
compõem a defesa CSRF existente; SameSite e CORS isoladamente não substituem
autenticação nem restrições de rede. Testar preflight e erros CORS/503 no ingresso
real; não colocar desafios externos que quebrem OPTIONS silenciosamente.

## 4. CRÍTICO — ingresso e IP confiável ainda não implementados para produção

`api/admin_origin.py` valida sintaxe/canonicalização de um único CF-Connecting-IP:
IPv4, IPv6 e IPv4 mapeado, sem fallback ou confiança implícita. Não verifica a
procedência do header, não implementa allowlist e não está ligado ao login.
Não foi encontrada proteção de rede de produção aplicada a todas as rotas Admin.

O HMAC de admissão apenas ofusca IDs dos buckets: **não autentica proxy, zona
Cloudflare ou requisição**. Uma allowlist aplicada a um header falsificável não
seria uma proteção válida.

Render documenta FORWARDED_ALLOW_IPS=* no runtime Python. Uvicorn local instalado
é 0.51.0: o middleware com '*' confia em todos os peers encaminhados e considera
o primeiro elemento de X-Forwarded-For. Não foi verificada a configuração efetiva
do serviço no painel. `request.client.host` pode já ter sido reescrito; nem ele,
Host, RENDER=true ou a presença de CF-Connecting-IP autenticam a fronteira.

Documentação Cloudflare admite particularidades de Workers/Pseudo IPv4 e informa
que X-Forwarded-For pode preservar uma cadeia previamente fornecida. Render usar
Cloudflare internamente não comprova aplicação de uma política da zona do cliente.

Antes de escolher implementação, confirmar:

1. Cadeia real de proxies e comportamento de sobrescrita/remoção dos headers,
   inclusive duplicados e requisições diretas ao domínio de origem.
2. Se haverá allowlist, seus IPs/CIDRs IPv4/IPv6, estabilidade e recuperação para
   mudanças de IP. Aplicar depois de uma identidade de rede confiável, não antes.
3. Mecanismo de autenticar a própria entrada/host autorizado ou bloquear acesso
   alternativo a **todas** as rotas Admin, não somente ao login ou ao site React.
4. Compatibilidade do mecanismo com Render e com CORS/cookies/preflight.

Candidatos a avaliar, não funcionalidades já disponíveis: gateway que apresente
asserção assinada verificável pelo backend, ou ingresso autenticado com bloqueio
de caminhos diretos. Cloudflare Access com validação JWT na origem é uma opção
documentada; precisa de avaliação de plano, audiência/emissor, fluxo do navegador
e preflight. A validação desse JWT não substitui automaticamente a atestação do
IP específico. AOP/mTLS/Tunnel também exigem suporte de infraestrutura confirmado;
não presumir que um app Uvicorn atrás do proxy Render consegue validar mTLS da borda.

Render documenta restrição de IP para web services em workspaces Scale/Enterprise;
não pressupor disponibilidade no ambiente informado anteriormente como Free.
Permitir IPs Cloudflare não comprova sozinho tráfego da zona específica do cliente.
Desativar o domínio onrender.com pode reduzir um caminho alternativo, mas requer
domínio próprio e não autentica sozinho a borda. **Não fazer isso globalmente sem
avaliar o webhook Kirvano existente**, que utiliza o serviço público.

Resultado: manter Admin não publicado até uma solução de ingresso comprovada.

## 5. Configuração HMAC e recursos operacionais

ADMIN_ADMISSION_HMAC_SECRET é obrigatório ao compor o Admin: exatamente 64
caracteres hex minúsculos, SecretStr, chave versão 1. Ambiente do processo tem
prioridade sobre .env; valor inválido/presente não cai para um fallback. O runner
local só usa ambiente, sem dotenv. Não há configuração de produção própria ainda.
Não foi lido o valor real nem verificado se a variável existe no Render.

Bucket por origem: capacidade 10, +1/30s. Por origem/identidade: capacidade 5,
+1/60s. A admissão dos dois buckets é atômica e precede Argon2id. Falha no
Firestore bloqueia autenticação, não libera tentativa. Credenciais inválidas
consomem admissão; sucesso não zera buckets. Não existe bloqueio global da conta.

Todas as instâncias precisam compartilhar segredo, versão e política. Rotação
arbitrária muda IDs e reinicia orçamentos; políticas persistidas incompatíveis
falham fechadas. Definir troca/rollback coordenados antes de alterar limites/chave.
Limpeza TTL é uma decisão operacional, não condição da expiração lógica.

**IMPORTANTE:** medir CPU/RAM/latência/timeout e custo Firestore no ambiente real
aprovado. A capacidade Argon2id é por processo; adicionar workers multiplica
consumo. Não recomendar mais workers ou Redis sem uma necessidade medida.

## 6. Firestore e índices — confirmação pendente

Não foi encontrado manifesto firestore.indexes.json ou regras Firestore no
repositório. Backend/firebase.json contém apenas emulator. Isso não prova ausência
de índices/regras configurados remotamente, pois o painel não foi consultado.

| Consulta real | Avaliação |
|---|---|
| admins.email_normalized, limit 2 | Índice simples padrão, se não desabilitado |
| users.email_normalized, limit 2 | Índice simples padrão, se não desabilitado |
| users ordenado por __name__, cursor, limit+1 | Índice do nome do documento; sem paginação global no navegador |
| purchases por user_id/status para compra registrada | Confirmar índices/merge de igualdades; não afirmar composto obrigatório sem evidência |
| purchases por user_id/status e intervalos valid_from/valid_until | Índice composto candidato obrigatório para a consulta de múltiplos intervalos; validar plano e ordenação implícita |
| activation_audit por customer_id/operation, limit 1 | Confirmar índices/merge de igualdades; não existe ordenação pelo evento mais recente |
| admin_sessions e auth_throttles | Leituras por ID; nenhum composto exigido pelo fluxo atual |

O emulator não exige índices compostos como produção. Planejar manifesto e uma
validação futura autorizada em Firestore de homologação; não considerar os 46
testes prova dos índices reais. Conferir banco `(default)`, projeto esperado,
IAM mínimo, ausência de configuração de emulator no startup real e separação
de credenciais/dados de desenvolvimento. SDK servidor usa IAM; regras de cliente
não substituem a proteção da conta de serviço.

## 7. Operações, limitações e classificação

Pesquisa exata, paginação, ficha, confirmação, ativação/suspensão/retomada e auditoria
estão implementadas/testadas. Estado/auditoria são atômicos e os no-ops não criam
transições falsas. Resultados incertos pedem releitura, não reenvio automático.

| Achado | Tipo / prioridade | Risco concreto |
|---|---|---|
| Sem ingresso confiável/anti-bypass de produção | Requisito pendente / CRÍTICO | Fraudar origem para contornar limitação/allowlist planejadas |
| Composição, origens e domínios reais não definidos | Requisito pendente / CRÍTICO | Habilitação insegura ou autenticação/cookies indisponíveis |
| Refund/chargeback só em revisão | Limitação conhecida / CRÍTICO para lançamento comercial | Cobrança invalidada ainda pode sustentar entitlement; identidade afetada não comprovada |
| Índices/IAM/configuração Firebase não homologados | Requisito pendente / IMPORTANTE, condição de operação | Erros de consulta, acesso indevido ao banco se configuração externa inadequada |
| Intermitência de suspensão concorrente | Falha observada anteriormente, causa não encerrada / IMPORTANTE | Resposta não confirmada sob contenção, sem evidência de corrupção; não ampliar retries arbitrariamente |
| Histórico de retomada com limit(1), sem vínculo à última suspensão | Limitação conhecida / IMPORTANTE documentar/decidir | Evidência histórica válida não identifica diretamente a restrição mais recente; não há defeito de bypass comprovado |
| Renovação/cancelamento antes de seus vínculos | Limitação conhecida / IMPORTANTE | Inbox pode exigir revisão; reentrega/ordem não tem replay genérico automático |
| Provisionamento de operator/recuperação ausentes | Requisito operacional / IMPORTANTE se necessários à operação | Impossibilidade de administrar novos acessos/recuperar admin pelo produto atual |
| TTL, métricas agregadas e refinamentos de observabilidade | OPCIONAL para primeira versão, com política mínima de operação | Crescimento de armazenamento e menor visibilidade de falhas |

Não foi comprovado novo defeito de produção nesta auditoria. Uma resposta genérica
não fornece diagnóstico interno; planejar métricas/códigos sanitizados sem logar
corpo de login, Cookie, Set-Cookie, tokens, IPs brutos ou segredos. Verificar
políticas externas de logs: não foram consultadas.

## 8. Menor sequência recomendada — sem execução

1. Usuário confirma hosts finais e política de entrada/IPs, orçamento/plano e
   necessidade imediata de operator. Preservar portal.dominandoanimacao.com.
2. Escolher e comprovar fronteira autenticada e anti-bypass compatível com Render;
   só depois integrar resolvedor e eventual allowlist. Falhar fechada no Admin.
3. Criar composição de produção explicitamente habilitada, reutilizando a factory
   existente. Isolar CORS/guardas do Admin do webhook e rotas públicas; definir
   se compartilhará serviço ou usará serviço separado antes de mudar entry point.
4. Preparar URLs, segredo no backend, cliente/banco esperado sem emulator, índices,
   IAM, rewrite SPA do Admin e headers do hosting (CSP, anti-framing,
   X-Content-Type-Options, Referrer-Policy, HTTPS). Não inferir headers do servidor
   a partir de index.html; configurar e homologar no hosting escolhido.
5. Validar em ambiente aprovado os caminhos direto/proxy, IPv4/IPv6, spoofing,
   cookies/CORS/CSRF/OPTIONS, owner/operator, concorrência e índices reais.
6. Definir versão conhecida para rollback, controle para retirar somente Admin,
   coordenação de segredo/política e acompanhamento inicial. Publicação apenas
   após autorização explícita, sem executar novamente bootstrap.

Resend permanece fora deste passo. O futuro e-mail pós-compra aprovada não deverá
alterar ativação pending nem conceder acesso. A finalização técnica do Admin não
remove o bloqueio comercial de reembolso/chargeback.

## Fontes oficiais consultadas (somente documentação pública)

- [Render: variáveis padrão](https://render.com/docs/environment-variables)
- [Render: regras de IP](https://render.com/docs/inbound-ip-rules)
- [Render: domínios próprios e onrender.com](https://render.com/docs/custom-domains)
- [Uvicorn: configuração de proxies](https://uvicorn.dev/settings/)
- [Cloudflare: headers e particularidades de Workers](https://developers.cloudflare.com/fundamentals/reference/http-headers/)
- [Cloudflare: proteção da origem](https://developers.cloudflare.com/fundamentals/security/protect-your-origin-server/)
- [Cloudflare Access: validação JWT](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [Firestore: índices](https://firebase.google.com/docs/firestore/query-data/index-overview)
- [Firestore Emulator: diferenças de índices/transações](https://firebase.google.com/docs/emulator-suite/connect_firestore)

## Arquivos examinados

app/main.py; app/admin_composition.py; app/tools/admin_local.py;
app/api/admin_auth.py, admin_customers.py, admin_dependencies.py,
admin_request_security.py, admin_origin.py, admin_cookies.py;
app/config/admin_admission.py, admin_cors.py, admin_http_security.py;
app/domain/admin.py, policies.py, admin_admission.py;
app/services/admin_auth_service.py, admin_password_service.py,
admin_session_service.py, admin_login_service.py, admin_admission_service.py,
firebase_service.py; repositórios Admin de clientes, sessões, admissão,
ativação/suspensão/retomada e elegibilidade; transação comercial Kirvano;
firebase.json; requirements.txt; documentação administrativa existente;
Admin/package.json, vite.config.ts, index.html, .env.example,
src/services/adminApi.ts e src/session/sessionStore.ts.

Única alteração desta etapa: este documento. Código, Admin/Frontend, credenciais,
serviços, servidores locais, dados e certificados foram preservados. Nenhuma
publicação, operação em produção ou PASSO 78 foi iniciado.
