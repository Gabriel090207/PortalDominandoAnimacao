# PASSO 83 — proteção complementar explícita

## Implementação e ativação

ComplementaryAdminAdmissionPolicy estende AdminAdmissionPolicy e exige duas
BucketPolicy adicionais sem defaults: identity e aggregate. A composição recebe
policy explicitamente, valida novamente a classe e mantém os serviços existentes.
INITIAL_ADMIN_ADMISSION_POLICY continua tendo SOMENTE os dois buckets anteriores.
Nenhuma variável ou runner local foi alterado; nenhum router foi ligado a app.main.

Para experimentar, passar uma instância complementar como policy na composição
sintética. Não existe carregamento automático dos novos limites pelo ambiente.
Produção permanece indisponível até aprovação explícita do ingresso e composição.
Suporte Render recomendando CF não equivale a garantia de remoção de falsificação.

## Quatro orçamentos em uma transação

Ordem: origem, origem/identidade, identidade independente, agregado independente.
Todos são lidos antes de qualquer escrita; todos consomem um token ou nenhum
consome. Reutiliza integralmente a aritmética Token Bucket, precisão inteira,
relógio UTC, validade lógica e rejeição de política persistida incompatível.
Nenhum contador é zerado por sucesso. Não altera status do administrador.

IDs antigos permanecem idênticos, inclusive e-mail inválido por origem. Novos IDs
são HMAC-SHA-256 com a chave/versionamento existentes e separação de finalidade:
identity + e-mail normalizado; aggregate + lista vazia. Nenhum IP entra nesses
novos IDs. Identidades inválidas usam um singleton identity_invalid independente
de IP e do texto inválido; continuam compartilhando o bucket inválido por origem
existente. Isso não valida credenciais nem revela existência de administrador.

A coleção auth_throttles e contratos de documento são reutilizados. Novos scopes
identity/aggregate têm a mesma estrutura validada. Política complementar é sempre
revalidada; documentos com política incompatível falham fechados, sem migração.
A política anterior pode continuar lendo seus dois documentos normalmente.

Não executar versões/políticas mistas em uma ativação real: instâncias usando
apenas dois buckets não aplicariam os novos orçamentos. Todas devem compartilhar
classe, limites, segredo e versão. Rotação de chave muda IDs e reinicia orçamentos;
não fazer automaticamente. Retirar a política também reduz proteção e exige decisão.

## Limites candidatos — somente testes

| Escopo | Capacidade | Reposição |
|---|---:|---|
| Origem existente | 10 | 1 token/30s |
| Origem/identidade existente | 5 | 1 token/60s |
| Identidade complementar | 5 | 1 token/60s |
| Agregado complementar | 10 | 1 token/30s |

Os dois novos valores são candidatos do PASSO 82, NÃO limites aprovados de
produção. Pequena equipe e login eventual tornam esse ponto de partida testável,
mas não há medição de carga/latência Render que autorize dimensionamento definitivo.
Identidade começa com cinco tentativas e recupera uma por minuto, independentemente
quando o cliente troca de IP/CF. Agregado começa com dez e recupera duas por minuto
para todos os logins. Saldos nunca excedem capacidade: após esgotamento, cinco
minutos sem novos consumos recuperam integralmente ambos. Não são janelas fixas;
a recuperação é contínua e novas admissões gastam o saldo recuperado.

## Riscos explícitos

Um atacante pode consumir o orçamento da identidade da vítima, mesmo sem conhecer
sua senha, bloqueando também o administrador legítimo até reposição. Pode consumir
o agregado com identidades distintas e impedir todos os administradores. Os testes
demonstram esses efeitos. Não existe promessa de disponibilidade sob ataque nem
mecanismo de desbloqueio especial. Limites candidatos exigem aceitar/medir esse
trade-off; não resolver com reset por sucesso ou fallback local permissivo.

Os complementos limitam trabalho de senha mesmo se a origem variar; NÃO autenticam
um header nem substituem o requisito de ingresso confiável. Mesmo IP confiável
não identifica pessoa. Origin/CSRF/cookies/permissões permanecem necessários.
O limite agregado pode ser um ponto de contenção e de exaustão deliberada. Não
há garantia de equidade entre administradores. Semáforo Argon2 continua por processo.

## Falhas e transações

SDK mantém suas tentativas automáticas existentes; nenhuma retentativa externa
foi adicionada. Erro antes do commit não deixa consumo parcial. Conflito recuperado
pelo SDK consome uma vez. Esgotamento e indisponibilidade são sanitizados e impedem
Argon2/autenticação/sessão. Resultado incerto pode já ter consumido os quatro
orçamentos: não autenticar, não devolver token, não estornar e não repetir
automaticamente. A resposta é indisponibilidade, não credencial incorreta.

## Firestore: custo e crescimento

Sem retries, cada admissão lê quatro documentos em vez de dois. Uma admissão
permitida grava quatro documentos em vez de dois; rejeição não grava novos
buckets, mas ainda lê os quatro. A isso somam-se operações de autenticação/sessão
já existentes. Retentativas podem multiplicar leituras e latência. Não foi feito
benchmark de produção nem estimativa monetária sem região, volume e franquia.

Para O origens, P pares e I identidades admitidas, o armazenamento pode chegar a
O + P + I + 1 documentos por versão/chave, mais os scopes de identidades inválidas.
O singleton agregado é compartilhado entre instâncias, portanto tem contenção.
Identidades arbitrárias válidas podem acumular documentos ao longo do tempo;
o agregado reduz criação por tempo, mas não limita armazenamento histórico.
TTL físico não foi habilitado: expiração lógica existe e não depende da remoção.
Qualquer TTL futuro só pode remover documentos após recuperação completa, como
já expressa expires_at. Não afirmar custo zero; nenhum serviço foi contratado.

## Validação e isolamento

Unidades reutilizam fixtures em memória, SDK real com commit scripted para conflitos,
esgotamento e ACK perdido; isso não é prova de contenção real. Cenário HTTP de
composição utiliza Argon2 e sessão reais com lookup administrativo mockado.
Cobre identidade normalizada/CF variável, origem/pair anteriores, agregado,
invalid identities singleton, recuperação, concorrência entre serviços,
indisponibilidade, resultado incerto, sanitização, sessão e logout.

Emulator: somente test_admin_complementary_admission_integration.py. A fixture
sobrescreve a limpeza destrutiva histórica. Projeto estritamente demo, endpoint
127.0.0.1:8080, credenciais anônimas. Chave sintética aleatória por teste separa
inclusive o singleton agregado. A limpeza remove APENAS IDs calculados pelo teste,
sem varredura nem exclusão global. Dois clientes independentes compartilham os
orçamentos; concorrência verifica teto sem exigir sucesso quando o SDK esgota
retentativas. Falha pré-commit e commit real seguido de ACK sinteticamente perdido
são distintos. Nenhum teste comprova a procedência dos headers na borda Render.

## Próxima decisão

Aprovar ou ajustar limites com medições e risco de negação de serviço documentado;
confirmar ingresso, política uniforme entre instâncias, custo e contenção antes de
qualquer composição de produção. Preservar HostGator/Render/Firestore/Kirvano,
sem novos serviços, publicação, mudanças em Admin/Frontend ou início do PASSO 84.

## Resultados executados

- 27 novos cenários unitários aprovados.
- Conjunto específico (política/admissão/configuração/login/origem/composição):
  297 aprovados.
- Suíte unitária completa: 1.282 aprovados, 52 subtestes aprovados;
  223 testes de integração desselecionados, sem uso do banco real.
- Arquivo novo isolado no Emulator: 5 aprovados, inclusive concorrência real
  entre dois clientes e preservação atômica dos quatro documentos.
- Nenhum teste falhou nas execuções desta etapa. Aviso existente de depreciação
  TestClient/httpx, sem instalação de dependências. Contagens se sobrepõem.
- git diff --check passou. Alterações anteriores preservadas.

Execução do Emulator realizada SOMENTE com o arquivo novo, nunca a suíte global:

```sh
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider --run-firestore-emulator Backend/tests/emulator/test_admin_complementary_admission_integration.py
```
