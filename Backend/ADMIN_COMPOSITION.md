# Composição administrativa HTTP explícita (não publicada)

app/admin_composition.py disponibiliza compose_admin_http. Não é importado pelo
main e não registra rotas automaticamente. A importação não inicializa Firebase,
não carrega ambiente/segredos, não consulta admins e não cria sessões.

Parâmetros explícitos:

- firestore_client: cliente já obtido pelo chamador. Futuramente pode ser o mesmo
  get_firestore_client de firebase_service utilizado pelo backend, em composição
  autorizada. Não existe outra aplicação Firebase, cliente alternativo ou fallback.
- admission_config: AdminAdmissionConfig obtido explicitamente pelo carregador
  existente. Ausência/invalidade impede composição. A chave permanece texto UTF-8,
  versão 1, sem decodificação hexadecimal.
- security_config: AdminRequestSecurityConfig com origens HTTPS exatas. Não há
  domínios provisórios/default de desenvolvimento ou curingas.
- trusted_origin_dependency: callable(request) explícito, conforme router existente.
  Ausência mantém login indisponível (503), sem inferir origem por headers/peer.
- clock: UTC servidor por padrão; injetável para testes com o contrato existente.
- policy: INITIAL_ADMIN_ADMISSION_POLICY por padrão; uma política alternativa
  validada pode ser injetada em testes/composição deliberada. Não há alteração
  automática da política persistida ou dos limites aprovados.

A fábrica revalida configurações e usa o MESMO cliente nos três repositórios:
AdminRepository, AdminSessionsRepository e AdminAdmissionRepository. Monta um
AdminSessionService, AdminAdmissionService, AdminAuthService e AdminLoginService,
e passa as instâncias compartilhadas para create_admin_auth_router. Retorna
AdminHTTPComposition com router e referências aos serviços, sem exposição de
configuração/segredo em repr. Falhas geram AdminCompositionError fixo e sanitizado.

Lifecycle: executar uma vez por aplicação/worker, fora da requisição e preferencialmente
fora do event loop, pois o construtor de autenticação aquece o hash dummy Argon2
existente. Guardar o objeto na composição/lifespan da aplicação e incluir seu
router somente após autorização de publicação. NÃO chamar a fábrica em Depends
por requisição. Não há cache global de objetos/configurações da composição, nem
cache de sessões/permissões. O semáforo Argon2 continua o existente por processo;
instâncias de serviço não criam limites independentes. O dono do cliente permanece
o chamador, responsável por seu encerramento; a composição não fecha um cliente
compartilhado com outros serviços.

As três rotas reutilizam serviços capturados no router: login usa coordenador e
admissão antes de autenticação; GET usa validação existente; logout usa revogação
confirmada antes de remover cookie. Mantêm oito horas absolutas, CSRF, cookies
seguros, erros sanitizados e no-store, sem criação extra/renovação de sessões.

Configurações de teste são fornecidas somente pelo teste, com cliente em memória
ou emulador demo guardado e segredo/origem sintéticos. Aplicações diferentes têm
composições distintas. Não há seleção automática de ambiente ou criação de segredo.
O carregamento real de configuração/cliente é decisão explícita futura; a fábrica
não lê .env nem altera os.environ.

A injeção de callable NÃO atesta a origem. Antes de produção, confirmar a fronteira
Render/Cloudflare e aprovar o provedor; CF-Connecting-IP não é ligado automaticamente.
Também pendentes: segredo real autorizado, origens finais, CORS/HTTPS/same-site,
frontend e inclusão explícita do router. Falha ao compor Admin deve ser contida
na funcionalidade Admin, sem impedir rotas públicas. Nada foi ligado em main,
Netlify, Render, DNS ou Kirvano nesta entrega.
