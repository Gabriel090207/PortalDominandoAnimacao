# Retentativa nativa limitada na ativação — passo 63

## Alteração mínima

AdminActivationRepository passa explicitamente max_attempts=8 ao criar SUA
transação. Antes, client.transaction() herdava o padrão nativo de cinco. O SDK
instalado aceita esse argumento público e cria um objeto Transaction independente;
não altera a configuração do cliente Firebase nem de outras operações.

A constante local _ACTIVATION_MAX_ATTEMPTS=8 é o único ajuste na lógica de produção.
Não há loop externo, sleeps, backoff improvisado, nova dependência ou nova política
para sessões, webhooks, admissão ou demais repositórios. O máximo é oito tentativas
transacionais totais, e não oito vezes cinco. Oito inclui a tentativa inicial.
Os mecanismos de transporte RPC do SDK permanecem intactos; o limite não significa
que toda tentativa terá apenas uma RPC nem estabelece prazo global absoluto.

## Por que oito

O passo 62 capturou dois esgotamentos conjuntos e três esgotamentos individuais do
limite de cinco, com integridade preservada. Oito adiciona uma margem pequena e
explícita de três tentativas (+60% no teto), sem multiplicar camadas de recuperação.
É uma política inicial limitada a ser avaliada pela amostra de estabilidade,
não uma afirmação de número ótimo ou de disponibilidade absoluta. Pode aumentar
leituras/custo/latência em contenção; não elimina conflitos ou necessidade de 503.

## Distinção segura de erros

O decorador transacional real do SDK mantém a classificação por tipo/etapa:

- Aborted retornado pelo commit é tratado pelo próprio SDK, que reinicia a tentativa
  e reexecuta o callback completo, dentro do orçamento de oito.
- Ao esgotar, ValueError associado ao último Aborted continua sanitizado como
  CustomerActivationUnavailable; o HTTP permanece 503.
- ValueError genérico, mesmo contendo a palavra Aborted, não autoriza retry.
- DeadlineExceeded/erro genérico de commit não são convertidos em Aborted nem
  provocam nova tentativa transacional pelo decorador.
- Erros do callback de leitura continuam fora do catch de Aborted do commit;
  aumentar max_attempts não adiciona recuperação de erros de leitura.
- Perda da confirmação após commit continua retornando 503, sem retry externo.

Não existe inspeção de mensagens de erro ou classificação por texto/cadeia de
ValueError na produção. O contrato HTTP e a UI de resultado incerto/GET explícito
não foram alterados. Retentativas de RPC já internas ao SDK não foram reconfiguradas.

## Revalidação, idempotência e auditoria

Cada reexecução lê novamente o usuário, administrador, compra vigente e direito,
com o relógio recalculado. Não reaproveita estado comercial pré-computado. Conta
bloqueada, ativação suspensa, compra/direito incompatíveis ou administrador inelegível
continuam sendo recusados. Não se altera can_access_portal ou regras de assinatura.

Se outra transação concluir primeiro, a nova leitura encontra active e devolve
already_active, sem nova transição/auditoria. Se bloqueio ou revogação de direito
ocorrer entre tentativas, a validação impede ativação. As verificações HTTP de
sessão, activate_customer, Origin, CSRF e confirmação humana permanecem intactas.

O update exclusivo de activation_status e create da auditoria continuam no mesmo
commit. A referência de auditoria permanece estável na chamada externa e create-only;
cada tentativa nativa limpa suas escritas anteriores. Aborto não grava auditoria
isolada. Não se modifica conta, e-mail, compra, assinatura, entitlement ou campos
desconhecidos. O actor vem exclusivamente da autoridade validada no backend.

## Testes determinísticos e injeção local

Os testes do SDK usam seu decorador _Transactional real com transporte isolado:
limites cinco/oito, recuperação na oitava, esgotamento, callback com erro, timeout
incerto e ValueError genérico. O teste de repositório confirma a solicitação de
max_attempts=8, sem camada externa. Testes anteriores de auditoria, perda de
confirmação e idempotência continuam sendo executados.

Cinco novos cenários no emulador verificam recuperação na oitava tentativa,
esgotamento de oito com nenhum efeito, erro genérico sem retry e revalidação após
mudança de conta ou entitlement. Para injetar um Aborted confirmado sem fingir
uma falha de rede, o teste faz rollback real ANTES de levantar Aborted. O SDK então
executa novamente o callback contra o emulador. Isso é injeção controlada de erro,
não reprodução de uma RPC real Aborted nessas cinco situações. As mudanças de
conta/direito nesses testes representam fatos sintéticos concorrentes, não novos
endpoints ou implementação de bloqueio/revogação.

## Estabilidade e preservação dos resultados anteriores

O runner diagnóstico existente foi adaptado para permitir nome simples de arquivo
JSONL e orçamento explícito, até 540 segundos. Seu padrão agora é 540s, em vez dos
840s do passo 62, respeitando o limite atual de aproximadamente dez minutos com
margem para a regressão. Mantém 99 repetições e reserva a centésima para regressão.
Não sobrescreve arquivos existentes, não muda concorrência/asserções e não adiciona
pausas. O arquivo do passo 62 permanece preservado para comparação.

Os novos resultados estão em tests/activation_stress_results_step63.jsonl. As
fixtures continuam limitadas a localhost, projeto demo e credenciais anônimas,
com bloqueio do cliente Firebase de produção. Não houve alteração de ambiente
Render/Netlify, credenciais, autenticação, sessões, permissões ou webhooks.

## Limitações que permanecem

Abortos/indisponibilidade ainda são possíveis após oito tentativas. A política não
resolve o mecanismo interno de locks do emulador e não comprova o comportamento
ou a frequência em produção. Efeitos de cache, agendamento e variação natural de
concorrência impedem interpretar uma comparação de duas amostras como prova causal
ou garantia de melhoria em toda carga.

Resultados incertos continuam conservadores. A confirmação da compra não prova
validade financeira atual nem ausência de reembolso/chargeback; essas pendências
comerciais não foram modificadas. Oito tentativas podem elevar a latência de cauda;
monitorar em ambiente autorizado após publicação e configuração operacionais próprias.
Nenhum endpoint foi criado/registrado em app.main e nada foi publicado.

## Resultados executados

- Testes unitários específicos de ativação/SDK: 60 aprovados (9 cenários adicionais
  em relação ao conjunto anterior de 51).
- Cinco novos cenários de injeção/revalidação no emulador: aprovados.
- Suíte unitária completa final: 1043 aprovados, 52 subtests, sem falhas.
- Regressão final no emulador: 23 aprovados, incluindo os cinco novos e a centésima
  execução do cenário concorrente. Mantidos os testes reais HTTP 503/commit incerto.
- Estresse: 99 execuções isoladas + 1 na regressão, 100 aprovações e zero falhas.
  Tempo somado dos subprocessos: 379,087 segundos (~6min19s), dentro do orçamento.
- Em todos os 100 cenários, uma chamada activated e outra already_active, cliente
  active/enabled, uma auditoria pending -> active do synthetic-admin/customer-a,
  demais campos e coleções preservados. Nenhuma exceção FINAL foi capturada.
  Abortos intermediários recuperados internamente não foram contabilizados pelo
  diagnóstico; não se afirma que não ocorreram conflitos.
- git diff --check e verificação dos arquivos não rastreados aprovados.
- Permanece um aviso preexistente de depreciação Starlette/httpx.

| Medida local | Antes, máximo 5 | Depois, máximo 8 |
|---|---:|---:|
| Cenários concorrentes | 100 | 100 |
| Aprovações | 98 | 100 |
| Falhas do cenário | 2 | 0 |
| activated + already_active | 95 | 100 |
| activated + unconfirmed | 3 | 0 |
| unconfirmed + unconfirmed | 2 | 0 |
| Média por cenário (s) | 3,382 | 3,340 |
| Mediana por cenário (s) | 2,056 | 2,053 |
| Máximo por cenário (s) | 10,129 | 10,104 |

As durações são do corpo do teste completo (incluindo suas leituras, chamadas
concorrentes e verificação idempotente), NÃO de uma ativação individual. Os tempos
observados foram semelhantes. As amostras são sequenciais e sujeitas a variação
natural; não houve experimento aleatorizado, comprovação estatística de desempenho
ou observação em produção. O teto maior pode aumentar latência/custo em outras
cargas, mesmo que a média desta amostra tenha sido semelhante.

Zero falhas nesta amostra é evidência favorável à política limitada, não prova de
que conflitos/esgotamentos sejam impossíveis. Não se alteraram as asserções para
aceitar mais resultados. Nenhum resultado incerto foi convertido em sucesso, e
nenhum timeout recebeu nova camada de retry.

Arquivos deste passo: repositório de ativação (constante/argumento nativo), testes
unitários de ativação/SDK, testes de integração de ativação, runner diagnóstico,
novo JSONL de resultados e este relatório. Os artefatos/diagnósticos dos passos
61/62 foram preservados. Admin/ e Frontend/ permaneceram intactos; nenhuma regra
comercial, endpoint ou configuração de produção foi criada/alterada. Nada foi
publicado e nenhum banco de produção foi acessado.
