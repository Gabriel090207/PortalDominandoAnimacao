# Coordenação interna de admissão e autenticação

AdminLoginService recebe AdminAdmissionService e AdminAuthService por injeção.
Não configura clientes Firebase, políticas, segredos, relógios ou variáveis de
ambiente. A composição futura deve instanciar os serviços uma vez por worker;
o aquecimento do hash dummy ocorre na construção da autenticação, não durante
uma tentativa negada.

Cada authenticate(trusted_origin, email, password) executa admit_attempt primeiro.
Somente uma decisão ALLOWED confirmada permite chamar AdminAuthService. A
transação dos dois buckets já terminou nesse momento; nenhuma transação de
admissão envolve Argon2 ou criação de sessão. A sessão continua usando suas
próprias verificações transacionais existentes. Nenhuma credencial é enviada ao
repositório de admissão.

E-mails válidos mantêm normalização e IDs existentes. E-mails inválidos usam um
bucket opaco compartilhado por origem e um escopo HMAC reservado, sem armazenar
a entrada malformada ou criar um bucket por valor inválido. Também consomem o
bucket geral da origem. Depois da admissão, a autenticação existente executa a
verificação dummy e retorna InvalidAdminCredentials sem consultar admins.

Resultados internos:

- InvalidAdminCredentials: falha genérica, sem revelar existência ou status.
- AdminLoginLimited: mensagem fixa e retry_after_seconds da política existente.
- AdminAdmissionUnavailable: origem/configuração/armazenamento inválido ou
  resultado incerto; nenhuma autenticação é executada.
- AdminAuthenticationUnavailable: falha interna posterior à admissão, incluindo
  capacidade Argon2 indisponível, corrupção ou falha de criação de sessão.

Não há devolução de capacidade, reset no sucesso, bloqueio de conta ou retentativa
externa. Um commit de admissão sem confirmação pode consumir capacidade, mas não
libera autenticação. As retentativas transacionais internas do SDK são mantidas.
Duas instâncias compartilham os mesmos buckets quando usam política, chave,
versão e origem canônica iguais. O limite Argon2 continua sendo por processo;
contenção pode falhar fechada e não garante atendimento de todas as chamadas.

O coordenador não interpreta headers nem atesta a origem. A fronteira de confiança
do Render ainda exige confirmação operacional antes de conectar CF-Connecting-IP.
Não há endpoint, cookies, configuração de produção ou ativação automática.
Antes do login HTTP: aprovar limites, fornecer segredo HMAC dedicado com plano de
rotação, sincronizar relógios e definir retenção/TTL/custos. A camada HTTP deverá
usar o coordenador em todas as tentativas, fora do event loop, e mapear erros
para respostas genéricas sem registrar credenciais, tokens, hashes ou origem.

Testes: tests/test_admin_login.py e tests/emulator/test_admin_login_integration.py.
Os testes de emulador usam exclusivamente as fixtures existentes, projeto demo,
credenciais anônimas e endpoint loopback com validações anteriores à conexão.
