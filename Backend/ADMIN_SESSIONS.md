# Infraestrutura interna de sessões administrativas

Não há endpoint, login, cookie ou integração com frontend nesta etapa. Nenhum
contrato de domínio foi alterado. AdminSessionService recebe um repositório;
AdminSessionsRepository recebe um cliente Firestore explicitamente injetado.
Não há inicialização Firebase na importação ou nesses construtores. A futura
composição da API poderá usar o serviço Firebase central existente, banco default.

`create(authenticated_admin)` só deve ser chamado após autenticação bem-sucedida.
Receber um objeto Admin NÃO comprova conhecimento da senha. A futura camada de
login deve fornecer o administrador e auth_version associados à autenticação.
A criação relê o AdminRecord em transação, exige vínculo do ID, administrador
habilitado e a mesma versão; cria a sessão somente com precondição de inexistência.
Não modifica o administrador nem exige executar bootstrap.

O token é gerado por secrets.token_hex(32): 256 bits aleatórios. Só o resultado
da criação contém o token, em SecretStr e excluído de repr; o chamador interno
obtém o valor com token.get_secret_value() para futura entrega segura ao cliente.
Nunca registre esse valor nem serialize um resultado de criação indiscriminadamente.
O ID do documento em admin_sessions é SHA-256 de um prefixo fixo de propósito e
do token. O documento usa exatamente AdminSessionRecord, sem token nem hash de
senha. A resistência do digest depende da alta entropia do token gerado. O prefixo
e o formato não devem ser alterados sem estratégia para sessões existentes.

`get_session(token)` é consulta interna: pode retornar sessão expirada/revogada
e NÃO autoriza acesso. `validate(token)` lê sessão e administrador atual numa
transação consistente e aplica is_admin_session_valid. Retorna Admin sem hash
apenas se a sessão existir, estiver dentro de [criação, expiração), não estiver
revogada, e administrador, estado e auth_version forem compatíveis. Pode receber
expected_admin_id para exigir um administrador específico. Ausência/invalidade
retorna None; falha de armazenamento ou estrutura inválida gera erro sanitizado,
jamais autenticação bem-sucedida. Permissões ainda devem ser verificadas à parte.

`revoke(token, reason=LOGOUT)` é transacional. Retorna True somente na primeira
mudança, preservando data e motivo em repetições; sessão ausente retorna False.
A revogação não remove o documento e não prolonga expiração. A validade permanece
em oito horas absolutas, sem renovação deslizante. Horário deve vir do backend,
nunca de entrada HTTP; now explícito permite testes determinísticos.

Somente a revogação possui até três execuções externas, cada uma com novo runner
e nova transação. Repete exclusivamente Aborted ou ValueError com causa explícita
Aborted, antes de sanitizar a exceção. Entre execuções, fora da transação, aguarda
50–100 ms e depois 100–200 ms (jitter uniforme). Não espera após a última falha.
O SDK mantém suas próprias tentativas internas (cinco na versão validada),
podendo resultar em até quinze tentativas de commit nessa configuração.
Entradas e callback permanecem iguais; uma revogação já concluída retorna False
sem modificar sua origem. Permissão, validação, rede e commit de resultado incerto
não recebem retentativa externa. Esgotamento continua sendo erro sanitizado,
nunca confirmação de logout. Criação e validação não receberam esse mecanismo.

Colisões não sobrescrevem sessões: geram até três tentativas com novos tokens.
Falhas de comunicação/commit não provocam nova emissão automática. Em resultado
incerto, pode existir uma sessão inacessível ao cliente até expirar. Os erros
públicos internos são sanitizados, sem documentos, tokens ou texto bruto do SDK.

O domínio não limita sessões Admin simultâneas. Esta entrega não adiciona esse
limite, exclusão TTL, revogação em lote ou operações para alterar auth_version.
Futuras alterações de credenciais/permissões devem incrementar essa versão.
A validação consulta os fatos atuais; como toda autorização, sua decisão é
referente ao snapshot lido. Uma ação sensível que exija atomicidade com alterações
de permissão precisará validar dentro da própria transação dessa ação.
Os serviços são síncronos; endpoints assíncronos deverão executá-los fora do loop.

Testes unitários: `.venv/bin/python -m pytest -q tests/test_admin_sessions.py`.
Integração: usar a infraestrutura e os guards descritos em tests/emulator/README.md
com tests/emulator/test_admin_sessions_integration.py. Somente localhost e projeto
demo-dominando-animacao-test, AnonymousCredentials e bloqueio do Firebase real.
