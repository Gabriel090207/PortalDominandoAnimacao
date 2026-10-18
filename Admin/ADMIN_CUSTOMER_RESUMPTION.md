# PASSO 67 — Retomada na ficha do cliente

## Ação e autoridade

A ficha `/clientes/:customerId` oferece **Retomar acesso** somente com sessão válida,
`read_customers` + `resume_customer`, cadastro pronto, account_status=enabled e
activation_status=suspended. Owner e operator usam as mesmas permissões, sem bypass
por papel. Loading, erro cadastral, ausência de cliente, logout, pending, active,
blocked ou outra operação incompatível não oferecem nova confirmação.

A disponibilidade é administrativa, não comprova elegibilidade comercial. Não depende
da confirmação de compra registrada e não consulta auditorias nem calcula períodos
no navegador. O Backend verifica histórico legítimo, compra, entitlement e demais
pré-condições. Dados legados sem evidências podem ser rejeitados; não há reparo local.

## Confirmação e HTTP

CustomerResumption reutiliza CustomerAccessAction e customerAccessStore: confirmação
inline com fieldset/legend, e-mail, consequência e aviso de que o acesso permanece
condicionado às verificações do sistema. Checkbox com label inicia desmarcado;
Cancelar não envia POST. A UI compartilha foco visível, foco no checkbox ao abrir,
retorno ao botão ao cancelar, mensagens acessíveis e carregamento das outras ações.
Não há novo modal, reformulação da ficha ou lógica financeira.

A instância Axios existente usa VITE_API_URL, withCredentials, Content-Type
application/json e X-Admin-Request: 1. `resumeCustomer` valida/codifica o identificador
com customerPath e envia somente:

POST /admin/customers/{customer_id}/resume
{"confirm_resumption":true}

CustomerResumptionResult confirma o contrato real do Backend: customer_id correspondente,
activation_status=active e result=resumed|already_active. A resposta é projetada;
campos extras não são expostos. Não há outro Axios, URL fixa, token acessível, cookie
lido por JavaScript, log sensível ou auditoria criada no frontend.

## Resultados e atualização

- resumed: “Acesso retomado com sucesso.”
- already_active: “Este cliente já está ativo.” Sem alegar nova transição.
- Ambos fecham a confirmação e limpam o consentimento. O GET da ficha é a fonte do
  cadastro atualizado: não há alteração otimista de activation_status/account_status.
- A confirmação comercial previamente consultada é mantida; retomada não cria compra,
  direito, renovação ou pagamento. Não promete acesso permanente.
- Se o POST confirmar e o GET falhar, a mensagem mantém o resultado confirmado,
  explica que a atualização não foi concluída e oferece nova consulta. O detail store
  remove o cadastro antigo; ações não usam dados obsoletos.
- 400/413/415/422: requisição inválida; 401: invalidação central e limpeza de dados;
  403: autorização negada sem logout; 404: cliente ausente.
- 409: “Não foi possível retomar o acesso nas condições atuais. Verifique a situação
  do cliente antes de tentar novamente.” Não presume ausência de auditoria: o mesmo
  código pode representar outros impedimentos. Não chama activate nem fabrica histórico.
- 503, timeout, rede, resposta inesperada ou erro não classificado: resultado incerto,
  sem alegar sucesso ou ausência de gravação. Não há retry automático de escrita.

“Atualizar situação” executa somente GET. Uma consulta bem-sucedida apresenta o estado
atual sem atribuir uma alteração ao POST anterior. Se ainda suspenso, uma nova tentativa
exige nova abertura, checkbox desmarcado e confirmação humana. Não há polling.

## Coordenação e ciclos na mesma ficha

O coordenador por ficha existente é compartilhado entre ativação, suspensão e retomada.
Uma confirmação aberta já reserva a operação; POSTs repetidos compartilham a Promise
em andamento. A elegibilidade é novamente verificada antes do despacho. Operações
incertas e falhas de reconsulta mantêm o bloqueio até reconciliação GET bem-sucedida.
Não é estado global e não substitui as transações/autorização do Backend.

Para permitir ciclos legítimos resume -> suspend -> resume sem recarregar a página,
o fluxo compartilhado pode abrir nova confirmação a partir de um resultado confirmado
somente após GET bem-sucedido, quando os dados atuais tornam a ação novamente elegível
e o coordenador está livre. Isso não repete POST automaticamente nem reabre um resultado
incerto. O consentimento e a mensagem anterior são limpos a cada nova confirmação.
As regras da ativação inicial permanecem inalteradas.

Troca de cliente cria contexto próprio; desmontagem, logout, perda/troca da sessão
limpam os stores e invalidam respostas antigas. Uma resposta tardia não restaura
informações privadas nem inicia GET no contexto antigo. Nenhuma confirmação vai para
localStorage/sessionStorage. Limpar a UI não cancela um POST já recebido pelo servidor.

## Validação e limitações

Testes sintéticos usam adapters Axios locais, stores e markup SSR da infraestrutura
existente. Incluem transporte, respostas estritas, owner/operator, estados, consentimento,
cancelamento, erros, incerteza, GET, ciclos, exclusão entre as três ações e limpeza por
logout/perda de sessão. Regressão preserva login/logout, rotas, listagem/paginação,
pesquisa, ficha, compra, ativação e suspensão. Nenhuma API publicada ou Firebase foi usado.

Não houve revisão real em navegador: a tentativa de acessar o Chrome local retornou
**Computer Use permissions are not granted**. Os testes de markup SSR não executam
eventos DOM, efeitos de foco, teclado ou layout real. Homologação visual/interativa,
responsividade e ausência de overflow em tamanhos reais continuam pendentes.

Somente Admin/ foi alterado. Backend/ e Frontend/ dos alunos permanecem intactos.
O router continua isolado fora de app.main; não houve publicação, configuração de
Render/Netlify/DNS, migração, alteração de permissões/sessões/Kirvano, bloqueio ou
funcionalidade financeira. Nenhuma dependência foi instalada.

Validação final: **316 testes aprovados, zero falhas** (57 novos casos).
`npm run typecheck`, `npm run build`, `npm run lint` e `git diff --check` aprovados.
O build gerou apenas os artefatos locais habituais em dist/. A comparação SHA-256
com o snapshot inicial confirmou Backend/ e Frontend/ intactos nos arquivos-fonte,
configuração e documentação (excluídos dependências, caches e builds).
