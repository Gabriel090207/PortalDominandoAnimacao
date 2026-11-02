# PASSO 84 — dimensionamento da proteção complementar

## Decisão recomendada, sem ativação

Manter os buckets existentes exatamente iguais. Recomendar, para aprovação
posterior, identidade de capacidade 5 e reposição 1/60s; agregado de capacidade
20 e reposição 1/30s. Nenhuma configuração padrão, runner, router ou código de
produção foi alterado neste passo. Os valores novos aparecem somente nos testes.

Esta é uma recomendação inicial para equipe pequena e uso eventual, não uma
medição da capacidade do Render. A quantidade real de operators futuros não foi
confirmada. O cenário de quatro administradores é margem de planejamento
hipotética e explícita, não requisito de carga conhecido. A hipótese de três erros
antes de acertar também é um cenário escolhido, não estatística de usuários reais.

## Inspeção

Revisados ADMIN_COMPLEMENTARY_ADMISSION.md, domínio/políticas de admissão,
repositório e serviço de admissão, coordenador de login e composição, tratamento
de erros e testes de concorrência/Emulator. Reutilizados sem alteração do algoritmo.
A configuração complementar exige composição explícita; a padrão permanece
INITIAL_ADMIN_ADMISSION_POLICY com somente os dois buckets anteriores.

## Experimentos e resultados

Unidades usam relógio controlado e transações em memória já existentes.
Cenários HTTP usam Argon2id, sessões e composição reais, com lookup de administrador
mockado por e-mail. Os registros owner/operator são sintéticos. Testes de admissão
não distinguem senha correta/incorreta; somente os cenários HTTP exercitam senha.

| Cenário | Resultado |
|---|---|
| Owner / operator, login normal | 200; sessão consultável e papel correspondente |
| Dois admins no mesmo IP, 3 erros + acerto cada, sem reposição | 8 admissões, 6 respostas 401 e 2 sessões, com agregado 10 ou 20 |
| Quatro admins em IPs distintos, 4 tentativas cada | agregado 10: 10 admitidas e 6 negadas; agregado 20: 16 admitidas |
| Quatro admins no mesmo IP, agregado 20 | origem existente limita a 10; 6 negadas |
| 5 senhas erradas contra owner e depois senha válida | 429 mesmo com senha correta; outro admin ainda consegue 200 |
| E-mails/IPs distintos até esgotar agregado | próximas identidades também limitadas; nenhum novo documento na negação |
| Agregado esgotado, 29,999999s depois | negado, Retry-After de domínio 1 segundo |
| Exatamente 30s depois | um token permite uma tentativa; a seguinte continua negada |
| Inatividade suficiente | saldo recupera até capacidade; nunca além dela |
| Atacante obtendo cada token reposto antes da vítima | vítima continua negada por três ciclos simulados; sem garantia de equidade |
| Contagem instrumentada de repositório | permitida: 4 leituras/4 escritas; negada: 4 leituras/0 escritas |
| 20 identidades/origens novas admitidas | 61 documentos; relógio avançado sozinho não apaga documentos |

Regressões do PASSO 83 reexecutadas: mesmo e-mail com IP/CF variável, capitalização,
identidades inválidas, concorrência, Firestore indisponível, falha pré-commit,
conflito recuperado, esgotamento do SDK, resultado incerto e bloqueio antes da
senha. Também reexecutadas regressões de sessão, permissões, cookies/CSRF,
logout, app.main sem Admin e webhook público na suíte unitária completa.

## Emulator e concorrência observada

Novo arquivo de dimensionamento reutiliza a fixture NÃO destrutiva do PASSO 83:
projeto demo fixo, loopback 127.0.0.1:8080, credenciais anônimas, segredo sintético
exclusivo por teste. Limpeza somente dos IDs HMAC calculados por esse teste,
inclusive documentos cujo resultado foi incerto; nenhuma exclusão global.
Não foi lido nem apagado documento do usuário para comprovar preservação: a
garantia de isolamento está no namespace de chave e na limpeza restrita.

Na execução de dois administradores simultâneos, com dois clientes Firestore,
ambos foram admitidos. Foram contadas três chamadas SDK _begin para duas
transações: houve uma tentativa adicional automática. O agregado ficou com 18
créditos de token e a origem com 8; não houve débito duplicado. Esse resultado
comprova uma recuperação observada, não um limite universal de retries/latência.

A comparação 10/20 foi repetida no Emulator e confirmou 10/16 e 16/16 admissões,
respectivamente. O conjunto de cinco testes anteriores confirmou novamente teto
concorrente, atomicidade e diferença entre falha antes do commit e ACK perdido
após commit real. Sob contenção maior o SDK pode esgotar tentativas e retornar
indisponibilidade sanitizada; não aumentar retries arbitrariamente.

O conjunto de oito testes levou 12,55s nesta execução. Esse tempo inclui preparação,
assertivas e limpeza; NÃO é latência de login, benchmark Render ou previsão de
produção. Nenhum teste de carga/ataque foi enviado a um serviço publicado.

## Justificativa dos limites

Identidade 5/+1 por minuto preserva a tolerância anterior da combinação origem/e-mail,
mas faz esse orçamento acompanhar a identidade por todos os IPs. Permite três
erros e acerto, deixando uma tentativa de margem. Não aumentar esse limite sem
medição: aumentar tolerância também amplia tentativas de senha por identidade.

Agregado 20/+1 a cada 30s dá margem de rajada para o cenário hipotético de quatro
administradores com quatro tentativas (16), deixando quatro tokens. Ele duplica
a rajada comparado ao candidato 10, mas mantém o teto sustentado de duas admissões
por minuto. Não é prova de que 20 seja ideal; aceitar a rajada extra requer
medição de recursos antes de produção. O semáforo Argon2 limita concorrência por
processo, não é fila com garantia de sucesso: sobrecarga pode devolver 503.

Aumentar agregado não evita bloqueio deliberado; apenas muda o orçamento inicial.
Não aumentar origem para acomodar quatro admins no mesmo NAT sem evidência de
necessidade. Dois admins com erros já cabem em 10. O limite compartilhado sob NAT
permanece uma limitação conhecida e deve ser acompanhado antes de ajuste.

## Recuperação e orçamento temporal

Token Bucket tem reposição contínua, não uma janela fixa que zera contadores.
Com buckets inicialmente cheios e reposição aproveitada, o teto de admissões é
capacidade + piso(tempo/período), sujeito aos outros três controles.

| Intervalo desde o início | Agregado 10 | Agregado 20 recomendado | Mesma identidade |
|---|---:|---:|---:|
| Rajada inicial | 10 | 20 | 5 |
| Até 30s | 11 | 21 | 5 |
| Até 60s | 12 | 22 | 6 |
| Até 5min | 20 | 30 | 10 |
| Até 10min | 30 | 40 | 15 |

São tetos acumulados com consumo ao longo do intervalo, não saldos no instante
final. Após esgotamento e sem novos consumos, identidade volta a 5 em cinco
minutos; agregado 20 volta a 20 em dez minutos. O primeiro token global volta em
30s, o primeiro da identidade em 60s. Um ataque contínuo pode tomar esses tokens
indefinidamente; expiração não garante disponibilidade ao usuário legítimo.

## Custos, retenção e contenção

A instrumentação confirmou chamadas de leitura/escrita, não fatura ou métricas
reais de produção. Sem retries, N tentativas que chegam à admissão e A admissões
permitidas fazem 4N leituras de documentos e 4A escritas; somam-se autenticação,
sessões, rede e demais operações fora desse repositório. Negação continua custando
quatro leituras, mesmo para identidade inédita. Se apenas duas políticas estivessem
ativas, seriam 2N/2A. Falhas antes das leituras não seguem essa contagem.

Retentativas refazem leituras e podem aumentar latência/custo. O agregado é um
único documento por segredo/versão e participa de todas as admissões. A contenção
não desaparece aumentando capacidade; aumenta a rajada de transações que tentam
gravá-lo. Nenhuma medição local autoriza estimativa monetária ou garantia de quota.

Na pior cardinalidade de dados admitidos, cada origem/e-mail novo cria três
novos documentos além do agregado compartilhado: 20 primeiras admissões geraram
61 documentos, como verificado. Negadas não criam documentos, mas admissões ao
longo de dias continuam aumentando armazenamento. TTL físico não está habilitado
por este código. expires_at representa recuperação completa, não exclusão física.
Planejar retenção/TTL por aprovação posterior; não apagar buckets antes desse
prazo nem redefinir buckets para alterar limites. Política persistida incompatível
continua rejeitada mesmo após expiração lógica: mudança 10->20 exige decisão de
transição/migração coordenada, não somente mudar um número em instâncias distintas.

## Separação das garantias de segurança

A. Dependentes de IP confiável: origem e origem/identidade só vinculam tentativas à
rede real se o provedor confirmar a procedência do valor. Parser sintático e
normalização não autenticam CF, request.client.host ou XFF.

B. Independentes de IP: identidade normalizada HMAC e agregado continuam limitando
admissões mesmo com origens/CF variados; exigem a mesma política/chave em todas
as instâncias, Firestore funcionando e admissão obrigatória antes da senha.

C. Riscos remanescentes: bloqueio direcionado da identidade, indisponibilidade
coletiva pelo agregado, custo de leituras em negações, armazenamento histórico,
contenção, saturação Argon2, ataques distribuídos e tentativas usando diferentes
identidades. Senha comprometida ainda pode autenticar dentro do orçamento.
Origin/CSRF protegem o contexto do navegador; não autenticam cliente de rede.

Uma API administrativa pública pode usar sessões fortes, autorização e controles
independentes de IP como arquitetura de segurança, mas isso NÃO equivale a ingresso
privado nem garante disponibilidade. No projeto atual, operação pública exigiria
aceitação explícita desses riscos e decisão sobre o requisito de ingresso
pendente; este passo não o remove, não aprova CF e não publica endpoints.

## Ativação local e pendências

Não foi encontrado bloqueio técnico para compor explicitamente a política em
uma aplicação sintética/local. A configuração atual do runner continua intacta e
não adota agregado 20 automaticamente. Seu resolvedor loopback continua exclusivo
do ambiente demo. Não inserir flags ou fallback que habilitem Admin em produção.

Antes de publicação: aprovar limites e risco de bloqueio, confirmar/decidir a
fronteira Render, dimensionar a rajada Argon2, verificar índices/IAM e hosting,
domínios HTTPS/cookies/CORS, retenção, política uniforme e procedimento de troca
sem resets acidentais. Nenhuma configuração de Render/HostGator/Firebase/DNS,
credencial, compra, sessão real, Admin visual ou Kirvano foi alterada.
Não iniciar PASSO 85.

## Resultado final e reprodução

Arquivos criados neste passo: esta documentação, testes unitários
Backend/tests/test_admin_admission_sizing.py e testes Emulator
Backend/tests/emulator/test_admin_admission_sizing_integration.py. Nenhum arquivo
existente ou valor de produção foi modificado nesta etapa.

- 13 novos cenários unitários e três novos cenários no Emulator aprovados.
- Conjunto específico de regressão: 310 aprovados.
- Suíte unitária Backend: 1.295 aprovados, 52 subtestes aprovados,
  226 testes de integração desselecionados.
- Emulator: oito aprovados (cinco anteriores + três novos).
- Nenhuma falha nas execuções; aviso existente de depreciação TestClient/httpx.
  Nenhuma dependência instalada. Contagens se sobrepõem, não somar.
- git diff --check passou; alterações locais anteriores preservadas.

Comandos na raiz do projeto:

```sh
PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider Backend/tests/test_admin_admission_sizing.py
PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider Backend/tests
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -s -p no:cacheprovider --run-firestore-emulator Backend/tests/emulator/test_admin_complementary_admission_integration.py Backend/tests/emulator/test_admin_admission_sizing_integration.py
```

Não substituir os dois arquivos explícitos pela suíte global de integração:
a fixture histórica usa limpeza destrutiva do banco. Servidores locais e dados
usados no Chrome foram preservados; nada foi publicado ou contratado.
