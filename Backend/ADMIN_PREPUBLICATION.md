# PASSO 89 — homologação local pré-publicação

Status: validação automatizada local por camadas executada, COM pendência de
regressão concorrente no Emulator. NÃO é homologação
em navegador nos domínios reais nem aprovação de publicação/comercialização.
Nenhuma funcionalidade ou código de produção foi alterado nesta etapa.

## Inspeção e método

Revisados Admin/HOSTGATOR_DEPLOYMENT.md, ADMIN_PUBLIC_API.md, ADMIN_ENTRYPOINT.md,
ADMIN_ADMISSION_CONFIGURATION.md; entrada/factory pública, composição, parser,
CORS, clientes Axios/session store, rotas React e fixtures não destrutivas.
Reutilizadas a política explícita 10/5/5/20 e as implementações existentes.

Três camadas distintas, sem alegar equivalência com navegador real:

1. TestClient ASGI + Firestore Emulator real para PublicAdminEntryConfiguration,
   autenticação, dados de clientes, sessões e auditoria. Repositórios SEM mocks.
2. Testes Admin/React/Axios para gates de sessão, navegação, withCredentials,
   X-Admin-Request, erros de rede/503 e ausência de acesso visual antecipado.
3. Build estático + Apache local em porta aleatória de loopback para HTML,
   fallback SPA, assets, headers e cache. Sem conectar o pacote à API real.

Somente hosts fictícios: https://admin.example.test e https://api.example.test
no cliente ASGI, sem DNS ou /etc/hosts. Build com https://api.example.invalid,
não funcional. Nenhum browser foi iniciado/controlado. Não foi executado um
fluxo JavaScript do bundle em navegador; HTTPS é simulado no scope ASGI e o
Apache local valida entrega HTTP, não TLS real.

## Fluxo real no Emulator

Novo test_admin_prepublication_integration.py reutiliza a fixture UUID do PASSO 74,
que sobrescreve a limpeza global histórica. Cliente, compra/subscription/right,
admin, sessões, auditoria e IDs HMAC são exclusivos por teste. Credenciais
anônimas, projeto demo fixo, endpoint 127.0.0.1:8080. Limpeza apenas dos IDs
calculados ou consultas filtradas por admin/customer UUID deste teste. Não foi
apagado/redefinido o cliente usado no Chrome ou qualquer owner já existente.

Os seis cenários novos cobrem:

- Ciclo completo repetido para owner e operator: sessão inicialmente 401, operação
  sem sessão 401, senha incorreta 401 sem sessão criada, senha correta 200,
  consulta de sessão, logout revogado e reutilização do token revogado 401.
- Cookie real emitido com __Host-admin_session, Secure, HttpOnly, SameSite=Lax,
  Path=/ e sem Domain. Jar HTTP identifica api.example.test como host-only e
  não envia cookie numa chamada ao host admin.example.test (401). Isso NÃO
  reproduz as políticas SameSite/terceiros/CSRF de Chrome/Safari/Firefox.
- CORS com credenciais e preflight na origem Admin distinta da API; mutação
  sem X-Admin-Request recusada antes da mudança de estado.
- Pesquisa exata normalizada, ficha e confirmação histórica da compra; a
  confirmação permanece current_payment_validity=not_verified e requer revisão.
- Ativação -> suspensão -> retomada; estado final active. Três auditorias por
  execução, validadas nos contratos, confirmação humana e administrador corretos.
  Documentos de purchase/subscription/entitlement e seus update_time preservados.
- Sessão expirada no registro sintético -> 401; admin sintético desabilitado ->
  sessão 401 e nova senha válida também 401.
- Cinco tentativas para mesma identidade com CF variado -> próxima 429 antes
  de autenticação; vinte e-mails/CF distintos -> próximo login 429. Nenhuma
  sessão criada nesses cenários. Relógio da admissão fixado explicitamente;
  testes não dependem da velocidade da máquina para o Retry-After.

A normalização comercial da fixture usa os mecanismos existentes, mas não é um
pagamento real nem validação do provedor Kirvano. Não altera regras comerciais.

## Regressão de segurança e API pública

Reexecutada a suíte unitária completa, incluindo ausência/configuração inválida
503, política antiga recusada no modo público, CF ausente/malformado/duplicado,
sem fallback, Origin/CSRF inválidos, negação de permissão, Firestore indisponível,
commit incerto, pré-Argon2, falta de sessão e sanitização.

A matriz atual permite aos dois papéis todas as oito operações administrativas
existentes. A negação de permissão na regressão usa decisão sintética negativa,
sem inventar uma restrição nova para operator ou alterar a matriz de produção.

Health/raiz públicos continuam independentes; webhook mantém autenticação
security-token e contratos próprios. O dispatcher delega à mesma aplicação
pública. app.main não ganhou routers administrativos. CORS Admin não envolve
webhook/rotas públicas. Configuração Admin inválida não derruba health/público.
Os testes unitários Kirvano reexecutados não equivalem a entrega real do provedor.

CF permanece dado operacional potencialmente falsificável caso a borda não o
sanitize. Parser não atesta procedência. Identidade e agregado independentes de
IP preservam seus orçamentos mesmo quando o valor do header muda. Isso não cria
ingresso privado nem remove ataques de indisponibilidade direcionada/coletiva.

## Pacote HostGator

TypeScript, lint, testes Admin e npm run build:hosting reexecutados com URL
sintética HTTPS. dist-hosting/ foi regenerado como artefato ignorado, sem alterar
fontes/visual nem o dist/ anterior. Nenhum arquivo foi enviado à hospedagem.

Apache 2.4 disponível no macOS, configuração temporária e cópia em /tmp para
não alterar permissões de Documents. Processo temporário encerrado pelo próprio
teste; nenhum servidor do usuário foi reiniciado/encerrado. Seis verificações:
raiz, /clientes, /clientes/synthetic-customer, JS, CSS e asset inexistente 404.
Confirmados HTML fallback, paths /assets/, MIME, no-store para HTML,
immutable para assets versionados, CSP, X-Frame-Options, nosniff e Referrer-Policy.

O marcador VITE sintético adicional, 127.0.0.1, placeholder de CSP e marcador de
chave privada não apareceram no pacote; sem source maps. Não houve uso/leitura
de segredos reais, e essa verificação não é garantia universal de detecção de
segredos em código. O literal http://localhost interno do React Router continua
no JS; não é API configurada ou chamada de rede local. Build tem apenas URL
fictícia e precisa ser recompilado antes de futura publicação autorizada.

## Checklist pré-publicação

PRONTO significa implementação e evidência LOCAL, sem aprovação operacional.

| Item | Categoria | Evidência / ação necessária |
|---|---|---|
| Login, sessões, permissões, CSRF, auditoria | PRONTO | Testes locais/Emulator; não são homologação real |
| Quatro buckets e política 10/5/5/20 | PRONTO | Seleção explícita/limites validados; intermitência concorrente separada abaixo |
| Build, Axios, rotas e pacote estático | PRONTO | Testes Admin e Apache local; API sintética |
| Isolamento público/Kirvano e rollback de código preparado | PRONTO | main intacto; desabilitar ramo sem apagar dados |
| Subdomínio Admin | PENDENTE DE CONFIGURAÇÃO | Escolher/aprovar nome e diretório exclusivo HostGator |
| Subdomínio API | PENDENTE DE CONFIGURAÇÃO | Aprovar nome e domínio no serviço Render existente |
| HTTPS | PENDENTE DE CONFIGURAÇÃO | Certificados/redirects e cadeia real dos dois hosts |
| VITE_API_URL | PENDENTE DE CONFIGURAÇÃO | URL HTTPS aprovada e recompilação do artefato |
| CORS/Origin | PENDENTE DE CONFIGURAÇÃO | Allowlist final exata, credenciais, preflight/erros reais |
| Cookie | PENDENTE DE CONFIGURAÇÃO | Atributos prontos; confirmar comportamento em navegadores/hosts same-site |
| HostGator .htaccess | PENDENTE DE CONFIGURAÇÃO | Confirmar Apache/LiteSpeed, overrides, módulos e headers sem herança conflitante |
| Índices Firestore | PENDENTE DE CONFIGURAÇÃO | Consultas reais, especialmente múltiplos intervalos de elegibilidade; Emulator não prova índices |
| IAM, projeto e banco corretos | PENDENTE DE CONFIGURAÇÃO | Conferência autorizada da credencial/projeto/(default)/privilégios, sem emulator |
| HMAC | PENDENTE DE CONFIGURAÇÃO | Segredo real backend, mesma chave/versão, sem geração/rotação automática |
| Configuração por instância | PENDENTE DE CONFIGURAÇÃO | Mesma política, versão e chave; rejeitar implantação mista |
| Transição dos buckets | PENDENTE DE CONFIGURAÇÃO | Coordenar pausa/liberação; dados incompatíveis não migram sozinhos |
| Start Command Render | PENDENTE DE CONFIGURAÇÃO | Composição pública autenticada explícita ainda não ativada; manter comando atual até aprovação |
| Rollback operacional | PENDENTE DE CONFIGURAÇÃO | Aprovar e ensaiar versões/pacotes/backups; não resetar buckets/sessões/bootstrap |
| Procedência CF não comprovada | RISCO A SER ACEITO | IP não é autenticação; não declarar sanitização real provada |
| Regressão concorrente intermitente | PENDENTE DE CONFIGURAÇÃO | Pendência técnica: investigar teste/SDK antes de aprovar disponibilidade; não se resolve só com configuração |
| Indisponibilidade direcionada/coletiva | RISCO A SER ACEITO | Atacante pode consumir identidade/agregado, inclusive tokens repostos |
| Leituras/custo/contensão e crescimento | RISCO A SER ACEITO | Quatro leituras por tentativa, quatro escritas admitida, retries e TTL/retencão pendentes |
| Limitações Render Free informado | RISCO A SER ACEITO | Cold start/reinícios/quotas; sem medição real ou garantia de disponibilidade |
| Reembolso/chargeback no lançamento comercial | PENDENTE DE CONFIGURAÇÃO | Categoria operacional: NÃO se resolve por configuração apenas; falta tratamento comercial em etapa própria |

Última linha registra uma pendência de implementação comercial, não uma opção
que possa ser habilitada num painel. Esses eventos constam do inbox, mas seu
tratamento comercial não está concluído; a prontidão técnica do Admin não libera
comercialmente o portal completo. Não implementar essa parte neste passo.

## Decisões e menor próximo passo

Os fluxos funcionais novos passaram nas camadas locais. A regressão concorrente
ainda tem uma falha não encerrada; portanto a homologação integral NÃO está
aprovada. O Admin ainda não foi homologado
como sistema executando no navegador em domínios reais. Nenhum teste autoriza
publicação automática ou garante custos/disponibilidade sob ataque.

Decidir hosts finais, disponibilidade de plano/overrides HostGator e aceitar
explicitamente riscos da API pública/Render Free antes de preparar valores de
produção. Menor próximo passo: investigar e classificar a falha concorrente registrada,
com diagnóstico sanitizado e armazenamento isolado, antes de aprovar o checklist
operacional. Não aumentar retries nem flexibilizar assertions sem comprovar o
contrato que o teste deve verificar. Sem deploy ou mudanças DNS/credenciais. Uma
homologação real posterior exige autorização e testes browser/CORS/cookies/TLS,
projeto/IAM/índices, recursos e rollback. Não iniciar PASSO 90.

## Resultados e falha não encerrada

- Backend completo: 1.384 aprovados + 52 subtestes; 234 integrações desselecionadas.
- Admin: 328 aprovados; TypeScript, lint e build: aprovados.
- Novo arquivo do Emulator: seis aprovados na execução específica.
- Regressão ampliada de quatro arquivos não destrutivos no Emulator: 15 aprovados
  e UMA FALHA em test_admin_admission_sizing_integration.py::
  test_two_administrators_simultaneously_share_aggregate.
- Apache: seis verificações HTTP aprovadas; verificações do artefato aprovadas.
- git diff --check passou. Aviso existente TestClient/httpx, sem dependências novas.
- Contagens se sobrepõem; não somar execuções repetidas como novos testes.

Falha observada: um dos dois callers recebeu AdminAdmissionUnavailable antes de
o teste concluir sua expectativa de ambos retornarem allowed. A mensagem pública
permaneceu sanitizada. A causa interna da falha original não foi capturada; não
atribuir categoricamente a Aborted, timeout ou esgotamento sem diagnóstico.

Três repetições ISOLADAS passaram, cada uma com duas admissões e, respectivamente,
5, 3 e 5 chamadas SDK _begin. Isso demonstra retentativas variáveis nas execuções
bem-sucedidas. Não reproduziu o erro nem comprova que ele foi resolvido. O teste
pressupõe sucesso de ambos sob contenção; o contrato do SDK não promete sucesso
incondicional após suas retentativas. Há hipótese de fragilidade dessa suposição,
mas não há prova da causa da falha específica. Não foi alterado esse teste nem a
lógica de produção para fazer a regressão passar.

Um diagnóstico local temporário estava preparado para emitir somente nomes de
tipos da cadeia de exceções se houvesse nova falha. Nenhuma cadeia foi obtida
porque as três execuções passaram. Não registrar senhas, tokens, corpos ou IPs
reais para investigar. Não há novo defeito de produção comprovado, nem evidência
nova de consumo parcial/reativação de sessão; também não declarar correção.

Menor correção candidata, SOMENTE se diagnosticado conflito SDK permitido pelo
contrato: adaptar o teste para aceitar exclusivamente a falha de contenção
identificada, verificar contabilização/atomicidade e capacidade remanescente,
sem presumir ordem ou sucesso de todos. Não aceitar qualquer exceção genérica.
Se o diagnóstico apontar falha de produção, registrar teste reproduzível e propor
correção mínima separadamente; não mexer em retries aleatoriamente.

Arquivos criados: Backend/tests/emulator/test_admin_prepublication_integration.py
e este relatório. Nenhum arquivo-fonte existente foi alterado. Artefato ignorado
Admin/dist-hosting foi recompilado localmente com URL fictícia. Todo o restante
das alterações locais anteriores foi preservado. /tmp recebeu apenas a cópia e
script de validação descartáveis, sem alterações em /etc/hosts ou confiança TLS.

Nenhum Firebase real/Render/HostGator/DNS foi acessado ou alterado. Nenhum owner
real foi usado, bootstrap executado, servidor do usuário encerrado ou pagamento
modificado. Nada publicado ou contratado; não iniciar PASSO 90.
