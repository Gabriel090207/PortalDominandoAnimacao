# Admissão administrativa interna (ainda não habilitada)

AdminLoginService coordena a admissão e AdminAuthService internamente. Não há
endpoint, leitura de headers, alteração de conta ou inicialização Firebase. O serviço recebe repositório, política,
segredo HMAC dedicado e relógio por injeção. Não lê .env, não gera credenciais e
não tem limites padrão de produção. Nenhum recurso real foi configurado.

AdminAdmissionPolicy exige duas BucketPolicy independentes: origem e
origem+identidade. Cada política exige capacidade inteira positiva, quantidade
de tokens de reposição e período inteiro positivo em segundos. Coerções de bool,
strings, floats, campos extras e valores fora da faixa de armazenamento são
rejeitadas. Alterar uma política para os mesmos IDs exige migração explícita:
registros de política diferente falham fechados, sem reiniciar cotas.

O saldo usa inteiros: um token equivale ao período de reposição em microssegundos
e cada microssegundo adiciona refill_tokens unidades. Isso permite reposição
fracionária exata sem saldo float. Toda admissão custa um token em CADA bucket.
O saldo é limitado à capacidade. A decisão retorna allowed ou limited e espera
arredondada para cima em segundos, sem identificar publicamente o bucket.
Entrada, configuração, armazenamento ou relógio inválidos geram
AdminAdmissionUnavailable com mensagem fixa, sem detalhes de origem/identidade.

O método admit exige e-mail válido, normalizado pela política existente, e uma origem
canônica previamente validada por camada confiável. Origem é um identificador
opaco, NÃO uma alegação autenticada pelo serviço. Não inferir confiança por
X-Forwarded-For nem repassar headers diretamente. O método admit_attempt, usado pelo coordenador, também admite entradas de
e-mail inválidas: todas compartilham um bucket origem+identidade inválida por
origem, com escopo HMAC origin_invalid_identity distinto de qualquer e-mail real.
O bucket geral da origem mantém exatamente o mesmo ID. Os dois buckets usam
as mesmas políticas e transação existentes; nenhum e-mail inválido é persistido.
Após admissão confirmada, AdminAuthService mantém sua verificação dummy e
rejeição genérica, sem consultar admins. admit preserva seu contrato estrito.

IDs são HMAC-SHA-256 de propósito, versão de identidade, versão de chave, escopo
e valores canonicalizados. Os escopos origem e origem_identidade são distintos.
O segredo deve ter pelo menos 32 bytes UTF-8 e ser forte, dedicado e igual entre
instâncias. Não utilizar EMAIL_IDENTITY_HMAC_SECRET ou credenciais comerciais.
Seu fornecimento é responsabilidade da composição futura, não do ambiente nesta
entrega. Nenhum segredo, e-mail ou IP é persistido nos documentos. IDs HMAC são
pseudonimizados; não são garantia de anonimato. Rotação/chave/versionamento mudam
os IDs e podem reiniciar cotas: exigem plano operacional, não rotação automática.

AdminAdmissionRepository usa somente auth_throttles e dois IDs diretos. Lê ambos
antes de escrever, verifica saldo e cria/atualiza os dois no MESMO commit. Quando
um limite é atingido, não escreve nem cria parcialmente o outro bucket e não
prolonga a restrição. Não existe documento global, consulta de admins ou bloqueio
global por e-mail. Outra origem não é bloqueada por um ataque ao mesmo e-mail.
O bucket por origem continua compartilhado entre seus diferentes e-mails.

O SDK executa suas retentativas internas; o callback só faz leituras/escritas
Firestore e aritmética. Não executa Argon2, autenticação, sessões, sleeps, geração
de IDs ou chamadas externas. O instante é capturado uma vez antes da transação.
Não há retentativa externa: falha/resultado incerto não concede admissão. Uma
confirmação perdida pode consumir os dois saldos sem autorizar o chamador; não
presumir rollback nem repetir indiscriminadamente. Não há fallback permissivo.
O resultado é decisão interna para UMA autenticação, não um token ou
permissão reutilizável apresentado pelo cliente. AdminLoginService faz nova
admissão para cada chamada antes de invocar a autenticação. Não há transação
de admissão aberta durante consulta de admins, Argon2 ou criação de sessões.

expires_at indica quando o saldo pós-consumo estaria COMPLETAMENTE reposto.
A recuperação lógica é feita pela aritmética, mesmo que o documento continue
existindo. TTL é limpeza opcional, não ativada nesta etapa; excluir antes de o
bucket estar cheio enfraqueceria a política. Campos e custo de indexação/TTL
deverão ser revisados na implantação. Sem TTL, há crescimento de documentos por
novas origens/identidades; exclusão exige política de retenção aprovada.

Relógio: injetar UTC timezone-aware de fonte do backend, nunca do cliente. O
instante lógico é o maior entre o relógio e os últimos instantes dos dois buckets;
um relógio atrasado não gera saldo novo nem recua timestamps. Saltos para a frente
PODEM antecipar reposição/expiração. Antes de habilitar múltiplas instâncias,
confirmar sincronização UTC/NTP e tolerância operacional de skew, monitorar saltos
ou adotar fonte de tempo validada no servidor. Esta entrega não presume que
relógios arbitrários ou não sincronizados forneçam um limite temporal estrito.

Custo esperado: duas leituras e duas escritas por admissão concluída, duas leituras
por rejeição, mais retentativas do SDK e eventual limpeza. Alta contenção pode
gerar indisponibilidade segura; não há promessa de atendimento de todas as
solicitações concorrentes. Ataques distribuídos e volumétricos ainda exigirão
controles adicionais. Não publicar login só por existir essa infraestrutura.

Pendências de implantação: limites calibrados e aprovados, origem/proxies
confiáveis, segredo dedicado/rotação, relógio sincronizado, TTL/retencão/custos e
composição HTTP explícita com o coordenador e execução fora do event loop. Nenhuma dessas decisões
habilita automaticamente o mecanismo em produção.

Testes unitários: tests/test_admin_admission.py. Integrações:
tests/emulator/test_admin_admission_integration.py, usando exclusivamente a
fixture guardada existente, localhost, AnonymousCredentials e projeto demo.

## Política inicial aprovada e uso explícito

`app.domain.policies.INITIAL_ADMIN_ADMISSION_POLICY` disponibiliza um
AdminAdmissionPolicy imutável, validado pelos mesmos BucketPolicy existentes:

| Bucket | Capacidade | Reposição |
| --- | ---: | --- |
| origem | 10 | 1 token a cada 30 segundos |
| origem + identidade | 5 | 1 token a cada 60 segundos |

A futura composição deve passar essa constante como `policy=` ao construir
AdminAdmissionService, mantendo repositório, segredo HMAC e relógio explícitos.
AdminLoginService recebe esse serviço já construído. A constante é carregada do
código ao importar policies; não consulta ambiente nem fornece segredo. Importar
não instancia serviços, não acessa Firestore e não habilita login HTTP. Políticas
alternativas continuam possíveis por injeção de AdminAdmissionPolicy validado,
sem alterar o algoritmo. Nenhuma configuração de produção foi aplicada.

Toda tentativa admitida custa um token em cada bucket, inclusive falhas posteriores
e sucesso. Não existe reset após login. E-mails inválidos mantêm seu bucket
reservado por origem. A recuperação é gradual: após esgotamento completo, um token
por origem fica disponível em 30 segundos e por identidade em 60 segundos; ambos
ficam cheios após 5 minutos sem consumo. A capacidade máxima limita acúmulo.
Vários administradores no mesmo IP compartilham as dez admissões iniciais.

## Futuras mudanças de política (procedimento não executado)

Uma divergência entre política persistida e injetada interrompe a admissão com
AdminAdmissionUnavailable, sem modificar buckets ou chamar autenticação. Isso
ocorre também em documentos expirados: expiração não converte o contrato.
Apenas trocar valores pode causar indisponibilidade. Mudar a chave/versão HMAC
para contornar a comparação reiniciaria orçamentos e não é migração implícita.

Estratégia recomendada para uma futura transição, sujeita a aprovação separada:

1. Aprovar nova política e procedimento; inventariar políticas antigas e conferir
   integridade dos registros e relógios.
2. Suspender somente admissões administrativas em todas as instâncias, drenar
   operações em andamento e impedir chamadas por versões antigas.
3. Aguardar recuperação completa de TODOS os buckets antigos, usando expires_at
   e margem de relógio aprovada. Para a política inicial são cinco minutos desde
   o último consumo apenas com relógios confiáveis e documentos íntegros;
   outras políticas podem exigir mais tempo.
4. Com autorização específica, remover somente registros administrativos de
   admissão já completamente recuperados, ou executar migração projetada e testada.
   Não limpar auth_throttles inteira: a coleção pode conter outros propósitos.
   Não tocar administradores ou sessões.
5. Implantar a política uniforme em todas as instâncias antes de reabrir o fluxo.
   Validar o procedimento no emulador previamente e planejar rollback: voltar ao
   código antigo também exige considerar documentos já escritos na política nova.

A espera evita conceder capacidade antes da recuperação natural. Um bucket cheio
representado por ausência de documento já é suportado pelo algoritmo. A ferramenta
operacional, a seleção segura dos registros e a janela de manutenção ainda exigem
aprovação e implementação próprias. Migração online durante tráfego exigiria uma
nova decisão arquitetural. Não há migração automática nesta entrega; nenhum bucket
foi apagado, redefinido ou migrado.

## Configuração privada do segredo administrativo

A variável dedicada é ADMIN_ADMISSION_HMAC_SECRET. O carregador explícito
`app.config.admin_admission.load_admin_admission_config()` só deve ser chamado ao
compor a funcionalidade administrativa. Não é chamado no startup público atual.
Ausência ou erro não afeta rotas públicas ou Kirvano que não inicializam Admin.

Representação: exatamente 64 caracteres hexadecimais minúsculos, sem espaços,
correspondentes à representação de 32 bytes obtidos de um gerador criptográfico
seguro (256 bits de entropia na geração). Senhas, frases e identificadores não são
fontes adequadas. Formato e comprimento são verificáveis; nenhum validador pode
comprovar a aleatoriedade ou procedência do valor. Não usar os exemplos sintéticos
dos testes. Nenhum segredo real foi gerado nesta etapa.

Para preservar o HMAC existente, os 64 caracteres são utilizados exatamente como
texto UTF-8 na chave HMAC-SHA-256, SEM decodificar o hexadecimal em bytes. Essa
convenção faz parte da identidade dos buckets e não deve ser alterada depois.
O segredo fica em SecretStr com repr oculto. A composição futura deve passar
`config.secret.get_secret_value()` para admission_hmac_secret e config.key_version
para key_version ao construir AdminAdmissionService. Não imprimir a configuração,
serializar seu segredo ou registrar argumentos/variáveis locais em diagnósticos.

O ambiente efetivo do processo tem prioridade sobre Backend/.env, inclusive se
contiver valor vazio ou inválido: não há fallback nesse caso. O arquivo é lido
somente na chamada explícita, sem interpolação, sem alterar os.environ e sem
reescrever arquivos. O carregador permite injetar um mapping/arquivo de teste ou
usar env_file=None para desativar leitura de arquivo. Não procura segredos de
outros propósitos nem gera substitutos. Falhas produzem
AdminAdmissionConfigurationError com mensagem fixa, sem valor ou causa exposta.
A versão inicial da chave é explicitamente 1; não é uma opção automática de rotação.

Futura configuração no Render: após autorização e antes de inicializar Admin,
criar o valor num ambiente seguro/gerenciador de segredos e cadastrar a variável
na seção Environment do backend. Não compartilhar pelo chat, Git, frontend ou
linha de comando com histórico. Usar o mesmo valor, versão de chave e política
aprovada em TODAS as instâncias. Não alterar o segredo comercial ou webhook.
Nada disso foi configurado no Render nesta entrega.

Rotação muda todos os IDs HMAC e pode conceder buckets cheios enquanto os antigos
continuam existindo. Instâncias com chaves distintas deixam de compartilhar cotas.
Não trocar o valor arbitrariamente, nem mesmo mantendo key_version=1. Uma rotação
planejada exige versionamento explícito e estratégia aprovada para preservar as
restrições (por exemplo, janela controlada de recuperação e troca coordenada),
incluindo rollback e documentos antigos. O procedimento de mudança de política
acima não é implementado automaticamente para rotação. Não há dupla chave, migração,
rotação automática ou persistência do segredo no Firestore.
