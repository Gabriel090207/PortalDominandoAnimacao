# Admin — aplicação independente

Frontend exclusivo de administradores, ao lado de Frontend/ e Backend/. Não importa
código interno do portal dos alunos. A aplicação possui login em / e uma área mínima protegida em /painel, sem dashboard
completo. Ao iniciar, consulta a sessão por GET antes de liberar conteúdo. Login
e logout só ocorrem por ação explícita do usuário.

## Desenvolvimento

Testado com Node 24.13 e npm 11.6. Dependências próprias e package-lock.json próprio.
Instalação reproduzível: `npm ci`. Scripts, executados dentro de Admin/:

- `npm run dev`: Vite local.
- `npm run typecheck`: TypeScript dos arquivos de aplicação/configuração, em modo strict.
- `npm run build`: TypeScript e build Vite em dist/.
- `npm run lint`: oxlint, conforme convenção do projeto.
- `npm test`: node:test com adapter Axios sintético; nenhum endpoint é acessado.
- `npm run preview`: pré-visualização local do build.

React/ReactDOM, Axios, TypeScript, Vite/plugin React, tipos e oxlint seguem as faixas
de versão do Frontend existente. Nenhum router, biblioteca visual ou framework de
testes adicional foi instalado. node_modules, dist e arquivos .env privados são ignorados.

## Configuração pública

Copiar .env.example para .env apenas quando houver API de teste/homologação aprovada.
VITE_API_URL é a URL base HTTPS configurável da API. Não há host de produção padrão
nem fallback same-origin/proxy. Configuração ausente/inválida falha ao invocar o
serviço, sem envio. Nunca inserir HMAC, senha, token ou credencial em VITE_*: essas
variáveis são públicas e incorporadas ao build. Reiniciar/recompilar após alterá-las.

HTTPS é obrigatório no cliente administrativo para manter cookies Secure. Não existe
bypass de desenvolvimento para HTTP localhost ou proxy temporário para contornar CORS.
Sem configuração de API, a consulta inicial falha com mensagem segura e não há
acesso ao painel. Um teste
real posterior requer TLS local ou ambiente HTTPS aprovado e configuração backend compatível.
Os domínios finais ainda serão escolhidos; nenhum foi fixado aqui.

## Serviços

src/services/adminApi.ts exporta loginAdmin, getAdminSession e logoutAdmin. O cliente
Axios é construído sob demanda e usa withCredentials:true. createAdminApi permite
configuração explícita e adapter injetado nos testes, sem mock automático de produção.

- Login: POST /admin/auth/login, JSON {email,password}, X-Admin-Request:1. Não valida
  sintaxe de e-mail antes do backend. Retorna somente {admin_id}.
- Sessão: GET /admin/auth/session. Retorna admin_id, email, role owner/operator e as
  permissões existentes. Não exige expires_at. Permissões locais só orientam UI;
  autorização definitiva continua no backend.
- Logout: POST /admin/auth/logout, sem corpo/token, com X-Admin-Request:1. Só confirma
  por resposta {success:true}; rede/503/resposta inesperada rejeitam a operação.

Não há armazenamento de tokens, leitura de cookies HttpOnly, Authorization manual,
Origin manual ou retries automáticos. Respostas são projetadas somente nos campos
aprovados, com validação mínima do formato. Dados de resposta não são segredos para
persistir; nenhuma funcionalidade aqui os grava em storage.

AdminApiError contém mensagem fixa, kind, status e Retry-After opcional. Distingue
credenciais (401 login), sessão inválida (401 demais operações), origem/CSRF (403),
limitação (429), requisição inválida (400/422), tamanho (413), formato (415), servidor
indisponível (5xx) e falha de comunicação. Nenhum AxiosError/config/corpo original é
preservado no erro público, pois pode conter senha. Retry-After segue o contrato atual
inteiro de segundos, preservado como string sem inventar espera. Não existe retry.

## Limitações e publicação

Os endpoints administrativos ainda NÃO estão registrados em Backend/app/main.py.
Este frontend não habilita a API. Antes de conectar a interface, aprovar publicação,
configurar origem do Admin no CORS/CSRF backend, expor Retry-After e homologar cookies
HTTPS/same-site nos domínios finais. withCredentials não contorna bloqueios de cookies
entre sites. A fronteira de origem de rede no Render permanece pendente.

Nada foi publicado no Netlify/Render ou configurado em DNS. Os testes usam somente
credenciais sintéticas e adapters em memória; não usam Firebase ou API publicada.

## Login visual (PASSO 47)

src/pages/Login separa componente, CSS e controlador local de envio. O formulário
é controlado, não usa validação complexa de e-mail (noValidate), possui labels,
autocomplete, mostrar/ocultar senha, foco visível e mensagens acessíveis. A senha
é limpa do estado ao enviar. Um bloqueio síncrono no controlador impede submissões
concorrentes, além do botão desabilitado. Não existe persistência de senha/token.

LoginAdmin é chamado somente por ação do usuário. Um admin_id não confirma acesso:
o sucesso visual exige getAdminSession. Falha dessa consulta produz estado de
incerteza e um botão para consultar novamente, sem reenviar credenciais nem afirmar
revogação. No PASSO 49 foi acrescentada a navegação real e o logout confirmado descritos abaixo;
não há dashboard completo nem navegação fictícia.

Mensagens reutilizam AdminApiError sanitizado. Configuração ausente informa que o
acesso ainda não está disponível; 429 exibe os segundos recebidos em Retry-After
quando presentes, sem inventar prazo ou efetuar retry. Erros desconhecidos não
são exibidos em formato bruto.

O CSS usa tons escuros/ciano e composição tipográfica inspirados no portal, sem
copiar componentes nem inventar logo oficial. Layout possui breakpoints para
celular e respeita prefers-reduced-motion. A homologação visual desktop/mobile e
interações por teclado permanece pendente: o navegador integrado estava indisponível
e o acesso Computer Use ao Chrome não tinha permissão nesta execução. A marcação
React foi validada por renderização no servidor com Vite e ReactDOMServer, sem
abrir servidor HTTP/WebSocket. Isso não equivale a teste visual ou de DOM interativo.
Testes do controlador cobrem fluxo/erros/concorrência; mostrar/ocultar e interação
real dos campos devem ser conferidos no navegador na homologação.

## Ajuste visual (PASSO 48)

O login utiliza cartão único centralizado, largura máxima 428px, largura fluida,
min-width:0 e padding responsivo. O contêiner tem min-height:100dvh, sem height fixa
ou bloqueio de overflow. Em altura pequena/zoom, o conteúdo pode aumentar a página
e a rolagem vertical permanece disponível; não há overflow-x:hidden mascarando
problemas. Nenhuma medição de viewport foi realizada nesta execução.

Paleta base copiada como valores independentes de Frontend/src/styles/global.css:
fundo #050913, cartão #141b2d, destaque #00e0ff, hover #33e8ff, texto #ffffff e
secundário #a0b3d0, input rgba(13,20,36,.85), danger #ef4444, warning #facc15 e
success #22c55e. Não há import de estilos/componentes do Frontend.

react-icons/fi fornece FiMail, FiLock, FiEye, FiEyeOff, FiArrowRight e FiCheck.
Botão de olho mantém type=button, aria-label/aria-pressed dinâmicos, foco visível
e área 44x44; o estado visible e o fluxo de autenticação não foram alterados.
O cartão é uma seção da página, não um diálogo: sem aria-modal ou focus trap.

A validação automatizada cobre marcação, acessibilidade semântica e regressão do
fluxo existente. A revisão visual/DOM interativa em 320, 375, 390, 768, 1024 e
1440px, alturas reduzidas, zoom e teclado ainda depende de navegador autorizado.
Não houve revisão visual real nesta etapa; a indisponibilidade de Computer Use
registrada anteriormente permanece. Não foram feitas chamadas reais à API.

## Sessão e rotas (PASSO 49)

React Router fornece / (login) e /painel (área mínima). A instância de sessionStore
é criada por App e compartilhada por props/useSyncExternalStore, sem Context global,
Provider complexo ou persistência. Os estados são checking, authenticated,
unauthenticated e error. O componente SessionRoutes consulta o GET inicial em
useEffect; chamadas simultâneas compartilham a promessa em andamento, incluindo o
replay de efeitos do StrictMode. Não existe login automático.

Durante checking/error nenhum conteúdo protegido é renderizado. 401 remove a
autorização visual e /painel direciona para /. Falha de rede/503/configuração gera
indisponibilidade com nova consulta explícita; não afirma expiração ou logout.
O loginController existente recebe login e confirmLogin do store. O POST não concede
acesso: somente o GET confirmado publica a sessão e React Router navega para /painel.
Não há GET duplicado por navegação. Ao entrar em / com sessão já confirmada, direciona
para /painel. Navegações automáticas usam replace para evitar loops no histórico.

O painel mostra apenas identificação, e-mail e papel reais retornados pelo backend,
com botão Sair. O logout usa o cliente existente, compartilha a requisição em
andamento e mantém a sessão anterior com aviso em caso de falha de rede/503. Somente
resposta confirmada limpa o estado e direciona para o login. Um 401 autoritativo
invalida acesso sem anunciar logout bem-sucedido. Não manipula cookies.

Um contador de geração invalida respostas antigas de verificações, confirmações,
login e logout. Isso impede que respostas atrasadas restaurem acesso após invalidação.
Não há timers de expiração, refresh, retries automáticos ou interceptors. Ações
protegidas futuras devem repassar AdminApiError 401 a store.handleUnauthorized(error).
O GET inicial/confirmLogin e logout já tratam seus próprios 401. store.verify permite
revalidar quando necessário, removendo acesso durante essa verificação.

O estado em memória não substitui autorização do backend e não comprova que uma
sessão continua válida indefinidamente sem nova consulta. Mudanças de permissões ou
revogação são verificadas pelo backend em cada operação protegida. Não há expiração
inventada: o contrato atual não retorna expires_at. Após refresh, uma nova instância
começa obrigatoriamente em checking. Para acesso direto/refresh em /painel na futura
hospedagem estática, configurar o fallback de SPA no deploy aprovado; Vite já atende
isso localmente. Nenhuma configuração Netlify foi alterada nesta etapa.

Os endpoints continuam fora de app.main. Não apontar VITE_API_URL para produção
esperando que esta etapa os habilite. Testes de store/rotas usam somente serviços
sintéticos. A renderização de rotas foi verificada por SSR com MemoryRouter; navegação
interativa real, histórico e comportamento em navegadores ainda exigem homologação
manual com infraestrutura autorizada. Nenhuma credencial/token é armazenado.

## Consulta de clientes (PASSO 51)

/clientes usa o mesmo SessionRoutes: somente sessão confirmada com read_customers
renderiza a página. O painel oferece link Clientes apenas com essa permissão.
Ausência de permissão mostra aviso sem montar o componente ou consultar a API.
CORS/autorização definitiva continuam no Backend. A tela inclui volta ao painel e
logout confirmado pelo mesmo SessionStore; não cria outro controle de autenticação.

getAdminCustomers usa a mesma instância Axios, GET /admin/customers e params limit
(padrão 20, máximo 50) e cursor opcional. Tipos AdminCustomer/Page reproduzem somente
customer_id, email, account_status, activation_status, created_at, items e next_cursor.
Não há totais. Dados são projetados em campos aprovados e nunca registrados em logs.
Enums atuais: enabled/blocked e pending/active/suspended; status desconhecidos recebem
rótulo neutro, sem inferir acesso. created_at exige fuso explícito para formatação;
é convertido para UTC, identificado na tela, em pt-BR. Data ausente/inválida mostra
Data indisponível. A consulta não calcula acesso comercial, plano ou assinatura.

customersStore mantém somente a página atual e histórico dos cursores em memória.
Próxima usa next_cursor; Anterior refaz a consulta com cursor anterior, sem guardar
listas antigas. Não há offset, preload de toda coleção, cache persistente ou retries
automáticos. Botões são desabilitados durante consultas e no fim da paginação.
Lista vazia mostra Nenhum cliente encontrado. Falhas limpam dados e permitem retry
manual, exceto 403, que mostra falta de permissão. 400/422, 503 e rede usam mensagens
seguras de AdminApiError. 401 é encaminhado a SessionStore.handleUnauthorized.

Um contador de geração descarta respostas antigas. A assinatura do estado de sessão
limpa dados/histórico quando há logout em andamento, mudança de sessão ou perda de
autenticação. O StrictMode reutiliza a consulta em andamento, sem limpar no cleanup
simulado do efeito. Ao desmontar, a instância é descartada; não é compartilhada entre
administradores. Resultados de uma instância anterior não reaparecem em outra.

A apresentação usa cartões responsivos com labels semânticos, quebra de e-mail/IDs,
grid fluido e botões acessíveis, sem biblioteca de tabelas ou alteração da paleta.
Testes cobrem adapter HTTP, estados/paginação/races, erros e renderização SSR das
rotas/campos; não equivalem a revisão visual/interativa em navegador. Essa revisão
continua pendente por indisponibilidade do acesso Computer Use, já registrada.
Nenhuma chamada real à API foi feita. O endpoint continua fora de app.main; a
publicação/homologação ainda é necessária antes de usar dados reais no Admin.

### Ficha individual de clientes (passo 53)

A rota `/clientes/:customerId` reutiliza a sessão central e exige
`read_customers`, recebido na consulta da sessão. A listagem oferece um Link
semântico para a ficha; ela consulta novamente o endpoint individual, sem usar a
listagem como resposta substituta. Há retorno à listagem, ao painel e saída.

`getAdminCustomer` utiliza a mesma instância Axios com credenciais, valida o ID
como identificador de documento e o codifica como um segmento de URL. A resposta
é projetada nos cinco campos existentes e deve corresponder ao ID solicitado.
A ficha reutiliza os formatadores de status/data (UTC) e mantém somente estado
em memória. Não existe edição, consulta comercial ou persistência no navegador.

O store individual deduplica carregamentos, descarta respostas antigas e limpa
dados na mudança de cliente/sessão. Erros 400, 401, 403, 404, 503 e de rede têm
mensagens seguras; somente 401 invalida a sessão central. Falhas transitórias
permitem uma nova tentativa manual, sem retries automáticos.

Os testes usam adaptadores Axios sintéticos, stores isolados e renderização SSR
da árvore real de rotas. A checagem de CSS não substitui homologação visual e
interativa em navegador. Os routers administrativos continuam sem publicação no
backend; a tela depende da disponibilização futura autorizada desses endpoints
e das configurações operacionais de cookies, CORS e fronteira de confiança.

### Pesquisa exata de clientes por e-mail (passo 56)

A página protegida `/clientes` oferece um formulário acima da listagem. A pesquisa
é explícita (clique ou Enter), usando `lookupAdminCustomer` na mesma instância
Axios configurada por `VITE_API_URL`, com credenciais, JSON e X-Admin-Request: 1.
O e-mail é enviado exclusivamente no corpo de POST /admin/customers/lookup. Não
há pesquisa por tecla, filtro dos 20 resultados locais ou normalização de aliases
no navegador; apenas o envio vazio é impedido. O backend mantém a validação final.

Owner/operator usam a mesma permissão read_customers da sessão já confirmada.
Sem sessão/permissão a página não monta o formulário. HTTP 401 invalida a sessão
central; 403 não é logout. 404 informa somente que nenhum cadastro foi encontrado;
409 exige verificação administrativa dos cadastros e nunca escolhe um deles.
A revisão/correção dessa ambiguidade é uma pendência operacional separada.
503/rede/validação têm mensagens seguras, sem respostas brutas. Pesquisar permite
nova tentativa manual; não existe retry automático.

O store da pesquisa é independente da paginação. Editar/limpar apaga resultados e
invalida respostas anteriores; envios repetidos em andamento são deduplicados.
Troca/perda da sessão e início do logout limpam e-mail e resultado, impedindo que
respostas antigas restaurem informações. Tudo permanece em memória; não há logs
de e-mail, armazenamento persistente, leitura de cookies ou envio manual de tokens.

O resultado reutiliza o componente CustomersList extraído da listagem e seus
formatadores de status/data UTC. O Link "Ver cliente" usa somente customer_id;
a ficha individual segue fazendo sua própria consulta. A paginação existente,
cursores reais e histórico em memória permanecem independentes da busca.

Validação: 135 testes aprovados (27 novos), TypeScript, build e lint aprovados.
Testes utilizam adaptadores Axios sintéticos, stores e renderização SSR das rotas
reais. Validam contrato HTTP, resultados/erros, deduplicação, descarte de respostas,
limpeza e permissão. Não substituem interação visual real em navegador: homologação
visual, teclado/Enter e comportamento em dispositivos reais permanecem pendentes.
CSS usa flex-wrap/min-width e quebra de e-mails conforme os cartões existentes.

Backend e portal dos alunos não foram modificados; nenhuma chamada à API publicada
foi realizada. Os endpoints continuam não publicados. Não há confirmação visual de
compra, ativação, ajustes comerciais ou publicação neste passo.

### Confirmação registrada na ficha (passo 57)

Somente após carregar o cadastro individual, a ficha consulta
GET /admin/customers/{customer_id}/purchase-confirmation pela mesma instância
Axios. O identificador é validado e codificado como segmento único; credenciais
permanecem automáticas, sem acesso a cookies HttpOnly. A resposta é validada em
runtime e projetada nos quatro campos reais; identidade incompatível, booleano
inválido ou contrato inesperado são erros, nunca confirmação negativa.

Apresentação: "Compra aprovada registrada: Sim" ou "Não encontrada", seguida de
"Em caso de dúvida, confira a compra diretamente na Kirvano." Não encontrada
não significa que o cliente nunca pagou. Os campos de validade financeira são
validados no contrato, mas não apresentados como indicadores na interface.
Isso não representa pagamento válido hoje nem autorização para ativação.

O status cadastral continua vindo da consulta individual, com "Status de ativação"
e "Situação da conta" e os tradutores existentes (Pendente/Ativa/Suspensa e
Habilitada/Bloqueada). Identificador e data são preservados. A seção separada de
confirmação organiza a ficha para uma futura ação de acesso, sem botão fictício,
API de escrita, nova permissão, ativação automática ou mudança de status.

A confirmação tem estado próprio: loading, resposta válida ou erro. 401 utiliza
a invalidação central; 403 é acesso negado; 404 é cliente não encontrado; falhas
503/rede/outros mostram "Não foi possível consultar a confirmação da compra."
com tentativa manual apenas dessa consulta. Erro nunca se converte em false.
O store deduplica chamadas de efeitos repetidos e descarta respostas antigas;
troca de cliente recria a ficha, e a assinatura do estado central limpa dados ao
perder/trocar sessão ou iniciar logout. Somente a ficha consulta confirmação;
nenhuma consulta por linha foi adicionada à listagem ou à pesquisa.

Validação: 160 testes aprovados (25 novos), TypeScript, build e lint aprovados.
Os novos testes usam adaptadores sintéticos, stores e SSR para contrato, estados,
normalização de caminho, falhas, descarte de respostas, apresentação e status.
Os testes anteriores de sessão/permissões, listagem, pesquisa, navegação, login e
logout continuam passando. Não houve revisão visual real no navegador; layout e
interação em dispositivos reais ainda precisam de homologação. Nenhuma chamada
à API publicada, alteração de Backend/Frontend ou publicação foi realizada.

### Ativação manual na ficha (passo 59)

A ficha oferece "Ativar acesso" somente com sessão confirmada, read_customers e
activate_customer, cadastro carregado enabled/pending e confirmação de compra
carregada/positiva para o mesmo ID. Owner e operator seguem as permissões da
sessão; nenhuma distinção por papel foi introduzida. Essas condições são apenas
visuais; o servidor continua validando compra, direito, estados e autorização.

A confirmação é um formulário inline com e-mail do cliente, aviso de acesso
condicional, checkbox inicialmente desmarcado e botões Cancelar/Confirmar ativação.
Cancelar não envia requisição. O foco vai ao checkbox ao abrir e retorna ao botão
ao cancelar; feedback após a operação recebe foco. Não há modal nem focus trap.

activateAdminCustomer reutiliza o Axios configurado por VITE_API_URL, valida o
ID como segmento único, envia POST /admin/customers/{id}/activate com somente
{"confirm_activation":true}, application/json, X-Admin-Request: 1 e credenciais.
Não envia admin_id, estado, papéis ou prova de compra. A resposta é validada e
projetada no contrato real; resposta inválida nunca é interpretada como sucesso.

activated mostra "Acesso ativado com sucesso."; already_active mostra "Este cliente
já está ativo.", sem alegar nova operação. Em ambos, a ficha refaz GET do cliente;
nenhum activation_status é modificado localmente como substituto dessa leitura.
A confirmação da compra é reconsultada após o cadastro carregar, reutilizando seu
store/View existentes, agora coordenados na ficha. Falha na atualização preserva
somente o resultado confirmado do POST, sem inventar o estado atual do cadastro.

503, timeout/rede, erro inesperado ou resposta incompatível após POST são tratados
conservadoramente como resultado incerto. A interface não afirma falha pré-commit,
sucesso ou autoria de uma eventual alteração. Ela bloqueia novo POST até uma
reconsulta explícita por "Atualizar situação", que faz somente GET. Se a leitura
mostrar active, o status é exibido e não há ação de ativação. Se mostrar pending,
a nova tentativa exige novamente verificação das condições e confirmação humana.
Isso não torna o resultado do POST anterior conhecido nem prova sua autoria.

401 utiliza a invalidação central; 403 não faz logout; 404 informa cliente
inexistente; 409 informa que as condições atuais não permitem ativação; demais
rejeições conhecidas usam mensagens sanitizadas. Todas oferecem atualização de
situação apropriada, sem retry automático de escrita. Erro de atualização não
converte resultado incerto em sucesso nem desbloqueia tentativa silenciosa.

O store de ativação vive somente na ficha e em memória. Evita submissões
simultâneas, revalida a disponibilidade antes de despachar e nunca envia POST em
efeito React. Mudança de cliente desmonta/limpa a operação; perda/troca de sessão
ou início do logout limpa ficha, confirmação de compra, consentimento e resultado.
Gerações descartam respostas antigas, inclusive durante reconsulta. Uma escrita
já enviada pode terminar no servidor após navegação/logout; a UI não a considera
cancelada nem restaura informações privadas quando ela termina.

A auditoria continua exclusivamente transacional no Backend. Não há auditoria de
navegador, nova autenticação, persistência de tokens, logs de dados pessoais,
integração externa Kirvano, painel financeiro ou mudança comercial. Os endpoints
continuam não publicados, dependendo de publicação operacional autorizada futura.

Validação: 205 testes aprovados (45 novos), TypeScript, build e lint aprovados.
Testes usam adaptadores Axios sintéticos, métodos dos stores e renderização SSR:
contrato HTTP, critérios visuais, consentimento, cancelamento, deduplicação,
resultados, incerteza, GET de reconsulta e descarte de respostas. Testes existentes
de sessão, login/logout, listagem, pesquisa, ficha e confirmação seguem passando.
Não houve navegador real: cliques/Enter sobre DOM, movimentação efetiva de foco,
leitores de tela e layout/interação mobile ainda exigem homologação. Os testes de
store/SSR não devem ser apresentados como testes dessas interações reais.
