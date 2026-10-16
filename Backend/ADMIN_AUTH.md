# Autenticação administrativa interna

AdminAuthService recebe AdminRepository e AdminSessionService por injeção.
Nenhum construtor inicializa Firebase. Não há endpoint, cookies, frontend,
logout HTTP, gerenciamento de administradores ou alterações no bootstrap.

`authenticate(email, password)` normaliza o e-mail pela política existente,
consulta o administrador, verifica a senha com verify_admin_password e exige
administrador habilitado. Após sucesso, chama o serviço existente de sessões,
que relê estado e auth_version em transação. Retorna IssuedAdminSession, cujo
token permanece em SecretStr. Não altera papel, permissões, hash ou administrador.
A autorização continua separada, pela matriz de permissões existente.

AdminRepository.find_by_email usa igualdade em email_normalized com limit(2),
sem listar toda a coleção e sem depender de novo índice de identidade. Funciona
com o owner provisionado e com futuros operators. Exige AdminRecord válido,
ID do documento igual ao admin_id e e-mail correspondente. Se detectar dois
resultados, falha fechada: não escolhe um deles nem tenta verificar ambas senhas.
Essa consulta detecta duplicidades; NÃO constitui restrição única de escrita.
Futuros fluxos de criação/alteração devem garantir unicidade transacional. Eles
não fazem parte desta etapa e não houve migração ou alteração em produção.
O índice simples do campo deve estar habilitado no Firestore; falha de índice
ou permissões é tratada como indisponibilidade, nunca credencial incorreta.

InvalidAdminCredentials tem mensagem única para e-mail inválido/inexistente,
senha incorreta ou fora da política e conta desabilitada. Para e-mail inexistente
ou inválido, usa verificação de hash fictício Argon2id com a política atual.
Entrada de senha rejeitada pela política recebe uma verificação fictícia adicional
porque verify_admin_password a rejeita antes do trabalho criptográfico. Conta
desabilitada também passa pela verificação de senha. O hash fictício é preparado
na construção, compartilhado por cache por processo e não autentica ninguém.
Senhas de entrada nunca ficam armazenadas no serviço.

Isso reduz a diferença principal de custo criptográfico, mas NÃO garante tempo
constante de ponta a ponta: rede, índice, cache e hashes antigos com parâmetros
diferentes variam. E-mail sintaticamente inválido não consulta o banco. Não há
sleep artificial, rehash automático nem consultas extras para simular latência.

AdminAuthenticationUnavailable distingue falhas internas de credenciais inválidas:
hash/documento corrompido, duplicidade, rede/Firestore, Argon2 ou criação de sessão.
As mensagens são fixas e não incluem exceção bruta, e-mail, senha, hash, token ou
credencial. Não registrar errors() de validação, documentos ou variáveis locais.
Hash malformado normalmente é rejeitado ao carregar AdminRecord, antes da senha.
Falha de persistência não é repetida automaticamente; commit sem resposta pode
deixar uma sessão não entregue ao cliente, que continua sujeita à expiração.

Próxima integração HTTP depende obrigatoriamente de proteção contra tentativas
excessivas e limite de concorrência para Argon2 ANTES de chamar este serviço.
Não existe proteção de tentativas persistida nesta entrega interna. Reutilizar
uma instância por worker, executar trabalho síncrono fora do loop assíncrono e
adicionar política de cookies/CSRF e transporte seguro na etapa apropriada.
Não publicar endpoint somente por conectar este serviço.

## Capacidade local das verificações Argon2id

verify_admin_password utiliza um BoundedSemaphore compartilhado pelas threads
do processo, com limite conservador de UMA verificação Argon2id por vez. O custo
atual permanece m=19456 KiB (19 MiB), t=2, p=1. Não houve benchmark da hospedagem;
hashes antigos podem exigir mais recursos dentro dos limites já aceitos pelo
validador (até 256 MiB). Nenhum parâmetro ou hash persistido foi alterado.

A aquisição é não bloqueante: sem capacidade, não há espera, fila ou repetição.
AdminPasswordVerificationUnavailable é erro interno sanitizado; a autenticação
o converte em AdminAuthenticationUnavailable, nunca em senha incorreta.
A capacidade é liberada em finally, inclusive em falhas ou interrupção do
verificador. Senhas incorretas continuam retornando False na camada criptográfica.
Verificações reais, fictícias e de fallback compartilham o mesmo limite, inclusive
entre diferentes instâncias do serviço no mesmo processo. Os hashes fictícios
são aquecidos na construção por worker; geração de hashes/provisionamento não
foi alterada e não está abrangida por este limite de VERIFICAÇÃO.

O fluxo continua síncrono. Ainda não há chamada HTTP administrativa; quando
integrada ao FastAPI, executar a autenticação fora do event loop. A consulta por
e-mail termina antes de verificar a senha, e a transação de sessão só começa
depois da verificação e da liberação da capacidade. Não se mantém transação
Firestore aberta esperando ou executando Argon2.

Cada processo/instância tem seu próprio semáforo: N workers podem verificar N
senhas ao mesmo tempo. Orçar memória/CPU pelo total de workers e medir a carga
antes de aumentar o limite. Esse controle não é rate limiting, não coordena
instâncias, não bloqueia contas e não substitui proteção distribuída contra
tentativas excessivas, que deverá anteceder a autenticação no futuro endpoint.

Testes: tests/test_admin_auth.py e tests/emulator/test_admin_auth_integration.py.
Integração usa apenas a fixture guardada existente, AnonymousCredentials,
127.0.0.1:8080 e demo-dominando-animacao-test; nunca inicializa Firebase real.

Na validação desta etapa, os sete cenários de autenticação passaram. A regressão
adicional de sessões apresentou uma falha intermitente na revogação concorrente
(Session revocation failed); a reexecução isolada passou sem mudança de código.
A causa interna não foi determinada. Esse comportamento merece investigação na
camada de sessões antes de publicar o fluxo HTTP; não foi mascarado por retries
de autenticação nem tratado como senha incorreta.
