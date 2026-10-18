# Consulta HTTP de sessão administrativa (router não publicado)

app/api/admin_auth.py fornece create_admin_auth_router(session_service=...,
security_config=...). A composição é explícita, sem clientes, segredos ou ambiente
inicializados na importação. Não é importado nem incluído em app.main.
Somente a aplicação de teste registra GET /admin/auth/session nesta entrega.

O GET exige Origin exato configurado através de AdminRequestSecurityConfig e
AdminOriginSecurity. A política HTTPS estrita existente foi extraída em dependência
reutilizável, preservando as verificações de mutações. O GET não é uma mutação e
não exige Content-Type ou X-Admin-Request; futuras mutações continuam exigindo ambos
conforme AdminRequestSecurity. Origin inválido é rejeitado antes da consulta.
Não se trata da origem IP do rate limiting: não utiliza o resolvedor CF nem login.

AdminHTTPAuthentication recebe o serviço injetado e continua lendo exclusivamente
o cookie __Host-admin_session, rejeitando duplicidades e formato inválido. Executa
AdminSessionService.validate fora do event loop. Não há segunda consulta, criação,
renovação ou alteração de sessão e nenhum cookie é emitido ou removido.

Resposta 200 possui allowlist explícita: admin_id, email, role e permissions.
As permissões são calculadas por role_has_permission e AdminPermission existentes,
nunca a partir do navegador. O identificador é o admin_id já existente; não é
introduzida outra identidade pública. Nenhum documento Firestore é serializado.

expires_at foi deliberadamente omitido: a dependência atual retorna somente Admin,
não a sessão validada. Acrescentar uma segunda leitura para obter expiração teria
custo e possível inconsistência; expor um contexto validado ampliaria o contrato.
Se o frontend precisar desse campo, aprovar uma extensão mínima futura que entregue
Admin e sessão a partir da mesma validação. Não foi alterado o serviço nesta etapa.

401: cookie/sessão inválida, expirada, revogada, administrador desabilitado ou versão
incompatível. 403: origem ausente, desconhecida, duplicada ou malformada. 503: falha
que impede confirmar sessão. Mensagens são fixas e sanitizadas. A rota adiciona
Cache-Control: no-store a sucessos e exceções HTTP de dependências; falhas inesperadas
do handler também viram 503 sanitizado e no-store. Não há logs de credenciais.
O router não muda CORS global. Infraestrutura externa/CDN futura também precisa
preservar no-store e não capturar Cookie/Set-Cookie em observabilidade.

Pendências: publicação explicitamente autorizada, lifecycle do serviço, CORS com
origens finais, frontend e eventual contexto de expiração. Login/logout HTTP,
CF trust boundary e integração de cookies continuam fora desta entrega.
