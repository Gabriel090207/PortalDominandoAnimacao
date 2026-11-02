# PASSO 87 — entrada administrativa preparada, não publicada

Nota posterior (PASSO 88): a modalidade de ingresso verificado descrita aqui
foi preservada. A factory também aceita uma configuração distinta de API pública
autenticada; ver ADMIN_PUBLIC_API.md. Isso não autentica headers nem habilita
produção automaticamente.

## Arquitetura

app/admin_entrypoint.py fornece create_admin_entrypoint. Não exporta app global,
não é carregado por app.main, não lê variáveis/.env, não inicia Firebase e não
seleciona ingressos automaticamente. É preparação de código para o MESMO serviço
Render, não um segundo backend hospedado. O Start Command real não foi alterado.

A factory devolve um dispatcher ASGI:

- /admin e /admin/* são enviados exclusivamente ao ramo administrativo.
- Demais caminhos e lifespan são delegados à aplicação pública existente,
  normalmente app.main.app. /administrator não é prefixo administrativo.
- A aplicação pública não recebe routers Admin nem o CORS administrativo.
- Uma composição é construída por chamada à factory, para reutilização por worker;
  não por requisição. Criar fora do event loop, pois aquece Argon2 dummy.

Padrão: create_admin_entrypoint() conserva a aplicação pública e devolve 503 com
mensagem fixa e no-store para TODO o ramo Admin. WebSocket Admin é fechado sem
acesso a operações. Não há login, dependência de sessão ou consulta ao Firestore
nesse ramo desabilitado. Não há docs/OpenAPI administrativos acessíveis.

## Configuração explícita e bloqueio de produção

Para compor um ramo sintético é necessário AdminEntryConfiguration completo:

- firestore_client já fornecido e de ciclo de vida controlado pelo chamador;
- AdminAdmissionConfig existente com segredo válido e key_version suportado;
- AdminRequestSecurityConfig existente com origens HTTPS exatas;
- ComplementaryAdminAdmissionPolicy validada, escolhida explicitamente;
- ingress_verifier callable, cuja implementação/procedência precisa ser aprovada.

Usar load_admin_admission_policy(selection='complementary-local-v1') nos testes
para a referência 10/5/5/20, com reposições 1/30, 1/60, 1/60 e 1/30 segundos.
Não há política/segredo/origem/cliente default de produção. Os quatro controles
reutilizam compose_admin_http, serviços e repositórios existentes. Perfil inválido,
política de dois buckets ou qualquer dependência obrigatória ausente desabilitam
a composição inteira, sem rotas parcialmente expostas. Não há fallback para
apenas dois buckets quando a configuração complementar falha.

O chamador permanece responsável por fechar o cliente Firestore quando apropriado.
O dispatcher delega lifespan à aplicação pública; não fecha cliente compartilhado
com Kirvano. Validações de interface não fazem RPC nem provam projeto, database,
IAM, índices, ausência de emulator, disponibilidade ou propriedade da credencial.
Essas verificações operacionais continuam obrigatórias antes de produção.

Não existe um provedor de ingresso Render implementado/aprovado. A factory NÃO
oferece uma flag que passe a confiar em CF ou permita habilitação por ambiente.
Ela oferece somente injeção de código explícita, como os contratos existentes.
Uma função lambda que retorna um IP é uma premissa SINTÉTICA nos testes, não uma
implementação segura de produção. Injetar resolve_cf_connecting_ip diretamente
como prova de ingresso NÃO é uma configuração aprovada.

## Contrato do verificador de ingresso

Antes de QUALQUER operação administrativa, o guard exige scheme HTTPS e chama
verifier(request), síncrono em threadpool ou async. O verificador aprovado futuro
deve comprovar sua fronteira e devolver a origem de rede que ela atesta; na falta
de garantia deve lançar erro/recusar. Não deve consumir o corpo de requisição
sem preservar o stream para o handler, nem persistir/logar dados sensíveis.

O guard valida/canonicaliza o resultado usando o parser IP existente e o guarda
somente num campo interno do scope durante a requisição. Esse campo é removido
antes da verificação e ao terminar a chamada. A dependência de login lê somente
essa informação produzida pelo guard. Headers não preenchem esse campo.
Não há fallback para CF, XFF, X-Real-IP, Origin, Host, RENDER=true ou request.client.
Falha/valor ausente/malformado retorna 503 sanitizado antes do armazenamento.
Essa validação sintática da saída não é atestação criptográfica.

O controle de HTTPS em scope não autentica o proxy que o preenche. Um futuro
verificador precisa considerar o tratamento de X-Forwarded-Proto pelo Uvicorn e
caminhos alternativos de ingresso. Nenhuma confiança deve ser inferida da presença
desse scheme ou header. A pendência Render continua real e impede publicação.

## CORS, cookies e proteções

A factory CORS administrativa existente envolve apenas o ramo Admin. Preflight
para origem/método/headers permitidos não autentica nem cria sessão ou chama
verificador/Firestore; é negociação do navegador, sem acesso a lógica de negócio.
Requisições efetivas passam pelo guard. Origem não autorizada continua recusada
pelos contratos existentes; CORS não autentica cliente HTTP externo.

O CORS externo permite que erros de ingresso recebam headers da origem aprovada.
A configuração CORS pública original permanece somente no app público e não é
empilhada sobre o ramo Admin. Nada é aplicado globalmente a /webhooks/kirvano.

Reutilizados sem alteração: Argon2id e semáforo, admissão antes da senha, sessão
absoluta de oito horas, __Host-admin_session Secure/HttpOnly/SameSite=Lax/Path=/
sem Domain, validação de versão/status/vínculos, Origin exato, X-Admin-Request,
CSRF, permissões, confirmações explícitas e auditoria. Cookies não têm configuração
relaxável nesta entrada; seus atributos continuam fixos no helper existente.
Não há renovação automática, reset de bucket ou sucesso em commit incerto.

## Kirvano e aplicação pública

O dispatcher delega a aplicação pública por referência e não reimplementa seu
webhook, health, CORS ou tratamento comercial. Nenhum corpo/header público é
reescrito pelo ramo Admin. Falha na composição Admin não bloqueia essas rotas.
app.main permanece intacto, com raiz/health/Kirvano e sem routers administrativos.
Não foram criados novos endpoints de clientes ou alterada elegibilidade comercial.

## Ativação e rollback futuros — não executados

Apenas importar esta factory não ativa nada. Antes de considerar um entry point
ASGI de produção, aprovar ingresso e implementar o verificador correspondente,
configurações/cliente reais autorizados, hosts, HTTPS/CORS/cookies, política
uniforme e transição de buckets conforme ADMIN_ADMISSION_CONFIGURATION.md.
Não há comando de ativação de produção pronto/aprovado nesta entrega.

Rollback seguro: manter/voltar ao entry point público atual ou compor sem
AdminEntryConfiguration. Isso retira o ramo Admin sem remover documentos,
reabrir bootstrap, girar chave, alterar sessões ou modificar Kirvano. Rollback de
configuração de buckets não autoriza reset: incompatibilidades exigem procedimento
coordenado separado. Não encerrar serviços reais para executar os testes locais.

## Validação

Testes em TestClient e armazenamento em memória existentes, sem RPC/Firebase real.
Verificador é sintético, lookup de admin é mockado; senha/sessões/admissão usam
implementações reais em transações fake. Não é prova de fronteira Render, TLS
real, IAM/índices ou contenção Firestore. O novo dispatcher não altera transações;
Emulator não é necessário para esta mudança e não foi acessado.

Cobertura: padrão/ausência/configuração inválida, ausência/erro de ingresso,
headers não atestados, isolamento do prefixo, HTTPS obrigatório, CORS/preflight,
Origem recusada, política explícita, cookie, CSRF, login/sessão/logout, falha de
admissão antes da autenticação, sessão válida ainda bloqueada sem ingresso,
threadpool/async, importação inerte, aplicação pública e webhook preservados.
Nenhum serviço real, DNS, Start Command, credencial, Admin/Frontend, servidor
local ou integração comercial foi alterado. Nada publicado. Não iniciar PASSO 88.

Resultados executados: 22 novos testes aprovados; conjunto específico 319
aprovados; suíte completa 1.363 aprovados e 52 subtestes aprovados, 228 testes
Emulator desselecionados. Nenhuma falha. Aviso existente de depreciação
TestClient/httpx; nenhuma dependência instalada. Contagens se sobrepõem.
git diff --check passou e git diff de app/main.py permaneceu vazio.

Arquivos criados nesta etapa: app/admin_entrypoint.py,
tests/test_admin_entrypoint.py e este documento. Nenhum arquivo existente foi
modificado; alterações locais anteriores preservadas.
