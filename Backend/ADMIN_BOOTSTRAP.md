# Provisionamento interno do primeiro owner

Esta ferramenta não faz parte da API e não oferece cadastro público. Não foi
executada em produção durante a implementação.

Quando uma execução real for autorizada, a partir de Backend, em terminal:

```sh
ADMIN_BOOTSTRAP_ENABLED=true .venv/bin/python -m app.tools.provision_admin --bootstrap --project-id ID_DO_PROJETO
```

As credenciais são carregadas pelo serviço Firebase existente. Use uma identidade
operacional autorizada e confirme o projeto exibido. A senha é solicitada duas
vezes sem eco; não há opção de senha por argumento ou variável de ambiente.
O opt-in deve ser temporário, somente no processo, nunca permanente na hospedagem.

Após verificar o opt-in e o terminal, a ferramenta carrega Backend/.env com
override=False, preservando as variáveis já presentes no processo. Antes de
qualquer confirmação interativa ou inicialização Firebase, rejeita a presença
de FIRESTORE_EMULATOR_HOST, DATASTORE_EMULATOR_HOST ou FIRESTORE_TEST_PROJECT_ID
no ambiente efetivo, inclusive valores vazios. A mensagem não revela seus valores.
O .env não pode habilitar o opt-in: ele é verificado antes do carregamento.
Essa proteção pertence somente à ferramenta definitiva; o serviço e as transações
continuam disponíveis para os testes isolados que utilizam o emulador.

O e-mail segue a normalização existente e a senha usa o serviço Argon2id existente.
O registro usa AdminRecord sem alterar seus contratos: enabled, owner,
auth_version=1, timestamps UTC e created_by="bootstrap". Esse valor já é utilizado
nos testes do domínio; representa a origem operacional, não outro administrador.
O ID do novo administrador é um UUID, nunca o identificador reservado bootstrap.

Uma única transação lê o marcador admin_bootstrap/first_owner_v1 e verifica que
admins está vazia; então cria o administrador e o marcador. Usa somente create,
sem sobrescrever documentos. Competições pelo marcador são resolvidas pelas
transações Firestore; só um provisionamento pode concluir, mesmo com e-mails
diferentes. Isso também impede duplicação de um mesmo e-mail nesta ferramenta.
Qualquer administrador preexistente, inclusive desabilitado ou legado, impede
o bootstrap. Não existe criação administrativa geral nesta etapa.

O marcador registra operação, administrador, origem e timestamp do servidor,
sem e-mail, senha ou hash. Não é uma auditoria geral nem identifica a pessoa
que executou o comando; essa atribuição depende dos controles operacionais.
Nunca apague/reset esse marcador para criar outro owner. Excluir ou desabilitar
o primeiro owner não reabre o bootstrap. Credenciais com acesso direto ao banco
podem contornar controles da aplicação e devem permanecer restritas.

Falhas são sanitizadas. Em falha de comunicação durante commit, o resultado pode
ser incerto: confira o estado por acesso interno confiável antes de repetir. Um
commit concluído continua protegido pelo marcador, mesmo sem confirmação local.

Não há login, sessão, recuperação, frontend, alteração de clientes ou mudanças
comerciais nesta entrega. Futuros caminhos de criação de administradores devem
adotar unicidade transacional própria; este bloqueio permite somente o primeiro.

## Validação isolada no Firestore Emulator

Os testes específicos estão em tests/emulator/test_admin_bootstrap_integration.py.
Reutilizam a fixture existente: projeto fixo demo-dominando-animacao-test,
127.0.0.1:8080, AnonymousCredentials, bloqueio de inicialização Firebase e limpeza
da base sintética antes/depois de cada cenário. Não execute suítes simultâneas.
Não usam a ferramenta de provisionamento real nem leem credenciais privadas.

Com o emulador local disponível, dentro de Backend:

```sh
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test .venv/bin/python -m pytest --run-firestore-emulator -q tests/emulator/test_infrastructure.py tests/emulator/test_admin_bootstrap_integration.py tests/test_emulator_guards.py
```

Cobertura: contrato AdminRecord, hash Argon2id, mesmo commit para owner/marcador,
repetição, concorrência com e-mails iguais/diferentes, aborto antes do commit,
falha de precondição no commit real, marcador sem owner, administrador legado e
ausência de senha/hash na saída capturada e nas mensagens de erro.

Se o Firebase CLI não estiver disponível mas o JAR do emulador já estiver
instalado, ele pode ser iniciado diretamente com Java 21, sem instalar ferramentas:

```sh
java -jar /CAMINHO/DO/cloud-firestore-emulator.jar --host 127.0.0.1 --port 8080 --project_id demo-dominando-animacao-test --single_project_mode true --single_project_mode_error true
```

O caminho deve apontar para um JAR já existente; não baixe dependências
automaticamente. Encerre o processo ao terminar. Essas validações não autorizam
nem executam o provisionamento definitivo.
