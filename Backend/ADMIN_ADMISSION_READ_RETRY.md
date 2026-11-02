# PASSO 91 — recuperação direcionada de Aborted de leitura

## Causa e escopo

O SDK instalado google-cloud-firestore 2.34.0 executa o callback (_pre_commit)
fora do try que repete Aborted de commit. Um Aborted propagado por uma leitura
pode sair depois de um único begin/rollback. Esse caminho foi comprovado no
PASSO 90; a causa específica da execução histórica do PASSO 89 não foi comprovada.
A correção cobre esse caminho conhecido, não promete resolver toda contenção.

Inspecionados ADMIN_ADMISSION_CONCURRENCY.md e a evidência JSON, serviço,
repositório/modelo, composição, testes/fakes/fixtures de diagnóstico e SDK local.
Não altera política 10/5/5/20, Argon2, sessões, cookies, CSRF, permissões, auditoria,
Kirvano ou comportamento comercial. Nenhuma aplicação foi publicada/ativada.

## Prova de fase antes de repetir

O bloco de leitura do callback captura SOMENTE google.api_core.exceptions.Aborted.
Um estado de progresso por ciclo SDK registra se algum callback daquele ciclo já
terminou TODAS as leituras. Esse estado é sticky: não é apagado quando o SDK
reexecuta o callback após Aborted de commit.

- Antes de completar a primeira série de leituras, não houve evaluate_buckets,
  buffer_create/update nem retorno do callback. No SDK inspecionado, commit só
  acontece após o retorno do callback: logo ainda não houve tentativa de commit.
- Somente nessa condição a captura direta de Aborted emite um sinal privado de
  conflito de leitura antes de progresso.
- O SDK precisa fazer rollback e devolver esse sinal ao repositório. Se rollback
  falhar com outra exceção, ela não é classificada e não recebe retry externo.
- Ao terminar as leituras, o estado é marcado ANTES de avaliação ou escrita. A
  partir daí não há recuperação externa desse ciclo, inclusive se um callback
  posterior falhar lendo após uma tentativa nativa de commit.

É uma condição conservadora: não precisa inferir fase a partir do texto ou da
cadeia de uma exceção genérica, nem acessar detalhes privados de transporte.
A prova usa a ordem de operações do próprio callback e o fluxo do SDK instalado.
O estado é local à chamada/ciclo, não global ou compartilhado entre threads.

## Limite e relógio

Uma tentativa adicional, no máximo dois ciclos externos. É o menor limite capaz
de recuperar o primeiro conflito conhecido sem retry ilimitado. Os testes
mostram recuperação quando a primeira leitura falha uma vez e a transação seguinte
é válida; dois conflitos consecutivos permanecem indisponíveis. Não é limite
estatisticamente ótimo nem garantia de disponibilidade sob carga real.

Cada ciclo cria client.transaction() novo e rele todos os buckets por ID,
recalculando saldos com o MESMO now passado pelo serviço. Os refs/IDs/políticas
são preservados; não há reset, refill pelo tempo decorrido artificialmente,
sleep, timeout maior ou retentativa de credencial/sessão.

Não são simplesmente dez tentativas nativas: o primeiro ciclo só permite retry
externo se nenhum callback completou leituras. Seu primeiro read aborta antes de
commit. O segundo ciclo pode usar até as cinco tentativas nativas existentes de
commit; não existe terceiro ciclo. Nada ampliou max_attempts do SDK.

## Não repetidos e falha segura

Não recebem esse retry: Aborted no begin, falha genérica, PermissionDenied,
ServiceUnavailable, ValueError com causa Aborted por commits esgotados, erro após
buffer de escrita, commit incerto/ACK perdido, erro pós-commit, drift/configuração
inválida ou orçamento limitado. O mecanismo nativo de commit foi preservado.

Identidades inválidas continuam consumindo o orçamento definido pelo contrato
existente, mas o serviço chama o repositório com allow_read_retry=False. Isso
não adiciona recuperação transacional extra a e-mail malformado. A opção é
interna, não um parâmetro HTTP nem uma flag de produção.

Depois do limite, erro continua AdminAdmissionUnavailable sanitizado. O
coordenador não inicia autenticação/Argon2 nem sessão. Não há estorno ou sucesso
sintético. Commit potencialmente ocorrido nunca é repetido por este sinal privado.

Uma requisição nova do cliente ainda pode consumir novo orçamento após resultado
incerto; esta mudança não implementa exatamente-uma-vez entre requests.

## Testes determinísticos

16 novos casos unitários usam runner real do SDK com transporte scriptado:

- Aborted na primeira/quarta leitura, uma vez ou persistente;
- dois objetos de transação distintos; releitura completa e um único débito;
- clock do serviço consultado uma única vez;
- ausência de autenticação/sessão na falha persistente;
- erros de permissão/indisponibilidade/genéricos sem retry;
- identidade inválida sem segundo ciclo;
- commit Aborted nativo recuperado ou esgotado, sem retry externo;
- commit real simulado seguido de ACK perdido sem segundo ciclo;
- leitura Aborted depois de commit já tentado SEM retry externo;
- erro após buffer, rollback falho, bucket esgotado e configuração inválida.

Quatro novos casos no Emulator fazem injeção em DocumentReference.get na primeira
ou quarta leitura, transitória ou persistente. Usam transações reais e verificam
2 objetos novos, ZERO commits na falha e somente um commit na recuperação.
Todos os quatro documentos recuperados têm capacidade menos um token; nenhum
saldo parcial/negativo/excedido. O auth/session-create mock observa a fronteira
do coordenador, não substitui a regressão de login real com Argon2/sessões.

O teste de diagnóstico do PASSO 90 foi atualizado para a nova expectativa:
conflito persistente tem dois ciclos SDK distintos de um begin cada, não apenas
um. Não removeu a verificação de ausência de dados/autenticação. Wrappers de
cleanup dos testes repassam opções novas sem mudar decisões ou ampliar escopo.
O teste original de duas admissões simultâneas NÃO teve assertions alteradas.

## Emulator e isolamento

Usadas exclusivamente fixtures demo/loopback com AnonymousCredentials e segredo
sintético único por teste. Somente IDs HMAC/UUID próprios foram removidos,
nunca o banco inteiro ou dados usados pelo usuário no Chrome. Dois clientes
compartilham intencionalmente os buckets de cada caso. Não reiniciar Emulator.

Regressão inclui: mesmo IP/IPs distintos, mesma identidade/distintas, sequencial/
paralelo, agregado disponível e com 19/20 tokens consumidos, invariantes por
scope e fronteira de autenticação. Inclui ainda os seis fluxos reais do PASSO 89,
configuração, falha pré-commit/ACK incerto e concorrência anterior.

## Disponibilidade e decisão de homologação

O retry só melhora recuperação de um conflito transitório de leitura comprovado.
Persistência de conflito continua 503, sem promessa de que toda concorrência
vai concluir com sucesso. Contenção/custo podem aumentar pelas leituras extras.
Nenhum benchmark local comprova capacidade ou latência do Render/Firestore real.

Os testes de consistência e falha segura podem aprovar a correção desse caminho
se passarem. Isso não prova a causa histórica nem autoriza homologação em browser
real, ingresso/domínios/TLS/CORS, IAM/índices, custos ou lançamento comercial.
O checklist do PASSO 89 deve distinguir recuperação local validada de aprovação
operacional integral, ainda dependente de decisão/autorização do usuário.

Os documentos de passos anteriores permanecem como evidência histórica; suas
menções a ausência de retry externo descrevem o estado anterior ao PASSO 91.
Este documento registra a única exceção agora implementada.

## Reprodução

Na raiz, sem iniciar/limpar o Emulator globalmente:

```sh
PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider Backend/tests/test_admin_admission_read_retry.py
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider --run-firestore-emulator Backend/tests/emulator/test_admin_admission_read_retry_integration.py Backend/tests/emulator/test_admin_admission_diagnostics_integration.py Backend/tests/emulator/test_admin_admission_sizing_integration.py Backend/tests/emulator/test_admin_prepublication_integration.py Backend/tests/emulator/test_admin_admission_policy_config_integration.py Backend/tests/emulator/test_admin_complementary_admission_integration.py
```

## Resultados finais executados

- Novos unitários: 16 casos aprovados; subconjunto admissão/login/complementares:
  115 aprovados. Suíte unitária completa: 1.400 aprovados + 52 subtestes;
  251 integrações desselecionadas. Nenhuma falha.
- Emulator: 33 aprovados, incluindo quatro novos casos determinísticos, 13 de
  diagnóstico comparativo, três do módulo original, seis do PASSO 89 e sete
  regressões de configuração/complementares. Nenhuma assertion falhou.
- Teste original isolado: dez repetições, dez aprovações, zero falhas; além de sua
  execução no conjunto de 33. Contagens se sobrepõem e não devem ser somadas.
- Telemetria das dez repetições preservada em ADMIN_ADMISSION_READ_RETRY_RESULTS.json.
  Begins/commits totais por repetição: 5,3,3,3,3,5,3,3,5,3. Cada repetição terminou
  com dois allowed, seis documentos e débito EXATAMENTE dois em cada scope.
  Nenhum conflito de leitura foi observado nessas dez repetições; conflitos de
  commit tiveram recuperação nativa. Não atribuir esse sucesso exclusivamente
  ao novo retry de leitura. Esse caminho é comprovado pelas injeções determinísticas.
- Falhas persistentes/commit incerto dos testes intencionais continuam erros;
  aprovação do teste significa fail-closed verificado, não ausência de todos os
  resultados operacionais indisponíveis sob contenção.
- git diff --check passou; aviso existente TestClient/httpx; sem dependências novas.

Correção direcionada e regressão automatizada LOCAL podem ser consideradas
validadas neste escopo. A pendência de recuperação desse caminho conhecido foi
tratada. Não houve nova intermitência no teste original nesta rodada, mas sua
causa histórica continua não comprovada e não há garantia de sucesso universal.
A homologação integral/produção do PASSO 89 não é automaticamente aprovada:
continuam necessárias a decisão operacional sobre 503 legítimo e as verificações
de hosts/HTTPS/browser/ingresso/IAM/índices/custos registradas no checklist.

Arquivos modificados: app/persistence/admin_admission_repository.py,
app/services/admin_admission_service.py, tests/emulator/
test_admin_admission_diagnostics_integration.py (nova expectativa limitada),
test_admin_complementary_admission_integration.py e
 test_admin_prepublication_integration.py (wrappers repassam opções internas).
Arquivos criados: tests/test_admin_admission_read_retry.py,
tests/emulator/test_admin_admission_read_retry_integration.py, este relatório e
ADMIN_ADMISSION_READ_RETRY_RESULTS.json. Alterações locais anteriores preservadas.
Nenhum dado real, credencial, owner real, servidor local ou serviço externo foi
alterado. Nada publicado; não iniciar PASSO 92.
