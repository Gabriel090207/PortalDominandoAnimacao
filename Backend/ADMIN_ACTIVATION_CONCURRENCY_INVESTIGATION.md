# Investigação de concorrência — passo 61

Status: intermitência reproduzida; causa original ainda NÃO confirmada. Nenhuma
correção de produção foi aplicada. Aprovações posteriores não resolvem a falha.

## Teste exato e reprodução

`tests/emulator/test_admin_activation_integration.py::test_concurrent_activation_one_transition_one_audit`

O teste inicia duas chamadas simultâneas ao repositório, através de Barrier(2) e
ThreadPoolExecutor(max_workers=2). Não são duas requisições HTTP: são chamadas ao
repositório. CustomerActivationUnavailable é representado no teste por unconfirmed;
o router real traduz essa condição para 503, mas não houve tráfego HTTP na falha.

| Grupo | Execuções do cenário concorrente | Aprovações | Falhas |
|---|---:|---:|---:|
| Sonda isolada, sem alteração de produção | 12 | 12 | 0 |
| Conjunto original (17 testes), três execuções | 3 | 2 | 1 |
| Conjunto com diagnóstico temporário, cinco execuções | 5 | 5 | 0 |
| Conjunto fortalecido (18 testes), cinco execuções | 5 | 5 | 0 |
| Teste fortalecido isolado final | 1 | 1 | 0 |
| Total do cenário concorrente | 26 | 25 | 1 |

Na reprodução problemática, results foi [unconfirmed, unconfirmed]. O conjunto
teve 16 aprovações e uma falha; a asserção exigia exatamente um activated. Duração
do conjunto: aproximadamente 11,22s. Essa duração não prova timeout, contenção ou
qualquer tipo específico de exceção. O teste passou nas demais execuções, tanto
isolado como em conjunto, mas isso não comprova determinismo.

Na execução com falha, a asserção original ocorreu ANTES da inspeção do documento
e da auditoria; a fixture limpou o projeto ao encerrar o teste. Não foi possível
recuperar o estado persistido nem a exceção original dessa execução. Portanto:
NÃO se sabe se não houve ativação ou se houve commit sem confirmação. A ausência
de resposta activated não pode ser usada para inferir ausência de escrita.

## Evidências e limites da investigação

Inspeção confirmou:

- Cliente injetado, projeto demo fixo e endpoint localhost, credenciais anônimas.
- Fixture limpa antes/depois, bloqueia inicialização Firebase de produção e fecha
  o cliente. Cada par de threads termina antes da limpeza; não se executaram
  suítes simultâneas sobre o mesmo emulador. Não se encontrou vazamento de estado.
- As duas tarefas passaram a barreira na execução problemática, pois retornaram
  o erro sanitizado do repositório, e não BrokenBarrierError. A barreira sincroniza
  o início, não determina a ordem interna das transações.
- O repositório lê usuário/admin/compra/direito antes de enfileirar update + audit
  create. O decorador confirma commit antes de devolver activated. already_active
  não enfileira nova transição ou auditoria. Erros são sanitizados, incluindo
  resultados incertos. Não há retry externo.
- As leituras têm timeout explícito de 10 segundos. Pode ser relevante para
  investigar, mas não há exceção capturada que comprove que causou esta falha.

Na sonda isolada, depois de cada par: usuário active/enabled, exatamente uma
auditoria, demais campos do usuário e coleções administrativas/comerciais
preservados. Em cinco conjuntos instrumentados também se observaram active,
enabled e uma auditoria, sem erro original a classificar.

Não foi observada violação de atomicidade nas execuções cujo estado foi
inspecionado. Isso NÃO estabelece o estado da execução problemática já limpa.
Não há evidência suficiente para atribuir causa ao teste, SDK, emulador ou lógica
de produção. Contenção, falhas de leitura/commit e timeout permanecem hipóteses.

## Comportamento do SDK instalado

A análise do código local google-cloud-firestore e cinco testes determinísticos
com o decorador _Transactional real confirmam:

1. Aborted ou DeadlineExceeded levantado dentro do callback de leitura NÃO recebe
   as cinco retentativas do decorador: _pre_commit fica fora do try que trata
   Aborted de _commit; ocorre rollback e propagação.
2. Aborted de commit é retentado internamente.
3. Esgotamento de cinco commits Aborted resulta em ValueError associado a Aborted.
4. DeadlineExceeded de commit não é retentado pelo decorador como conflito seguro.
5. Query.stream não faz snapshot retry dentro de uma transação.

Isso corrige a simplificação de que qualquer erro transacional teria cinco
retentativas. NÃO demonstra qual desses caminhos ocorreu na reprodução. Não se
introduziu retry adicional de leitura/escrita para tentar esconder a falha.

## Fortalecimento dos testes, sem relaxar expectativas

O teste concorrente agora verifica estado e preservação ANTES da asserção de
progresso, inclusive se ambas as chamadas retornarem erro. Verifica:

- active implica exatamente uma auditoria; pending implica nenhuma;
- administrador, cliente e transição corretos na auditoria;
- account_status e demais campos do usuário preservados;
- compras, assinaturas, entitlements e administrador com dados/update_time intactos;
- uma repetição posterior não muda a auditoria;
- continua exigindo exatamente um resultado activated, sem presumir vencedor.

Não aceita indiscriminadamente exceções: captura somente a exceção sanitizada de
persistência já prevista. Em falha, fornece somente classes de exceção, funções/
linhas do traceback e contagens/estados, nunca mensagens originais ou documentos.
Esse diagnóstico existe SOMENTE no teste, não em logs públicos/produção.

Adicionado cenário de dois clientes diferentes em paralelo: duas ativações e duas
auditorias correspondentes, preservando registros comerciais. Concorrência não foi
reduzida, não houve sleeps arbitrários nem remoção de verificações.

O cenário de confirmação de commit perdida agora percorre o HTTP real da
composição isolada: após commit efetivo, injeta falha apenas no commit contendo
activation_audit. A resposta é 503 sanitizada/no-store; GET posterior mostra active
e uma auditoria; novo POST retorna already_active sem duplicar auditoria. Isso é
injeção controlada de perda de confirmação, NÃO reprodução da falha original.
O teste de falha antes do commit mantém igualdade completa do estado persistido.

## Resultados finais

- Testes unitários específicos de ativação e SDK: 51 aprovados.
- Suíte unitária completa: 1034 aprovados, 52 subtests; um aviso preexistente de
  depreciação Starlette/httpx, nenhuma falha unitária.
- Cinco execuções do conjunto fortalecido: 18/18 aprovados em cada uma (90
  aprovações), incluindo HTTP, auditoria, atomicidade, dois clientes, permissões,
  listagem, busca, ficha, confirmação e composição.
- Teste concorrente final isolado: aprovado, aproximadamente 8,36s.
- Uma falha intermitente anterior permanece registrada, não corrigida/ocultada.

Foram alterados somente testes e este documento em Backend/. Nenhum arquivo de
produção foi modificado neste passo; nenhuma regra comercial, autorização, sessão,
rate limiting ou webhook foi alterado. Nenhum acesso a produção ou publicação.

## Menor investigação adicional

Repetir o conjunto com o teste fortalecido até capturar nova ocorrência, dentro de
um orçamento operacional definido. O próximo relatório de falha preservará classes,
funções/linhas, activation_status e contagem de auditoria antes da limpeza. Correlacionar
então o ponto de falha com leitura, commit ou rollback no SDK e, se necessário, com
um trace temporário local das RPCs sem payloads. Somente depois escolher correção
mínima ou revisar a expectativa de disponibilidade, sem enfraquecer atomicidade.

Não aumentar timeouts, adicionar retries externos, serializar tarefas, aceitar
qualquer resultado ou declarar estabilidade sem essa evidência. A estabilidade da
regressão concorrente permanece pendente antes de considerá-la homologada.
