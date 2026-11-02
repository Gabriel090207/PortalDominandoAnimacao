# PASSO 90 — diagnóstico de concorrência na admissão

## Conclusão e alcance

Não foi reproduzida a falha no teste original nesta rodada: 20 execuções isoladas
passaram; o mesmo teste também passou em dois contextos instrumentados. Isso NÃO
encerra a falha histórica do PASSO 89 nem identifica retroativamente sua causa.

Foi reproduzido um caminho REAL de AdminAdmissionUnavailable em comparações
concorrentes no Emulator: Aborted durante leitura, após UM início transacional,
seguido de rollback, sem commit. O SDK instalado não reexecuta a transação quando
Aborted escapa do callback de leitura; sua captura para retentativa envolve o
commit. Um teste de injeção determinística confirma esse comportamento.

Essa é uma causa comprovada de indisponibilidade neste conjunto de experimentos,
mas não prova que seja a causa daquela execução original sem telemetria.
Não há evidência de corrupção, contagem parcial ou defeito de autorização.
Nenhuma lógica de produção, timeout, política, segredo ou retry foi alterado.

## Inspeção e sequência de chamadas

Revisados ADMIN_PREPUBLICATION.md, ADMIN_ADMISSION_SIZING.md,
ADMIN_COMPLEMENTARY_ADMISSION.md; novo fluxo prepublication, teste original,
fixtures demo não destrutivas, comparações, falhas transacionais unitárias,
serviço/repositório/modelo dos quatro buckets e SDK google-cloud-firestore 2.34.0.

Caminho real: login -> AdminLoginService -> admit_attempt -> normalização/HMAC ->
repository.admit -> firestore.transactional(_admit) -> begin -> quatro leituras
por ID -> evaluate_buckets -> quatro creates/updates se admitido -> commit ->
retorno allowed -> autenticação Argon2 -> sessão. Se limitado ou indisponível,
não chama autenticação. Em negação não escreve documentos.

Todas as leituras do callback precedem as gravações; IDs são determinísticos por
scope/chave, sem consultas de coleção na admissão. Dois e-mails distintos podem
compartilhar origem E agregado. Mesmo com IPs distintos o agregado é compartilhado.

Cada chamada fixa now antes de invocar a transação; o relógio dos experimentos é
START controlado. Não se pressupõe ordem dos callers após a barreira de largada.

## Instrumentação somente em testes

admission_diagnostics.py é plugin pytest opt-in (-p admission_diagnostics).
Observa serviço, begin, leitura, buffer_create/update, commit e rollback. Registra
somente nomes de tipos/etapas, contagens, resultado lógico, duração e somas dos
débitos por scope. Não registra corpo, senha, token, cookie, HMAC, IP, e-mail,
ID de documento/transação ou conteúdo dos snapshots. Não modifica decisões,
retentativas ou sleeps do SDK. Instrumentação pode afetar timing; frequências
observadas não estimam a taxa de falha em produção.

A fixture de diagnóstico depende da fixture NÃO destrutiva já usada pelo módulo:
projeto demo fixo, localhost explícito 127.0.0.1:8080, AnonymousCredentials,
segredo sintético aleatório por teste e exclusão apenas de IDs calculados por ele.
Timestamps/chaves dos dados usados no Chrome não foram alterados. Não foi lido
Firestore real, reiniciado Emulator ou encerrado servidor do usuário.

Na primeira rodada, o extrator de stdout exigiu que a linha JSON começasse na
primeira coluna; o ponto de progresso pytest precedia a linha. Assim, os status
20/20 foram preservados, mas métricas individuais dessa rodada NÃO foram salvas.
Não inferir contagens faltantes. A extração foi corrigida para os contextos
seguintes, sem alterar o teste ou sua execução. A evidência compacta sanitizada
está em ADMIN_ADMISSION_DIAGNOSTICS.json.

## Execuções controladas

| Rodada | Resultado | Observação |
|---|---|---|
| Teste original, isolado, processos novos | 20 aprovadas / 0 falhas | Limite explícito de 20, sem loop infinito |
| Novos 13 diagnósticos + módulo original (3) | 16 aprovados / 0 falhas | Uma indisponibilidade operacional REAL tipada em comparação |
| Regressão conjunta de cinco arquivos não destrutivos | 29 aprovados / 0 falhas | Duas indisponibilidades operacionais REAIS tipadas em comparações |
| Subconjunto unitário relacionado | 201 aprovados | Complementares/admissão/login/entradas/configuração |
| Suíte unitária Backend | 1.384 + 52 subtestes aprovados | 247 integrações desselecionadas |

Contagens se sobrepõem, não somar como testes únicos. Há 13 cenários novos:
oito combinações de identidade/IP/sequencial-paralelo, quatro comparações
paralelas com 19 admissões prévias (20 é a capacidade inalterada), e uma injeção
de Aborted na leitura. Não foram alteradas as assertions do teste original.
Nenhuma assertion falhou nas execuções desta etapa. As três indisponibilidades
operacionais não são ocultadas por essa contagem de testes aprovados.

## Comparações e estados persistidos

Com saldo disponível, mesmo IP ou IPs distintos, mesma identidade ou distintas,
sequencial ou paralelo: duas admissões ocorreram nos oito casos de cada rodada.
Na execução sequencial não ocorreu erro operacional.

Com 19 admissões prévias no agregado de 20, somente um dos dois callers poderia
ser admitido. Nas duas rodadas, resultados:

| Identidade | IP | 1ª rodada | Regressão conjunta |
|---|---|---|---|
| Mesma | Mesmo | 1 allowed, 1 unavailable (Aborted de leitura) | Igual |
| Mesma | Distintos | 1 allowed, 1 limited | Igual |
| Distintas | Mesmo | 1 allowed, 1 limited | 1 allowed, 1 unavailable (Aborted de leitura) |
| Distintas | Distintos | 1 allowed, 1 limited | Igual |

Não presumir qual caller ganhou. Cada unavailable real apresentou:

AdminAdmissionUnavailable -> AdminAdmissionUnavailable -> Aborted ->
_MultiThreadedRendezvous. Foram quatro chamadas de leitura, um begin, um rollback,
ZERO buffers de escrita e ZERO commits para o caller que falhou. Pela ordem do
callback, a falha aconteceu na quarta leitura (agregado). Não houve esgotamento
de cinco tentativas nessa operação: ela saiu na primeira execução do callback.

Depois dessas falhas, TODOS os scopes (origem, origem/identidade, identidade,
agregado) totalizaram exatamente 20 tokens debitados: 19 prefill + um vencedor.
Nenhum saldo negativo, débito parcial, débito duplicado ou orçamento excedido.
Authentication mock e session-create mock foram chamados exatamente para os
callers allowed, nunca para limited/unavailable. Esses mocks observam a fronteira
do coordenador; não são uma sessão real ou verificação Argon2 executada no Emulator.
O fluxo real de login/sessões foi reexecutado na regressão prepublication.

Em ambos os contextos instrumentados, o teste original concluiu duas admissões,
com três begins e três tentativas de commit ao todo. Um caller teve um commit
Aborted (_InactiveRpcError), então repetiu callback/leituras e comitou. Débito final
por scope: exatamente dois tokens; seis documentos (origem comum, dois pares,
duas identidades, agregado). Não houve débito duplo na transação repetida.

Nenhuma leitura após buffer de escrita foi observada na instrumentação (39
registros de contexto; seis testes prepublication usam fixture de outro formato
e não recebem esta telemetria). Nenhuma evidência de interferência por ID/chave:
namespace é exclusivo, cleanup ocorre após término do pool, ambos os clientes
compartilham intencionalmente só os dados daquela fixture. Contudo, Emulator/CPU/
conexões são recursos comuns: executar módulos juntos pode afetar timing.

## SDK e distinção de falhas

No SDK 2.34.0 inspecionado, _Transactional.__call__ executa _pre_commit FORA do
try que captura Aborted. O try cobre transaction._commit. O máximo nativo é cinco.
Logo:

- Aborted no commit pode disparar reexecução automática do callback, como observado.
- Aborted durante begin/callback/leitura que escape até o decorator sai sem essa
  reexecução. O teste determinístico injeta Aborted na primeira leitura: um begin,
  uma leitura, um rollback, nenhum documento e autenticação não chamada.
- Esgotamento dos cinco commits pode virar ValueError com causa Aborted, conforme
  fonte do SDK e testes unitários scriptados já reexecutados. NÃO foi observado
  esgotamento em falha REAL desta rodada no Emulator. Não chamá-lo de causa provada.
- Não se excluem retries internos de RPC; a afirmação acima é sobre reexecutar o
  callback da transação pelo decorator, que foi medido diretamente.
- Falha após possível commit é distinta de Aborted confirmado: os testes existentes
  de ACK perdido (incluídos) deixam os quatro débitos persistidos e bloqueiam
  autenticação. O repositório não adiciona retry externo nem estorno automático.
  Nova tentativa do cliente pode consumir novo orçamento, mesmo que o login
  anterior não tenha começado; não prometer exatamente-uma-vez entre requests.

## Classificação A–F e correção mínima

A. Contenção: comprovada por Aborted real em leitura e commit.
B. Esgotamento nativo: demonstrável por simulação/fonte, não provado nas falhas reais.
C. Sincronização do teste: barreira funciona, mas esperar sucesso incondicional
   dos dois callers é mais forte que o contrato observado do SDK. Não foi mudado.
D. Repositório: mantém atomicidade e falha segura; sanitização oculta a etapa ao
   usuário externo, recuperável aqui somente na instrumentação local. Nenhum
   defeito de integridade/autorização comprovado.
E. Configuração: sem evidência de drift ou segredo divergente; os mesmos limites
   e a mesma chave sintética são usados pelos dois clientes de cada caso.
F. Emulator: conflito reproduzido nele; não existe comparação autorizada com
   produção para afirmar que a frequência/ocorrência seja exclusiva dele.

Reprodução mínima comprovada: teste de injeção de Aborted em DocumentReference.get
numa transação real do Emulator. Reprodução natural próxima: comparação com
19/20 tokens, mesmo IP e dois callers. A primeira é determinística sobre o caminho
SDK, mas não prova a frequência de conflitos; a segunda não é determinística.

A falha histórica do teste original permanece sem causa específica comprovada.
Não afirmar que foi definitivamente o mesmo Aborted de leitura apenas por gerar
a mesma exceção externa. Nenhuma correção de produção deve ser feita para apagar
essa incerteza. O novo teste determinístico é evidência para regressão futura.

Menor próximo passo: decidir explicitamente se 503 em conflito de leitura é
comportamento operacional aceitável e qual disponibilidade o teste original deve
exigir. Se aceito, propor uma alteração de contrato de teste APROVADA: manter
concorrência, validar somente falhas Aborted identificadas e contabilização exata,
sem aceitar qualquer erro ou remover verificações de atomicidade. Se o requisito
for recuperar automaticamente Aborted de leitura, propor separadamente retry
externo limitado APENAS desse caso confirmado, com nova transação, relógio fixo e
sem repetir commit incerto. Não basta aumentar max_attempts: o callback está fora
dessa captura no SDK instalado. Nada disso foi implementado neste diagnóstico.

## Situação do PASSO 89 e preservação

Consistência dos quatro buckets e fail-closed receberam evidência adicional.
Homologação integral do PASSO 89 continua PENDENTE: não foi reproduzida a falha
exata e não foi decidida/alterada a expectativa de disponibilidade. Não declarar
resolvido por 20 execuções aprovadas. Ingresso/domínios/custos/índices/IAM e riscos
comerciais anteriores permanecem como no checklist; não há publicação autorizada.

Arquivos criados: tests/admission_diagnostics.py, tests/emulator/
test_admin_admission_diagnostics_integration.py, ADMIN_ADMISSION_DIAGNOSTICS.json
e este documento. Nenhum arquivo existente foi modificado nesta etapa.
git diff --check passou; aviso existente TestClient/httpx; sem dependências novas.
Nenhum serviço real, dado real, Admin/Frontend, cookies, regras de negócio,
Kirvano, DNS ou Start Command alterado. Nada publicado. Não iniciar PASSO 91.

## Comandos de reprodução local

Na raiz do projeto, com Emulator existente (não iniciar/limpar globalmente):

```sh
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test PYTHONPATH=Backend:Backend/tests PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -s -p no:cacheprovider -p admission_diagnostics --run-firestore-emulator Backend/tests/emulator/test_admin_admission_diagnostics_integration.py Backend/tests/emulator/test_admin_admission_sizing_integration.py
PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider Backend/tests
```

A fixture nova recebe apenas o namespace de buckets do teste; não executar a
suíte global de integração, cuja fixture histórica apaga o banco demo inteiro.
