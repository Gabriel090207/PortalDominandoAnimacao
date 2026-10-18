# PASSO 65 — Suspensão na ficha do cliente

## Disponibilidade e confirmação

A ficha `/clientes/:customerId` oferece **Suspender acesso** apenas com sessão válida,
`read_customers` e `suspend_customer`, dados cadastrais prontos, conta `enabled` e
ativação `active`. O papel não cria bypass: owner e operator usam as mesmas permissões.
A suspensão não depende de compra registrada, vigente ou confirmação comercial.
Loading/erro cadastral, cliente ausente, conta blocked, pending/suspended e logout
não oferecem a ação. O Backend continua sendo autoridade para a transição.

A confirmação inline compartilha o componente acessível da ativação: fieldset,
legend, e-mail, consequência, nota de que não cancela assinatura na Kirvano,
checkbox com label inicialmente desmarcado e botões Cancelar/Confirmar suspensão.
Não há modal nem necessidade de armadilha de foco. O código foca o checkbox ao abrir,
o botão ao cancelar e a mensagem após resultado; botões têm foco visível.
A suspensão tem borda tracejada e textos próprios, sem depender apenas de cor.

## HTTP e estados

A instância Axios existente usa VITE_API_URL e withCredentials. A nova função
`suspendCustomer` envia POST ao segmento validado e codificado por customerPath,
com JSON contendo somente `confirm_suspension: true`, Content-Type application/json
 e X-Admin-Request: 1. Valida ID, activation_status=suspended e os dois resultados
reais, projetando somente os campos da resposta. Não há outro Axios, token acessível,
log, auditoria local, domínio fixo ou retry de escrita.

- suspended: “Acesso suspenso com sucesso.”
- already_suspended: “Este cliente já está suspenso.” Sem alegar nova transição.
- Ambos fazem GET da ficha. A UI não muda activation_status otimisticamente.
- A confirmação comercial já consultada é preservada; não se altera account_status,
  e-mail, compras ou dados financeiros. “Suspensa” permanece a tradução existente
  do status de ativação, distinta de “Bloqueada” para a conta.
- Falha no GET após POST confirmado preserva a mensagem do resultado confirmado,
  mas explica a falha de atualização. O cadastro obsoleto é removido pelo detail store.
- 400/413/415/422: requisição inválida; 403: autorização negada sem logout;
  404: cliente não encontrado; 409: conflito, sem sucesso.
- 401 usa a invalidação central existente e limpa os stores privados.
- 503, timeout, rede e resposta inesperada são resultados incertos. Não indicam
  sucesso nem ausência de gravação. Há somente “Atualizar situação” por GET.
- GET explícito bem-sucedido libera nova avaliação/confirmacão manual se ainda ativo.
  Um cadastro atualmente suspenso não prova que a tentativa anterior causou a mudança.

## Coordenação e ciclo de vida

O fluxo antes exclusivo da ativação foi extraído para customerAccessStore e a
apresentação para CustomerAccessAction, mantendo o contrato e textos da ativação.
Um coordenador por ficha usa identificadores em memória para impedir confirmações,
escritas e reconsultas incompatíveis entre ativação e suspensão. Não é estado global.
O bloqueio permanece após resultado incerto/erro de atualização até GET explícito
bem-sucedido. Não há polling, POST em useEffect ou retry automático.

Chamadas repetidas compartilham a Promise em andamento; a confirmação desaparece
durante o envio e o consentimento é limpo. O despacho verifica novamente a elegibilidade.
Troca de customerId recria o contexto da ficha; desmontagem/logout/perda ou troca de
sessão limpam confirmação, dados e gerações de resposta. Respostas tardias não restauram
informações nem iniciam GET em contexto antigo. Limpar a UI não cancela um POST que
já chegou ao servidor. Nada é persistido em localStorage/sessionStorage.

## Validação e limites

Dados sintéticos e adapter Axios local; nenhuma chamada à API publicada/Firebase.
Testes existentes de sessão, login/logout, rotas, listagem/paginação, pesquisa,
compra e ativação são mantidos. Novos testes cobrem HTTP, permissões, confirmação,
idempotência, erros/incerteza, GET, coordenação, limpeza e markup SSR.

A infraestrutura atual testa stores, transporte e HTML gerado por SSR. Não executa
eventos DOM reais, efeitos de foco ou layout no navegador. A acessibilidade de foco,
teclado, contraste e ausência de overflow em larguras reais precisa de homologação
visual e interativa; nenhuma revisão real em navegador foi realizada neste passo.

Somente Admin/ foi alterado. Backend e Frontend dos alunos foram preservados.
O router do Backend continua isolado fora de app.main; a integração depende de
habilitação futura aprovada e validação operacional das configurações de produção.
Não há retomada, bloqueio/desbloqueio, alteração financeira ou publicação neste passo.
