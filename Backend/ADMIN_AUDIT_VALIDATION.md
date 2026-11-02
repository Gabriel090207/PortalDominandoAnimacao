# PASSO 76 — persistência e auditoria administrativa

Validação local de 22/10/2026, exclusivamente no projeto demo
`demo-dominando-animacao-test`, endpoint `127.0.0.1:8080`. Nenhuma mudança na
lógica de produção, modelos, permissões, retentativas ou apresentação do Admin.

## Contratos confirmados

Os serviços `AdminActivationService`, `AdminSuspensionService` e
`AdminResumptionService` delegam aos respectivos repositórios. A API obtém o
administrador de `AdminSessionService.validate`, exige a permissão da operação,
Origin autorizado, X-Admin-Request e confirmação explícita no JSON. Campos extras
de autor são rejeitados; o navegador não escolhe o autor da auditoria.

Coleção real: **activation_audit**. Cada auditoria contém exatamente:

| Campo | Semântica |
|---|---|
| schema_version | 1 |
| admin_id | Administrador autenticado que executou a operação |
| customer_id | Documento do cliente afetado |
| operation | Operação, conforme tabela abaixo |
| previous_activation_status | Estado anterior da transição |
| activation_status | Estado resultante |
| human_confirmation | true |
| occurred_at | Data/hora com fuso, obtida pelo relógio do backend |

| Operação | Transição | Repetição sem nova transição | Tentativas nativas máximas |
|---|---|---|---:|
| activate_customer | pending → active | already_active | 8 |
| suspend_customer | active → suspended | already_suspended | 5 |
| resume_customer | suspended → active | already_active | 8 |

`occurred_at` não é um timestamp de commit do Firestore. O documento tem ID UUID
gerado pelo backend, estável durante as retentativas daquela chamada. Não contém
e-mail, senha, cookie, token, hash de senha ou dados financeiros.

## Atomicidade, autorização e acesso

Cada repositório lê o cliente e revalida status, papel e auth_version do autor
persistido na mesma transação. Após todas as leituras, atualiza somente
`users.activation_status` e cria a auditoria. O commit atômico inclui ambos.
Uma falha de criação da auditoria impede a transição; erro/resultado incerto não
é convertido em sucesso. Não há retentativa externa introduzida neste passo.

Ativação e retomada usam `has_eligible_portal_access`, que resolve
entitlement → purchase → subscription e delega à regra `can_access_portal`.
Cancelamento/vencimento não sustentam a transição. A retomada também exige
evidência de ativação e suspensão anteriores, com contratos e sequência temporal
válidos. A suspensão independe de uma compra atual e impede acesso sem alterar
account_status ou documentos comerciais. Renovação não remove a suspensão.

Os no-ops não criam auditoria nem significam concessão comercial de acesso.
A idempotência é baseada no estado persistido; não há chave global de requisição.
Uma nova suspensão após retomada é uma transição real, com nova auditoria.

## Evidência do cliente usado na homologação

Consulta somente de leitura do cliente sintético `local-step74-customer-v1`:

- Conta enabled e ativação active.
- Uma auditoria activate_customer, uma suspend_customer e uma resume_customer.
- Três contratos de auditoria válidos e três referências de autor existentes.

Esse cliente e o administrador da homologação não foram modificados pela
validação. Os servidores existentes permaneceram ativos. Não houve controle do
Chrome, acesso à produção, publicação ou operações sobre administradores reais.

## Testes não destrutivos

Arquivo: `tests/emulator/test_admin_audit_validation_integration.py`. Reutiliza a
fixture não destrutiva do PASSO 74, substituindo a fixture padrão que limpa todo
o emulator. Cada cenário usa um cliente e um administrador próprios, com IDs
únicos, e remove somente seus documentos/auditorias/sessões. Não executar a pasta
inteira `tests/emulator` no ambiente de homologação ativo: testes antigos ainda
usam limpeza global.

```sh
# A partir de Backend/, usando apenas o emulator demo ativo:
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 \
FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test \
.venv/bin/python -m pytest --run-firestore-emulator -q \
  tests/emulator/test_admin_audit_validation_integration.py
```

Cobertura adicional:

- Ciclo HTTP completo nos papéis owner/operator, confirmação, rejeição sem
  sessão, autor forjado, releitura e repetição sem novos registros.
- Estados anteriores/novos, autor, cliente, campos exatos e datas dos registros.
- Preservação do conteúdo e update_time dos documentos comerciais preexistentes.
- Falha ao enfileirar auditoria e falha antes do commit: nenhuma mudança parcial.
- Aborted sintético após rollback real: recuperação e esgotamento dos limites
  nativos existentes (8/5/8), sem ampliação de tentativas.
- Perda simulada da resposta depois de um commit real: exceção não confirmada,
  estado e auditoria gravados juntos; releitura/no-op não duplicam a auditoria.
  Isso representa um resultado incerto, não garante como toda falha de rede ocorre.
- Três disputas para cada operação igual e três entre suspensão/retomada,
  além das duas ordens seriais. Não se presume qual concorrente vencerá.
- Conta blocked, autor desabilitado/auth_version alterada, cancelamento,
  vencimento e histórico ausente: rejeição sem efeitos adicionais.
- Renovação sintética pela transação comercial existente mantém a suspensão.

Uma resposta não confirmada em corrida é registrada como tal e confrontada com
os documentos persistidos, nunca contada como sucesso. As exceções inesperadas
não são aceitas indistintamente. Os testes não prometem que toda disputa terá
duas respostas bem-sucedidas.

## Resultados e limites

- Backend: 1.236 testes unitários e 52 subtestes aprovados.
- Admin: 326 testes aprovados, sem mudanças de apresentação ou comportamento.
- Emulator: 46 testes aprovados na rodada final; 12 cenários concorrentes
  registrados, sem respostas não confirmadas observadas. As três disputas entre
  suspensões deixaram uma transição e uma auditoria cada, com um no-op concorrente.
- `git diff --check` sem erros.

As suítes legadas de integração de ativação/suspensão/retomada não foram
executadas com a fixture destrutiva no emulator ativo. Seus cenários unitários
foram executados e os cenários transacionais acima foram verificados pela nova
suíte. A intermitência antiga de suspensão concorrente **não está resolvida** por
uma execução aprovada; exige acompanhamento, sem retentativas arbitrárias.

Não foi identificado defeito de produção reproduzível que exigisse correção.
O histórico da retomada é consultado com limit(1) por cliente/operação, sem
ordenação explícita; ele prova evidência histórica válida, não uma referência
direta à última suspensão. A auditoria atual não possui campo de vínculo ao
evento anterior nem ID de commit. Esses limites foram documentados, não
transformados automaticamente em mudanças de contrato.

Esta validação não testa IAM, imutabilidade contra operadores com acesso direto
ao banco ou contenção/carga no Firestore de produção. Reembolso/chargeback
continuam adiados. Nenhum PASSO 77 foi iniciado.
