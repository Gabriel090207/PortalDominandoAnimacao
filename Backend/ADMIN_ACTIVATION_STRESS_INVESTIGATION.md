# Investigação controlada de ativação — passo 62

Este relatório complementa o passo 61. Nenhuma implementação de produção foi
alterada, nenhum retry foi adicionado e nenhuma asserção foi relaxada.

## Isolamento e limite

Execução exclusivamente no Firestore Emulator 127.0.0.1:8080, projeto fixo
`demo-dominando-animacao-test`, banco padrão e credenciais anônimas. As fixtures
existentes impedem inicialização Firebase e obtenção do cliente de produção,
limpam antes/depois e aguardam as duas threads antes do teardown. Não houve
execução simultânea de suítes no mesmo projeto.

O runner de teste activation_stress_probe.py valida o ambiente antes de executar,
usa um subprocesso pytest por vez, mantém Barrier(2)/dois workers e não introduz
sleeps. Limita o ensaio a 99 execuções ou 840 segundos, reservando a centésima
execução concorrente para a regressão. O arquivo de resultados existente não é
sobrescrito silenciosamente. Nenhum valor do ambiente de produção é modificado.

Cada registro contém número, resultado pytest, duração, quantidade/resultados das
duas chamadas e o diagnóstico sanitizado do teste. O diagnóstico é anexado ANTES
das asserções e do teardown; não depende de recuperar documentos depois da limpeza.
Somente tipos de erro, nomes de funções/linhas, estados, IDs sintéticos de auditoria
e flags de preservação são registrados. Não há e-mail, documento inteiro, mensagem
original de exceção, payload, credencial, hash ou token nos resultados.

A quantidade calls=2 refere-se ao par concorrente. Nos testes aprovados existe
adicionalmente uma chamada idempotente sequencial de verificação, preservada do
teste original; ela não é contabilizada como terceira chamada concorrente.

## Falha capturada antes da limpeza

Nas execuções 28 e 31:

- Duas chamadas retornaram unconfirmed.
- Cada uma apresentou CustomerActivationUnavailable -> ValueError -> Aborted ->
  _InactiveRpcError. O último é o transporte gRPC, não evidência de timeout.
- Os tracebacks colocam Aborted na RPC de commit (_commit), e ValueError no ponto
  de esgotamento do decorador transacional do SDK.
- activation_status final: pending; account_status: enabled.
- Auditorias: zero; portanto não há administrador/transição persistidos nessas
  ocorrências. Não se inventa auditoria ou identidade de uma operação não gravada.
- Compras, assinaturas, entitlements e administradores preservados, inclusive
  update_time; e-mail e todos os outros campos do cliente também preservados.
- Não houve ativação efetiva nem violação de atomicidade nessas ocorrências.

Não são chamadas HTTP: o cenário chama o repositório diretamente. unconfirmed é
representação do erro que o endpoint traduz para 503. Não se relata um HTTP 503
medido na falha concorrente. A regressão separada continua exercitando o HTTP real,
inclusive 503 após perda simulada da confirmação de um commit efetivo.

Esses resultados NÃO recuperam retroativamente os documentos das falhas dos
passos anteriores: o estado persistido daquelas ocorrências continua desconhecido.

## Causa demonstrada e limite da conclusão

A causa imediata das ocorrências capturadas é o esgotamento, em ambas as chamadas,
das tentativas internas de commit após conflitos Aborted. O SDK instalado usa
max_attempts=5; seu decorador lança ValueError associado ao último Aborted ao
esgotar esse laço. A pilha capturada passa exatamente por esse caminho. A lógica
de produção sanitiza o erro para CustomerActivationUnavailable, sem sucesso falso.

Não foi capturada exceção DeadlineExceeded/Unavailable/Cancelled nessas duas
ocorrências. Sua duração próxima de dez segundos NÃO é prova de timeout de leitura.
Não houve evidência de erro no callback de leitura nessas ocorrências específicas.

O diagnóstico não determina o motivo interno de cada conflito/aborto no motor do
emulador, não demonstra defeito do SDK e não estabelece que a produção apresentaria
a mesma frequência. O instante e a interleaving dos locks permanecem desconhecidos.
Não se atribui a causa a limpeza prematura, dados misturados ou erro comercial:
não há evidências desses problemas nas verificações realizadas.

A expectativa de progresso do teste (uma chamada devolver activated) falhou;
as garantias de integridade verificadas permaneceram satisfeitas. Isso distingue
indisponibilidade por contenção/esgotamento de corrupção, duplicação ou quebra
de auditoria. A expectativa original foi mantida para não esconder o problema.

## Risco residual e próximo passo

O risco demonstrado é de disponibilidade: duas solicitações concorrentes podem
terminar sem ativar o cliente, demandando conferência e nova decisão humana. Uma
resposta 503 genérica continua potencialmente incerta em outros caminhos, incluindo
perda de confirmação após commit; não deve provocar retry automático de escrita.
A UI já oferece GET de atualização sem atribuir autoria a uma alteração observada.

Recomenda-se uma decisão técnica específica sobre a recuperação de contenção antes
de alterar produção: avaliar uma política limitada EXCLUSIVAMENTE para abortos
transacionais comprovados, distinguindo-a de timeouts/resultado incerto. Antes de
aprovar, definir limites, custo, latência e testes determinísticos. Não aumentar
silenciosamente as tentativas, não repetir erros arbitrários e não reduzir a
concorrência para passar. Nenhuma recuperação adicional foi implementada aqui.

Se for necessário explicar o mecanismo interno de locks, a investigação seguinte
pode correlacionar IDs efêmeros de tentativas e eventos de commit/abort no emulador,
sem payloads, dentro de novo orçamento aprovado. Essa explicação não é presumida
pelo presente relatório. A intermitência não está corrigida nem homologada como
estável, apesar da preservação observada dos dados.

## Resultado final e evidência por execução

O arquivo `tests/activation_stress_results.jsonl` contém as 100 execuções e seus
diagnósticos sanitizados, em ordem. Resultado do cenário concorrente:

| Grupo | Execuções | Aprovações | Falhas |
|---|---:|---:|---:|
| Ensaio isolado limitado | 99 | 97 | 2 |
| Cenário incluído na regressão final | 1 | 1 | 0 |
| Total | 100 | 98 | 2 |

Tempo somado de execução dos subprocessos: 383,347 segundos (~6min23s), dentro do
limite de aproximadamente quinze minutos. Nenhuma repetição adicional do cenário
foi executada. Duração individual entre 2,467s e 10,569s. A frequência observada
é apenas descritiva desta amostra local; não estima probabilidade em produção.

Pares de resultados, sem presumir vencedor:

- 95 vezes: activated + already_active.
- 3 vezes (6, 9, 68): activated + unconfirmed. Estado active/enabled, uma auditoria
  com admin_id=synthetic-admin, customer_id=customer-a, pending -> active.
- 2 vezes (28, 31): unconfirmed + unconfirmed. Estado pending/enabled, zero auditorias.

Foram sete erros sanitizados individuais; todos apresentaram a mesma cadeia
CustomerActivationUnavailable -> ValueError -> Aborted -> _InactiveRpcError,
com a pilha no esgotamento de commits do SDK. Não houve erro de leitura, timeout,
indisponibilidade ou cancelamento capturado como causa dessas sete exceções.
O gatilho interno dos Aborted no servidor permanece não determinado.

Em todas as 100 execuções, o diagnóstico foi capturado: duas chamadas concorrentes,
conta preservada, no máximo uma transição/auditoria, equivalência de auditoria ao
estado final e preservação de compras, assinaturas, entitlements, administrador,
e-mail e campos desconhecidos. Não houve item desconhecido na inspeção do estado
dessas execuções. Horário/ordem interna dos locks e IDs de cada tentativa SDK não
foram instrumentados, e continuam desconhecidos.

A regressão final inteira teve 18 testes aprovados no emulador, incluindo o
centésimo cenário concorrente, clientes distintos, auditoria/atomicidade,
autorização owner/operator, consulta, busca, confirmação e composição. O teste HTTP
de perda simulada de confirmação preservou 503 com ativação/auditoria efetivas,
demonstrando que a regra geral de resultado incerto deve continuar conservadora.

A suíte unitária completa teve 1034 testes aprovados e 52 subtests; cobre ativação,
falhas, SDK, permissões, autenticação/sessões e integração comercial sintética.
Um aviso preexistente Starlette/httpx permanece. Não foi instalada dependência.
`git diff --check` e validação dos arquivos não rastreados passaram.

As duas falhas de progresso do ensaio permanecem registradas. A aprovação da
regressão final não constitui correção ou comprovação de determinismo. Nenhum código
de produção foi modificado; mudanças deste passo limitam-se ao diagnóstico no teste,
runner/recorder de teste, artefato sanitizado e este relatório. Admin/, Frontend/ e
alterações locais anteriores foram preservados. Nenhum acesso ou publicação em
produção, endpoint ou funcionalidade administrativa nova.
