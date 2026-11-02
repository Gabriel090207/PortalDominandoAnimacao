# PASSO 97.13 — teste local de uma única operação

A ferramenta `app.tools.test_purchase_welcome` está preparada. **Nenhum modo de
ENVIO ÚNICO foi executado nesta etapa.** Não há autorização para envio real ainda.
O template aprovado não foi modificado.

## Pré-requisitos privados

- `Backend/.env` com chave, remetente e WhatsApp válidos pelos validadores existentes.
- Manter `PURCHASE_WELCOME_SEND_ENABLED=false` e
  `PURCHASE_WELCOME_RECOVERY_ENABLED=false`, no arquivo E no ambiente do processo.
- Emulator já em execução em `127.0.0.1:8080`, projeto
  `demo-dominando-animacao-test`, banco `(default)`.
- Informar explicitamente o corte ISO-8601 com fuso. Não há horário default.
- Criar MANUALMENTE `Backend/credentials/resend-test-recipient.txt` no editor local,
  com somente o endereço do destinatário autorizado. Não compartilhar no chat,
  não colocar no código, argumentos ou histórico de comandos. Depois restringir:

```sh
chmod 600 Backend/credentials/resend-test-recipient.txt
```

A ferramenta não cria esse arquivo nem escolhe comprador ou destinatário. Arquivos
fora de credentials, links simbólicos, arquivos de outro proprietário ou com acesso
para grupo/outros são rejeitados. `credentials/` já está ignorado pelo Git.
Não foi alterado o .env nem criado um arquivo com destinatário real nesta etapa.

## Preparação futura — sem envio

Da raiz do projeto, após escolher explicitamente o instante do início autorizado:

```sh
cd Backend
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 \
FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test \
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.tools.test_purchase_welcome \
  --prepare --not-before 'INSTANTE_ISO8601_COM_FUSO_ESCOLHIDO_PELO_USUARIO'
```

O texto entre aspas é PLACEHOLDER: substitua pelo instante escolhido, não execute
literalmente. A ferramenta exige `T` e fuso e rejeita corte posterior ao momento da
preparação. Se PURCHASE_WELCOME_NOT_BEFORE já estiver no arquivo/ambiente, deverá
corresponder ao argumento (comparação pelo instante). Não o grava nem altera .env.
O valor efetivo é registrado como `not_before` no arquivo privado da operação.

Usa os geradores/classificadores e a transação comercial EXISTENTES. A única
extensão no helper de payload local permite passar e-mail e sale_id exclusivos,
sem mudar os defaults ou a lógica Kirvano. Não faz requisição de webhook, compra
real ou consulta a compradores. Cria grafo sintético e intenção pending dentro de:

`resend_test_operations/<UUID exclusivo>/<coleção>/<documento>`

TODAS as coleções são direcionadas para esse namespace, incluindo usuários,
identidades, inbox/variante, compra, assinatura, entitlement e transactional_emails.
Não escreve nas coleções raiz dos clientes/administradores de homologação.
Cliente SDK usa explicitamente AnonymousCredentials e endpoint loopback, sem
Firebase Admin, ADC, service account ou credenciais de produção. Revalida projeto,
banco e vínculo Emulator no cliente antes de acessar qualquer coleção.

A preparação rende o MESMO HTML/texto aprovado para gerar um digest. Não instancia
adapter vivo, não chama Resend, não instala runtime nem inicia recuperação. Nome
sintético: Cliente Exemplo. A ativação permanece pending.

## Registro durável e trava

Uma única operação local em `Backend/credentials/resend-test/operation.json`.
Não aceita caminho alternativo de operação pelo CLI e NÃO substitui registro
existente ao executar --prepare novamente. Locks entre processos usam
`operation.lock`, inode estável separado do JSON. Atualizações usam arquivo
provisório próprio, fsync, substituição atômica e fsync do diretório.

Diretório privado 0700, arquivos 0600, proprietário atual, sem symlinks. Registra
UUID, IDs determinísticos, corte, hashes de destinatário/payload, estado e ID do
provedor quando conhecido. Não guarda chave, número WhatsApp, destinatário completo
ou resposta bruta. Hash não equivale a criptografia: mantenha os arquivos privados.
Todos esses caminhos estão ignorados pelo Git.

Estados locais: preparing, prepared, attempt_started, accepted, requires_review.
A transação comercial continua com seus estados existentes e não é duplicada.
O registro preparing é gravado ANTES dos writes no Emulator: preparação interrompida
não é silenciosamente repetida. Registro incompleto exige inspeção, não reset.

## ENVIO ÚNICO futuro — não executar agora

Somente após autorização explícita, no mesmo diretório Backend:

```sh
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 \
FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test \
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.tools.test_purchase_welcome \
  --send-once --confirm-single-send
```

Não informar novo corte no envio: usa o já preparado. Por padrão lê o mesmo arquivo
de destinatário. `--recipient-file` permite selecionar outro arquivo privado dentro
de credentials, mas o e-mail normalizado DEVE coincidir com o hash da preparação.
Não há opção para e-mail livre, assunto, corpo, remetente ou intenção arbitrária.

Antes do provedor: revalida flags, configuração, destinatário, namespace, existência
exata da intenção pending, vínculo da compra, corte e digest do payload. Mudança de
remetente, WhatsApp ou template após preparação bloqueia a operação. Se o Emulator
perdeu os documentos, NÃO os recria no envio. Não varre filas ou processa históricos.

Grava `attempt_started` com durabilidade ANTES de construir o provedor e tentar a
reserva. Só então chama o dispatcher existente com o ID fixo e o corte persistido.
O adapter é o Resend existente com transporte explícito, TLS validado, sem redirects
ou retries de transporte. Mesma chave idempotente por intenção. Uma chamada interna
manual possui config.enabled=True somente em memória: não modifica flags globais,
os.environ ou .env, e nunca instala runtime público ou recuperação.

Accepted grava ID do provedor e bloqueia repetição; aceitação não comprova entrega.
Timeout/rede/resultado inesperado/falha de persistência ou processo interrompido
mantêm a trava local. Se o resultado final não puder ser escrito, o marcador anterior
attempt_started continua bloqueando. Nenhum envio é repetido automaticamente, mesmo
após reinício do processo, reset do Emulator ou passagem de 24 horas. Essa política
é conservadora: até uma falha ANTES do HTTP pode exigir revisão e impedir nova tentativa.

**Limitações:** o diretório local é parte da garantia. Excluir/restaurar/editar o
registro para estado anterior pode eliminar a proteção; não fazer isso, não usar
outro computador nem copiar a chave para contornar a trava. Permissões protegem de
outros usuários, não do proprietário/root. Não existe atomicidade única entre disco,
Firestore e API externa nem garantia de entrega exactly-once. Incerteza requer
reconciliação autorizada no Resend e inspeção do estado, não outra tentativa. Não
foi criado comando de reset, reenvio ou reconciliação que chame a API.

## Testes desta etapa

Testes usam configuração sintética em diretório temporário, destinatários fictícios
GERADOS, cliente de memória que simula o Emulator e provedor falso. Não foi executado
CLI --send-once; a função interna foi exercitada apenas com fake injetado. Nenhuma
conexão de rede, Emulator em uso, API real ou dados do usuário foram necessários.
Testes de subprocesso comprovam a trava por arquivo e leitura do registro após
recriação do interpretador. Não houve limpeza global de arquivos ou banco.

Resultados: **36 novos cenários da ferramenta** e **187 testes direcionados ao todo
aprovados**, sem falhas. Incluem regressões do helper local, template, dispatcher,
trigger e runtime. Um aviso preexistente do TestClient. `git diff --check` limpo.
Foi executado somente `--help` no CLI real; preparação/envio foram exercitados em
funções automatizadas com configuração sintética, armazenamento simulado e fake.

Não fechar/reiniciar servidores locais. Não fazer commit, push, deploy ou próximo
passo sem nova instrução. Antes do primeiro envio real, revisar a operação preparada,
confirmar destinatário, corte e autorização novamente.
