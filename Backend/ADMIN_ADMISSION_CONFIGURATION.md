# PASSO 85 — configuração explícita da política complementar

## Escopo

O carregador app/config/admin_admission_policy.py prepara configuração sem ler
ambiente, .env, credenciais, banco ou rede. Não registra endpoints, não carrega
HMAC, não modifica os.environ e não habilita funcionalidades ao importar.
Nenhuma alteração foi feita no runner admin_local.py ou no ambiente manual ativo.
A composição e os algoritmos de admissão do PASSO 83 foram reutilizados intactos.

Revisados domínio/admin_admission.py, serviços de admissão/login, repositório,
admin_composition.py, admin_local.py, configurações HMAC/HTTP, testes e documentos
dos PASSOS 83/84. Mantêm-se restrições HostGator/Render/Firestore/Kirvano e
pendência de procedência do CF-Connecting-IP.

## Seleção e versão

load_admin_admission_policy exige selection explícita:

- complementary-local-v1: referência aprovada SOMENTE para preparação/testes
  locais. Não aceita configuration adicional que a sobrescreva silenciosamente.
- configured-v1: exige configuração completa schema_version=1 e policy com
  quatro BucketPolicy, validadas pelo modelo complementar existente.

Ausência, nome desconhecido, versão incompatível, configuração incompleta,
campos extras ou valores inválidos geram AdminAdmissionConfigurationError fixa,
sem conteúdo original. Capacidades/reposições/períodos são inteiros estritos,
positivos e respeitam o limite de armazenamento do domínio. Objetos previamente
construídos também são revalidados. Não existe fallback para política antiga em
caso de erro.

| Escopo da referência | Capacidade | Reposição |
|---|---:|---|
| Origem | 10 | 1/30s |
| Origem + identidade | 5 | 1/60s |
| Identidade independente do IP | 5 | 1/60s |
| Agregado | 20 | 1/30s |

schema_version desta configuração NÃO é versão HMAC nem schema_version dos
documentos. A configuração HMAC existente exige segredo válido e key_version=1;
o carregador da política não gera nem fornece esse segredo. Todos os quatro
buckets usam o mecanismo HMAC existente e seus scopes separados.

## Uso exclusivamente explícito

Em uma aplicação sintética/local já isolada:

```python
from app.config.admin_admission_policy import load_admin_admission_policy

policy = load_admin_admission_policy(selection='complementary-local-v1')
# Fornecer policy=policy à compose_admin_http existente, com cliente demo,
# configuração HMAC sintética e dependência de origem local já verificados.
```

Não é um novo comando de startup ou habilitação automática no Render. O runner
atual continua com política inicial de dois buckets, sem reinício, escrita em
buckets ou alteração de sessões. Os testes criam aplicações separadas e usam
armazenamento em memória ou namespace HMAC aleatório exclusivo no Emulator.
Nenhum segredo real foi gerado ou salvo em arquivo versionado.

O perfil configurável recebe, por exemplo, um dict contendo schema_version e
policy=policy.model_dump(), explicitamente entregue pelo chamador. Não há uma
nova fonte de ambiente ou caminho de arquivo implícito. A factory administrativa
continua sendo a única composição; não há segundo sistema de autenticação.

## Compatibilidade e divergências

A referência preserva exatamente os IDs/políticas dos dois buckets anteriores.
Opt-in sobre registros de dois buckets conserva seus débitos e cria os dois
novos documentos na mesma transação da próxima admissão permitida. Uma negação
não cria documentos nem consome parcialmente. Nenhum orçamento é zerado.

Os novos controles iniciam com capacidade cheia quando não existem: não há
reconstrução retroativa das tentativas anteriores por identidade/agregado.
Essa semântica de início precisa integrar a aprovação futura da ativação.

Políticas diferentes no mesmo ID persistido falham fechadas. O teste configura
agregado 10 numa instância após outra persistir 20 e comprova indisponibilidade,
sem débito parcial ou novos documentos. Contudo, instâncias com política antiga
continuam capazes de ignorar identidade/agregado: armazenamento não impõe um
manifesto global de implantação. Foi demonstrado explicitamente no teste.

Versões de configuração desconhecidas e versão HMAC não suportada são recusadas.
Segredos válidos diferentes ou uso direto de versões HMAC diferentes pelo serviço
interno podem criar namespaces distintos; o banco NÃO detecta essa divergência
como incompatibilidade. Não há coordenação automática ou lock global de ativação.
Não alegar detecção distribuída de configurações só porque o loader é versionado.

## Menor transição futura segura — NÃO executada

1. Aprovar política, risco de bloqueio, ingresso e janela de manutenção.
2. Pausar novas tentativas de login administrativo em TODAS as instâncias e
   impedir tráfego para versões antigas durante a troca. Não bloquear globalmente
   o serviço público/Kirvano. Não revogar sessões existentes como efeito colateral.
3. Confirmar mesma versão de aplicação, configuração, segredo HMAC e key_version
   em todas as instâncias. Não trocar chave para contornar incompatibilidade.
4. Verificar, por acesso interno autorizado futuro, se existem somente documentos
   antigos ou também identity/aggregate com políticas distintas.
5. Havendo apenas dois buckets compatíveis, preservar documentos e ativar os
   quatro coordenadamente; novos complementos iniciam cheios, conforme aprovado.
6. Havendo agregado persistido 10 (ou outra política incompatível), NÃO apenas
   mudar o perfil para 20. Mesmo após expires_at, a validação atual recusa drift.
   Manter login indisponível e decidir uma migração explícita auditável em outra
   etapa. Este passo não implementa migração, limpeza, reset ou aumento de saldo.
7. Homologar configuração/ingresso e só então liberar login com observação de
   429/503, contenção, custos e saturação Argon2.

Rollback preferido: retirar a disponibilidade do login e corrigir a composição,
preservando dados. Retornar à política de dois buckets diminui a proteção e só
pode ocorrer mediante aprovação explícita desse risco, com coordenação de todas
as instâncias. Se os quatro buckets forem mantidos compatíveis, rollback de código
não precisa alterar seus saldos. Não apagar documentos nem girar HMAC para obter
nova capacidade. A aplicação pública permanece independente dessas decisões.

Ainda é necessário definir mecanismo operacional para pausar/habilitar login;
não foi criado um interruptor de produção nesta etapa e não há garantia de
ativação coordenada apenas selecionando uma string. Admin ainda não foi publicado.

## Segurança e limites

Origem administrativa continua obrigatória antes da senha. Sem dependência
adequada, login é indisponível mesmo com perfil válido. Parser CF não atesta
procedência; não usar Origin/CORS, XFF ou request.client.host como substitutos.
A referência não altera Argon2id, CSRF, permissões, cookies ou oito horas de sessão.

Os quatro buckets continuam na mesma transação, com falha sanitizada e bloqueio
antes de Argon2/sessão se Firestore falhar ou o commit for incerto. Nenhuma
retentativa externa foi adicionada. Identidade e agregado permitem negação de
serviço direcionada/coletiva; não substituem automaticamente ingresso confiável.
Custos/retencão/contenção permanecem os registrados nos PASSOS 83/84: quatro
leituras por tentativa, quatro escritas se admitida, sem contar retries e demais
operações; TTL físico não configurado. Não há promessa de custo zero.

## Testes e isolamento

Unidades novas cobrem referência exata, seleção explícita, versão/configuração
incompleta e inválida, limites de todos os scopes, segredo ausente, HMAC versão
incompatível, composição padrão preservada, objetos revalidados, política antiga,
divergência e ciclo de login/sessão/CSRF/logout. Argon2 e sessões reais são usados
no ciclo sintético; lookup por e-mail é mockado, sem Firebase real.

Emulator novo reutiliza fixture que SOBRESCREVE a limpeza global legada:
loopback, projeto demo, credenciais anônimas, segredo sintético UUID por teste e
exclusão somente de IDs calculados por ele. Comprova preservação dos débitos
antigos na transição e divergência entre dois clientes sem consumo parcial.
Não apagar dados usados no Chrome nem executar a suíte global do Emulator.

## Resultados executados

- 46 novos casos unitários aprovados e dois novos casos no Emulator aprovados.
- Conjunto específico de configuração/política/admissão/composição/login/origem:
  356 aprovados.
- Suíte unitária completa: 1.341 aprovados, 52 subtestes aprovados,
  228 testes de integração desselecionados.
- Emulator isolado, configuração + complementares + dimensionamento: dez aprovados.
- git diff --check passou; alterações locais anteriores preservadas.
- Primeiro ensaio: 43 aprovados e um erro de montagem por fixture sessions não
  importada no teste novo. Corrigido somente o import; nenhum defeito de produção
  foi identificado. Nenhuma falha permaneceu. Aviso existente de depreciação
  TestClient/httpx, sem instalar dependências. Contagens não devem ser somadas.

Comandos principais na raiz do projeto:

```sh
PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider Backend/tests/test_admin_admission_policy_config.py
PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider Backend/tests
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test PYTHONDONTWRITEBYTECODE=1 Backend/.venv/bin/python -m pytest -q -p no:cacheprovider --run-firestore-emulator Backend/tests/emulator/test_admin_admission_policy_config_integration.py Backend/tests/emulator/test_admin_complementary_admission_integration.py Backend/tests/emulator/test_admin_admission_sizing_integration.py
```

Nenhum router publicado, serviço externo alterado, segredo real acessado,
servidor reiniciado ou bucket/sessão do usuário redefinido. Não iniciar PASSO 86.
