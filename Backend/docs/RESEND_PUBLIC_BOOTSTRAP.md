# PASSO 97.22 — bootstrap público Resend, somente audiência de teste

A entrada continua `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
Não há segundo backend, novo endpoint, troca de DNS ou ativação Admin.
A alteração prepara o envio; nenhuma flag real foi habilitada nesta etapa.

## Instalação no lifespan

O lifespan público chama prepare_public_welcome antes do instalador existente.
Flag ausente ou PURCHASE_WELCOME_SEND_ENABLED=false retorna imediatamente, sem
ler .env, obter cliente Firebase, criar provedor ou consultar Firestore. Não há
construção por importação. Health e webhook mantêm os contratos comerciais.

Com flag true, o bootstrap carrega SOMENTE o ambiente do processo do serviço e
valida configuração completa, audiência, autorização de teste, corte, recuperação
desligada e projeto esperado. Configuração inválida deixa e-mail unavailable e
preserva health/webhook. Não há fallback para audiência geral ou credencial diferente.

Só depois obtém o cliente Firestore central compartilhado (mesmo loader da Kirvano),
confere projeto, banco (default) e ausência de Emulator/projeto demo/conflito de
projeto. FIRESTORE_EMULATOR_HOST, DATASTORE_EMULATOR_HOST ou FIRESTORE_TEST_PROJECT_ID
presentes impedem esse bootstrap público, inclusive vazios. Revalida após o loader
Firebase, pois ele pode popular o processo por .env. Nenhum RPC é feito para validar
metadados; IAM/projeto real/índices ainda exigem confirmação operacional autorizada.

Configuração aprovada gera WelcomeRuntimeInstallation e a composição existente.
A factory do provedor reutiliza ResendEmailProvider e HTTPX, com TLS normal e retries
zero; construir transporte não envia. A chamada ao provedor continua somente depois
da reserva transacional. Não adiciona dependências: HTTPX já vem com Firebase Admin.

Instalações explicitamente injetadas (testes/entrada administrativa preparada)
continuam sendo respeitadas, sem segunda instalação por ambiente. O ramo Admin não
muda; a app pública possui o lifespan. No shutdown, encerra provedor próprio,
remove a seleção automática e não fecha o Firestore compartilhado. Um novo lifespan
relê as flags; mudar para false não reutiliza configuração automática antiga.

## Variáveis para FUTURA compra autorizada

Manter false agora. Nenhum valor privado foi copiado para este documento.

| Nome exato | Contrato |
| --- | --- |
| PURCHASE_WELCOME_SEND_ENABLED | false agora; true somente após autorização de teste |
| RESEND_API_KEY | Chave privada de envio já configurada no serviço |
| PURCHASE_WELCOME_FROM | Remetente simples canônico já configurado |
| PURCHASE_WELCOME_WHATSAPP_URL | URL oficial wa.me válida já configurada |
| PURCHASE_WELCOME_NOT_BEFORE | Instante ISO-8601 com T e fuso, fixo, escolhido pelo usuário antes da habilitação |
| PURCHASE_WELCOME_AUDIENCE_MODE | **Novo:** exatamente test; ausente, disabled ou all não habilitam envio público |
| PURCHASE_WELCOME_TEST_AUTHORIZED | **Novo:** exatamente true para autorização específica da audiência de teste |
| PURCHASE_WELCOME_TEST_RECIPIENT | **Novo, privado:** único e-mail autorizado, normalizado pelo validador existente |
| FIREBASE_PROJECT_ID | Variável já existente no projeto, agora obrigatória para este bootstrap; ID esperado do mesmo projeto da Kirvano |
| PURCHASE_WELCOME_RECOVERY_ENABLED | false; true é rejeitado no bootstrap público deste passo |

O projeto esperado confirmado anteriormente é portaldominandoanimacao-db, banco
(default). Isso não substitui a credencial Firebase existente. Variáveis alternativas
GOOGLE_CLOUD_PROJECT/GCLOUD_PROJECT/GCP_PROJECT presentes devem coincidir. Não modificar
FIREBASE_CREDENTIALS_JSON/PATH nem os segredos comerciais para habilitar Resend.
O batch size antigo não habilita recuperação e não precisa ser ajustado neste teste.

As três novas variáveis são AUDIENCE_MODE, TEST_AUTHORIZED e TEST_RECIPIENT. A última
é dado privado e não deve aparecer em logs, commits ou screenshots compartilhados.
Não há variável de preço/oferta nova: continuam elegíveis as ofertas mensais válidas
do produto autorizado, mas somente a identidade de teste poderá receber neste modo.
Usar no checkout exatamente o e-mail autorizado (mesma política de normalização).

## Audiência em todos os caminhos

PurchaseWelcomeConfig carrega uma WelcomeAudience imutável com valor privado.
Ausência de audiência é DENY. A configuração do serviço vincula audiência e corte
a uma nova instância do repositório; não modifica uma instância compartilhada para
trocar permissões de outro dispatcher. A reserva transacional verifica recipient
normalizado ANTES de permitir in_progress. Não basta filtrar o HTTP ou a fila.

Assim, after_event, BackgroundTasks, dispatch(id), reserva direta desse repositório
e recover_pending não contornam a audiência. Chamada sem corte temporal efetivo
não obtém reserva. Um argumento com corte anterior não reduz o corte vinculado
na configuração: usa o mais restritivo. Repositório sem política explícita não
permite despacho. Finalização de tentativa existente continua com fencing por
attempt_id, sem reabrir aceitação ou incerteza.

Compras dos demais compradores continuam persistidas e respondidas normalmente.
Suas intenções permanecem pending, sem reserva ou envio. São dados comerciais
válidos, não falhas que devam ser apagadas ou automaticamente repetidas.

## Corte: pagamento E timestamps do servidor

As verificações, no snapshot transacional da reserva, exigem:
1. transactional_emails.created_at >= corte;
2. purchases.created_at >= corte;
3. purchases.valid_from >= corte;
4. purchases.valid_from <= agora da execução no Backend.

valid_from já deriva de payment.finished_at, validado no webhook autenticado e
convertido para UTC pelo classificador comercial. created_at são os timestamps
server-side do commit. Portanto, uma venda antiga recebida/reprocessada hoje não
passa só porque criou uma intenção hoje. Campos ausentes, inválidos, sem fuso,
inconsistentes ou com pagamento futuro impedem envio; erro de dados/I/O falha seguro.

Não consultamos o relógio do navegador. A confiança no horário comercial depende
do payload autenticado e da configuração correta de KIRVANO_WEBHOOK_TIMEZONE,
já exigida pelo Backend. Não há consulta ao catálogo ou histórico do provedor para
inventar uma data ausente; ausência de evidência não autoriza envio. Não escolhemos
corte real nem alteramos timestamps históricos neste passo.

## Intenções excluídas e liberação geral futura

Não habilitar recuperação no primeiro teste. Ela permanece disponível como mecanismo
interno e também respeita a política, mas não é disparada por esse bootstrap.
Intenções excluídas não devem ser escoadas retroativamente ao liberar o produto.

O modelo de audiência possui a modalidade all para evolução interna/testes, mas o
loader de ambiente a REJEITA neste passo. Não é possível trocar apenas a variável
para all e enviar para todos. Uma liberação geral exigirá autorização posterior,
alteração explícita/revisada desse gate e um NOVO corte de início escolhido pelo
usuário. Os três timestamps acima impedem mensagens de compras anteriores ao novo
início. Intenções antigas ficam pendentes/arquiváveis por política futura explícita,
sem reenvio automático, alteração de compra ou reset de reservas.

Antes de futura recuperação, revisar consulta/índices e tratamento de pending
excluídas; uma consulta limitada que encontre sempre intenções fora da audiência
pode não avançar no backlog. Isso não afeta o teste atual com recuperação desligada.
Não prometer drenagem contínua durante suspensão do Render ou exactly-once.

## Preservação e testes

Nenhuma regra comercial, autenticação de webhook, HTML aprovado, ativação manual,
assinatura ou deduplicação foi alterada. Renovação/cancelamento/reembolso/chargeback
continuam sem boas-vindas adicionais. O provedor aceita ou leva a revisão; timeout,
rede e commit incerto não provocam retry cego nem confirmação de entrega.

A ferramenta local de teste continua exigindo flags globais false, Emulator e
registro durável. Vincula a audiência ao destinatário privado preparado. Somente
seu payload SINTÉTICO passou a usar pagamento no instante da preparação, em vez
de ontem, para cumprir o novo corte. Não foi executado --send-once novamente nem
alterado operation.json. Templates e credenciais reais permanecem intactos.

Testes antigos de Emulator foram ajustados para pagamentos realmente recentes,
com corte sintético anterior, preservando IDs próprios e cleanup não destrutivo.
Datas fixas de outubro não representam mais um teste válido de compra recente.
A nova suite cobre bootstrap false/incompleto/inválido, modo geral bloqueado,
audiência em cada caminho, reinício com flag false, compra antiga processada agora,
corte que não pode ser afrouxado, oferta mensal alternativa, outro produto, nome,
repetição e timeout sem reversão comercial. Provedores exclusivamente falsos.

Uma execução inicial unitária encontrou que o fake de memória não aceitava get com
timeout fora de transação; corrigido o adaptador de teste, sem afrouxar o código real.
Nenhuma chamada real de Resend/Kirvano, compra real ou ativação foi realizada.

Resultados finais: **1672 testes Backend e 52 subtestes aprovados**, incluindo 32
novos cenários unitários; **39 testes Emulator aprovados**, incluindo 6 novos de
audiência/corte e 33 regressões. 290 cenários Emulator foram desmarcados na suíte
unitária; à parte executamos apenas os arquivos isolados explicitamente selecionados.
Nenhuma falha final; aviso preexistente do TestClient. `git diff --check` sem problemas.
Não foram alterados .env, template aprovado, operação local, Render ou DNS.
