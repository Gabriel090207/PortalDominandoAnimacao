# PASSO 78 — proposta única de publicação futura do Admin

Planejamento de 22/10/2026. **Não implementado e não autorizado para publicação.**
Somente este documento foi criado. Nenhum código, dependência, serviço, DNS,
credencial, certificado ou banco foi alterado. Não iniciar PASSO 79.

## Decisão recomendada

**Admin estático no Netlify + Cloudflare Worker exclusivamente no ingresso
`/admin` da API + assinatura por requisição validada no Render.** Reutilizar o
serviço Render e Firestore existentes. Não adicionar Access, segundo login,
Redis, Tunnel, outra API hospedada ou serviço pago sem necessidade medida.

Esta é uma recomendação técnica sujeita à aprovação, não uma configuração já
existente. Exige controle de uma zona ativa Cloudflare, configuração autorizada
do hostname da API e os testes abaixo. Se esse pré-requisito não estiver
disponível, a implantação desta proposta fica bloqueada; não presumir uma
migração gratuita/automática de DNS ou autorizar troca de nameservers.

## Alternativas comparadas

| Alternativa | Viabilidade / bypass | Compatibilidade / custo / manutenção | Escolha |
|---|---|---|---|
| A. Cloudflare Access + JWT validado na origem | JWT assinado com issuer/audience/exp válidos bloqueia chamadas diretas sem prova. Presença do header não basta. Token é bearer, reutilizável até expirar; não vincula automaticamente IP/método/corpo. | Compatível com aplicação HTTP Render e frontend Netlify, mas adiciona identidade/autorização externa, JWKS e fluxo de login. CORS/OPTIONS e cookies Access precisam de configuração própria. Plano/assentos atuais precisam ser confirmados. Não resolve sozinho a origem de IP dos buckets existentes. | Não adotar inicialmente |
| B. Worker assinando requisições | Backend verifica prova que vincula o pedido e o IP atestado pelo gateway; rejeita acesso direto, alteração e replay. | Reutiliza login/cookies existentes. Precisa de pequeno Worker, verificador Python, segredo próprio e armazenamento de nonces. CORS explícito. Pode caber no Workers Free, condicionado a CPU/cota medidas. Não interfere no webhook quando restrito ao namespace Admin. | **Recomendação principal** |
| C. Serviço Render separado para Admin | Separação reduz acoplamento, mas uma segunda URL pública continua permitindo bypass sem ingresso autenticado. | Compatível com Netlify e cookie host-only, exigindo hostname/CORS. Acrescenta deploy, operação, disponibilidade e possível custo de outra instância. Ainda precisaria de A ou B. | Adiar até haver motivo de isolamento/capacidade |
| D. Proxy com header secreto estático | Pode autenticar um hop TLS se segredo só existir no gateway/backend; segredo/header capturado é reutilizável e não vincula o pedido. Host/Origin/IP allowlist sozinhos não autenticam a borda. | Menor código, mas garantias inferiores para os requisitos de replay e atestação do IP. Restrição de IP nativa do Render não pode ser presumida no plano atual. | Não escolher |

Cloudflare documenta validação JWT na origem e a necessidade de configurar CORS
do Access. Worker pode usar Web Crypto/HMAC sem instalar biblioteca criptográfica
no navegador; Python já possui HMAC/SHA-256. O protocolo entre ambos será novo e
precisará de vetores de interoperabilidade e revisão; não é segurança pronta só
por usar HMAC.

## Fluxo e separação de aplicações

Nomes abaixo são exemplos **provisórios**, configuráveis:

```text
Chrome
  ├─ HTTPS admin.<domínio> → Netlify → build estático de Admin/
  └─ HTTPS api-membros.<domínio>/admin/...
          → Worker da própria zona, limitado ao namespace Admin
          → HTTPS serviço.onrender.com/admin/...
          → guard criptográfico obrigatório do aplicativo Admin
          → sessão / Origin / CSRF / permissão / rate limiting existentes
          → Firestore

POST serviço.onrender.com/webhooks/kirvano
          → app.main existente → security-token e processamento existentes

API pública / futuras rotas do portal
          → app.main existente, sem autenticação administrativa imposta
```

- Admin: projeto Netlify próprio, raiz Admin/, build `npm run build`, publish dist,
  rewrite SPA para `/clientes` e fichas, HTTPS e headers de segurança.
- `VITE_API_URL`: origem HTTPS da API, sem segredo. Axios permanece credentialed.
- API: hostname próprio com DNS proxied Cloudflare; Worker Routes para `/admin`
  e `/admin/*`, sem wildcard que capture webhook ou restante da API. Desativar
  endpoints de preview/workers.dev do gateway de produção.
- Render: futura factory de produção explicitamente habilitada delega o
  namespace Admin à aplicação administrativa protegida e os demais caminhos ao
  `app.main` existente. **app.main continua sem registrar routers Admin.**
  A camada guard pertence a toda a aplicação Admin, não somente ao POST login.
- A futura troca do entry point Render só ocorrerá após testes e autorização.
  Configuração Admin ausente/inválida deve fechar somente o ramo Admin
  (404 desabilitado / 503 indisponível), mantendo o ramo público operacional.
- Nenhuma alteração global de proxy, CORS ou segurança deve atingir Kirvano.
  Não desativar onrender.com: ele pode continuar sendo o ingresso do webhook.
- A API dos membros permanece com seus próprios contratos; esta proposta não
  implementa login ou novas funcionalidades do portal.

## Ameaça concreta e verificação na origem

Um atacante conhece o hostname Render e chama diretamente `/admin/auth/login`,
`/admin/customers` ou qualquer outra rota Admin, enviando Origin e IP falsos.

**Resultado proposto:** ausência de prova criptográfica válida gera rejeição
antes de executar handlers administrativos. Forjar CF-Connecting-IP,
X-Forwarded-For, Host, Origin ou o nome do gateway não gera uma assinatura válida.
Mesmo uma sessão Admin válida não permite contornar a exigência de gateway.
Requisições públicas ao webhook continuam fora deste guard.

### Envelope proposto, versão 1

Worker e Render usarão uma chave nova e exclusiva de autenticação do gateway.
Não reutilizar ADMIN_ADMISSION_HMAC_SECRET, segredo comercial, security-token,
senha ou token de sessão. Chave somente como Worker Secret e segredo de runtime
Render; nunca VITE_*, Git, URL, cookie ou código entregue ao navegador.

A assinatura HMAC-SHA-256 cobrirá uma serialização determinística de:

- versão e propósito do protocolo, key_id e audiência lógica da aplicação Admin;
- timestamp e nonce aleatório de pelo menos 128 bits;
- método, caminho e query exatos encaminhados ao Render;
- SHA-256 dos bytes do corpo, sem parse/reformatação JSON;
- Origin, Content-Type e X-Admin-Request efetivamente encaminhados;
- digest do header Cookie efetivamente encaminhado, sem logar seu valor;
- IP canônico atestado pelo Worker da própria zona.

O formato de serialização/codificação será fechado antes da implementação, com
vetores iguais em JavaScript/Python. Não ordenar/reinterpretar parâmetros nem
descartar duplicatas para “corrigir” pedidos: a prova deve vincular os bytes e
headers realmente entregues. Não seguir redirects do upstream automaticamente.
URL upstream fixa por configuração; o navegador nunca fornece destino de fetch.

Worker removerá quaisquer headers de envelope fornecidos pelo cliente e criará
um envelope novo. Backend exigirá valores únicos/limitados, key_id reconhecido,
audiência esperada, timestamp aceitável e comparação segura da assinatura. Não
consultar Firestore por nonce antes de autenticar a assinatura.

O roteamento/guard deve ser testado contra caminhos codificados, barras,
normalização de URL, query duplicada e aliases. Toda rota que resolva para o
aplicativo Admin deve passar pelo guard; a simples correspondência textual de
uma route no Cloudflare não é a barreira de segurança do backend.

### Replay, relógio e falhas

- Proposta inicial: envelope de curta duração, por exemplo até 120 s de idade e
  30 s de tolerância futura, ajustado após medir fila/cold-start. Não é política
  já aprovada nem configuração existente.
- Após verificar assinatura/tempo, reservar nonce por create-only em coleção
  técnica separada no Firestore, com ID derivado do propósito/audiência/chave/nonce.
  Duas instâncias não conseguem consumir a mesma prova duas vezes. Não usar cache
  de processo ou KV eventualmente consistente para esta garantia.
- Documento guarda apenas metadados mínimos/expiração, sem IP, cookie ou senha.
  TTL físico pode remover documentos depois do período máximo de aceitação;
  expiração da prova é validada logicamente, independente do prazo do TTL.
- Nonce repetido/prova inválida: rejeitar com erro sanitizado, sem limpar sessão.
  Firestore indisponível ou reserva de resultado incerto: 503, sem executar ação.
- Reserva não é confirmação da operação: a transação de cliente/auditoria
  continua sendo a existente. Se uma resposta se perder depois da ação, a UI
  mantém sua estratégia de resultado incerto e releitura com novo pedido.
- Worker não fará retry automático de login ou ações mutáveis. Não gerar uma
  assinatura nova para repetir uma operação cujo resultado ficou desconhecido.
- Configurar Workers em fail closed. Mesmo um bypass por falha da route não deve
  abrir a API: o Render continuará exigindo a prova. Exceções/limites/segredo
  ausente não terão fallback direto do Axios para o hostname Render.

Essa prova autentica **o gateway**, não o administrador. Qualquer cliente pode
alcançar o gateway; ainda precisa vencer login, rate limiting, sessão, Origin,
CSRF e permissões. Não é garantia de que o pedido veio de um navegador humano.

## IP: como a confiança é estabelecida

Não confiar no header recebido isoladamente pelo Render. O backend só entrega
ao AdminAdmissionService o IP que faz parte do envelope autenticado do Worker.
O resolvedor/canonicalizador existente pode ser reutilizado na fronteira aprovada,
sem usá-lo como atestação de procedência.

Na entrada Worker, o IP depende das garantias de Cloudflare para aquele fluxo.
Condições operacionais: conhecer a cadeia da própria zona, não permitir outro
Worker anterior que reescreva x-real-ip, desabilitar Pseudo IPv4 que sobrescreva
o IP real e testar headers falsificados/subrequests de Workers. Subrequests de
outras zonas podem representar um Worker, não um usuário final; não apresentá-los
como identidade humana. Rejeitar ingressos cuja procedência de IP não puder ser
validada. Não aceitar um valor arbitrário do cliente para assinar.

IPs IPv4/IPv6, NAT, VPN e ataques distribuídos continuam tendo limitações próprias.
Não adicionar allowlist de operadores sem seus endereços e política de manutenção
aprovados. Não contar com request.client.host reescrito pelo Uvicorn para atestar
o peer original Render/Cloudflare.

## Cookies, CORS e preflight

- Admin/API HTTPS sob o mesmo domínio registrável, em hosts distintos: cross-origin,
  porém same-site. Não usar domínios padrão Netlify/Render como substituto sem testes.
- Cookie emitido pelo backend e retransmitido sem reescrita de atributos pelo
  Worker: __Host-admin_session, HttpOnly, Secure, SameSite=Lax, Path=/, sem Domain.
  O navegador o associa ao hostname visível da API, não ao hostname upstream Render.
- Não armazenar token no React/localStorage, não compartilhar cookie por Domain.
  Preservar múltiplos Set-Cookie e Cache-Control: no-store; não fazer cache de
  nenhuma resposta Admin, incluindo GET, redirects e erros.
- Permitir somente a origem exata aprovada do Admin; nunca '*'. Backend mantém
  a factory CORS administrativa e valida Origin também nos handlers.
- Worker atende OPTIONS de preflight no edge, sem exigir cookie nem consumir
  nonce. Só responde à origem/método/headers permitidos, credenciais habilitadas,
  Vary apropriado e sem dados de negócio. Não encaminha preflight anônimo ao ramo
  protegido Render. OPTIONS direto ao Render não dá acesso ao aplicativo Admin.
- GET/POST reais seguem assinados; backend continua exigindo Origin nas leituras
  e Origin + X-Admin-Request + JSON/confirmacao nas mutações. A assinatura vincula
  esses headers e não autoriza relaxar validações.
- Gateway devolve CORS restrito também nos seus erros para a origem autorizada,
  de modo que a UI possa distinguir indisponibilidade de sessão inválida.

Os três hosts planejados ainda dependem de confirmação. Não usar wildcard,
alterar portal.dominandoanimacao.com ou mudar nameservers por inferência.

## Custos e limitações verificadas

- Workers Free documenta 100.000 requests/dia e 10 ms de CPU por invocação.
  Espera por fetch não é CPU; HMAC/hash/validações precisam caber no limite e ser
  medidos. Configurar fail closed ao exceder cota. Não prometer disponibilidade
  ilimitada ou proteção gratuita contra qualquer volume de ataque.
- Workers Paid tem mínimo documentado de US$5/mês, com consumo adicional conforme
  tabela. Não é necessário contratá-lo antes de medir. Plano Workers é separado
  do plano geral da zona Cloudflare.
- Reutilizar serviço Render evita uma segunda instância. Free pode dormir após
  15 minutos sem tráfego e levar aproximadamente um minuto para acordar: pode
  prejudicar login/timeout/envelope. Definir disponibilidade desejada e testar;
  um plano pago só deve ser escolhido por esse requisito ou capacidade medida.
- Netlify: reutilizar hospedagem estática, build e domínio próprio conforme plano
  efetivo. Limites/créditos da conta não foram consultados; não prometer custo zero.
- Firestore: nonce acrescenta uma gravação por pedido encaminhado, mesmo que
  depois a autenticação seja rejeitada, além das leituras/escritas já existentes.
  Há armazenamento/limpeza e custos de ataques ao gateway; orçar e monitorar.
  A proposta não depende de regras de IP pagas no Render, Redis, KV ou Durable Objects.

## Riscos residuais e condições de aprovação

1. Comprometimento do Worker, da chave ou do deploy do backend rompe a atestação;
   proteger acessos às contas e definir rotação/revogação coordenada por key_id.
2. Nonces impedem replay de envelope, não roubo e reuso de cookie para obter novas
   provas no gateway. HttpOnly não elimina XSS; manter headers/hosting seguros,
   CSRF e revogação de sessão existentes.
3. CDN/proxy não substitui mitigação de DDoS/custo. O hostname Render permanece
   alcançável por causa dos serviços públicos; ele rejeita operações Admin sem
   prova, mas pode receber tráfego e sofrer indisponibilidade.
4. Rate limiting por origem não impede todos os ataques distribuídos. Gateway
   signing também não elimina força bruta vinda por pedidos novos legítimos ao edge.
5. Protocolo próprio exige teste contra confusão de URL/headers e revisão. Não
   declarar pronto antes de interoperabilidade, nonce concorrente e falhas reais.
6. Zona/DNS, plano/quotas, disponibilidade Render, domínios e retenção/TTL ainda
   precisam de decisão. Esses são bloqueios operacionais, não detalhes presumidos.
7. Reembolso/chargeback e demais pendências do PASSO 77 continuam separados; esta
   arquitetura não torna o sistema comercial inteiro pronto para clientes reais.

## Plano mínimo futuro e rollback

1. Aprovar esta arquitetura, confirmar controle da zona e hosts exatos, orçamento,
   disponibilidade e política de IP; manter a estrutura portal existente intacta.
2. Fechar especificação v1 do envelope, nomes de configuração, canonicalização,
   janela de validade, coleção/TTL de nonces e vetores comuns JS/Python.
3. Implementar/testar localmente verificador + nonces com emulator e Worker com
   runtime de teste apropriado, sem publicar, sem segredos reais e sem expor rotas.
4. Preparar factory de produção, isolamento do ramo Admin, CORS/preflight, Netlify
   SPA/headers e infraestrutura como configuração revisável. Reutilizar serviços
   e contratos de autenticação/auditoria existentes.
5. Em homologação autorizada: testar acesso direto Render com headers falsos e
   sessão válida, replay simultâneo em instâncias, alteração de cada campo
   assinado, caminhos codificados, cookies, Origin, CSRF, logout, quotas,
   Firestore indisponível, cold-start e regressão do webhook/ramo público.
6. Publicação somente depois de aprovação explícita e evidência de validação.

Rollback: desabilitar primeiro o ramo Admin ou voltar ao entry point público
anterior. Preservar rejeição sem assinatura — nunca retirar o guard deixando
routers Admin expostos. Worker indisponível deve deixar Admin indisponível, não
liberar caminho direto. Manter versão compatível de chave/política durante
rollback; revogar chave se comprometida. Não apagar usuários/auditoria/buckets
ou resetar sessões/bootstrap para reverter deploy. Kirvano permanece público.

**Próximo passo concreto sugerido, sujeito à autorização:** especificar e testar
o protocolo de prova de gateway e o consumo atômico de nonce, ainda isolados e
sem registrar routers de produção. Não implementar Resend ou outros módulos.

## Fontes oficiais consultadas em 22/10/2026

- [Worker Routes e pré-requisitos DNS](https://developers.cloudflare.com/workers/configuration/routing/routes/)
- [Web Crypto, HMAC e SHA-256](https://developers.cloudflare.com/workers/runtime-apis/web-crypto/)
- [Worker Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)
- [Limites e fail closed](https://developers.cloudflare.com/workers/platform/limits/)
- [Preços Workers](https://developers.cloudflare.com/workers/platform/pricing/)
- [Cloudflare Access: validação de JWT](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [Cloudflare Access: CORS](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/cors/)
- [Cloudflare: headers e subrequests de Workers](https://developers.cloudflare.com/fundamentals/reference/http-headers/)
- [Render Free e cold-start](https://render.com/docs/free)
- [Netlify: planos](https://www.netlify.com/pricing/)

Proposta baseada no código/relatório PASSO 77 e documentação pública. Não foram
acessados painéis ou credenciais; plano e DNS efetivos não foram verificados.
