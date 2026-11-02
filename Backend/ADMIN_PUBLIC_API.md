# PASSO 88 — modalidade pública autenticada, não publicada

## Decisão e mudança de contrato

A API pode ser alcançável pela internet sem conceder acesso administrativo a
quem conhece sua URL. Autenticação de administrador e autorização no backend
são a fronteira de privilégios. Não exigir passagem pela HostGator é uma decisão
explícita desta modalidade, não uma alegação de ingresso privado autenticado.

create_admin_entrypoint conserva o dispatcher do PASSO 87 e recebe um de três
estados, sem inferência por ambiente:

- Sem configuração/configuração inválida: ramo /admin indisponível (503).
- AdminEntryConfiguration: modalidade anterior, com verificador de ingresso
  explícito aplicado a cada requisição efetiva. Contrato preservado.
- PublicAdminEntryConfiguration: NOVO contrato de API pública autenticada,
  sem ingress_verifier artificial. Exige cliente Firestore, configuração HMAC,
  origens HTTPS exatas e ComplementaryAdminAdmissionPolicy completa.

Usar public_configuration como admin_configuration na mesma factory existente.
Não há app global, startup automático, segundo backend ou leitura automática
que escolha a modalidade. Um dict, booleano ou nome de header não seleciona o
modo público. Código do chamador deve construir o objeto tipado explicitamente.
Selecionar essa classe não autoriza deploy ou aprovação operacional de produção.

Exemplo conceitual para uma composição SINTÉTICA já isolada:

```python
from app.admin_entrypoint import PublicAdminEntryConfiguration, create_admin_entrypoint
from app.config.admin_admission_policy import load_admin_admission_policy

# client, hmac_config e security_config fornecidos pelo teste/ambiente autorizado.
settings = PublicAdminEntryConfiguration(
    firestore_client=client,
    admission_config=hmac_config,
    security_config=security_config,
    policy=load_admin_admission_policy(selection='complementary-local-v1'),
)
application = create_admin_entrypoint(admin_configuration=settings)
```

Não é comando de inicialização de produção. Nenhum cliente real ou segredo é
carregado por esse exemplo/factory. Não modificar o Start Command neste passo.

## Separação entre rede, transporte e privilégios

A modalidade pública usa _PublicHTTPS, que exige scope HTTPS nas requisições
efetivas. Isso é pré-requisito de transporte/cookie, não prova da identidade do
cliente ou do proxy. Uvicorn/terminação TLS ainda precisam de homologação.

No LOGIN, _operational_origin chama o parser existente sobre pares ASGI brutos
para CF-Connecting-IP. Duplicado/ausente/vazio/malformado/lista falha fechado com
503, antes da admissão/senha. IPv4/IPv6/mapeados continuam canonicalizados.
Não há fallback para XFF, X-Real-IP, request.client.host, Host ou Origin.

Esse IP é informação OPERACIONAL, baseada na infraestrutura Render recomendada
pelo suporte informado pelo usuário. Não é autenticado criptograficamente, e a
remoção de valores falsificados ainda não está comprovada. A função não satisfaz
nem é chamada de ingress_verifier. O parâmetro legado trusted_origin_dependency
na composição é reutilizado como ponto de injeção; o nome não transforma o dado
operacional deste modo público em origem atestada.

Em consulta/ações/logout, não exigir CF como prova de ingresso: sessão e
permissões protegem as operações. Fornecer CF/role/permission em headers NÃO
concede autenticação nem autorização. Origin e CORS são proteções de navegador,
não autenticação do chamador. Login e preflight são acessíveis sem sessão por
sua natureza; não dão acesso a dados de clientes ou ações administrativas.

## Política obrigatória e falhas

A modalidade pública rejeita política antiga de dois buckets. A referência
explícita 10/5/5/20 e reposições 1/30s, 1/60s, 1/60s, 1/30s é reutilizada sem mudar
seus defaults ou ativá-la no ambiente real. Instâncias devem compartilhar política,
segredo e versão; transição/rollback continuam coordenados (PASSO 85).

Os quatro orçamentos são consumidos na MESMA transação antes do Argon2:
origem, origem/identidade, identidade normalizada independente de IP e agregado.
Assim, trocar CF pode trocar os dois primeiros orçamentos, mas NÃO o terceiro ou
quarto. HMAC mascara identificadores sem autenticar o IP. Identidades inválidas
continuam usando o contrato limitado compartilhado já existente.

Firestore indisponível, política persistida incompatível e resultado incerto
não liberam senha/sessão. Não há reset por sucesso, fallback em memória ou
retentativa externa nova. Respostas existentes 401/403/429/503 são preservadas,
sem revelar existência de administrador, senha, token ou segredo.

## Sessões, permissões e aplicação pública

Reutilizados sem mudanças: senha Argon2id e semáforo, token opaco/digest, oito
horas absolutas, revogação/status/auth_version/vínculos, cookie __Host-admin_session
HttpOnly/Secure/SameSite=Lax/Path=/ sem Domain, Origin exato, X-Admin-Request,
CSRF, confirmação de ações, matriz owner/operator e auditoria transacional.
Sessões inválidas/expiradas e admin desabilitado continuam negados.

A matriz atual dá aos dois papéis as oito permissões operacionais existentes.
O teste de negação de permissão injeta uma decisão negativa SOMENTE no teste,
para exercitar o 403 sem inventar restrições atuais para operator. Headers do
cliente não sobrescrevem essa decisão. Não houve mudança de papéis/permissões.

Somente /admin e /admin/* vão ao ramo administrativo; CORS específico continua
fora do app público. Raiz/health/webhooks/Kirvano e lifespan são delegados por
referência à aplicação atual. app.main permanece sem routers Admin. Não foram
alterados métodos, headers, payloads, transações, auditoria ou elegibilidade comercial.
O chamador continua responsável pelo ciclo de vida do cliente Firestore compartilhado.

## Riscos residuais e viabilidade inicial

A arquitetura de aplicação é viável para avaliação de uma API pública fortemente
autenticada sem novos serviços, desde que riscos de disponibilidade/custo sejam
aceitos explicitamente. A modalidade não garante proteção absoluta ou ingresso
privado. O requisito de gateway autenticado não é presumido satisfeito: ele é
substituído NESTE CONTRATO por autenticação/autorização da API, de forma explícita.
A modalidade anterior permanece disponível separadamente.

- Atacante distribuído ou com CF manipulável pode contornar buckets de origem,
  mas continua sujeito ao orçamento de identidade e ao agregado.
- Pode esgotar uma identidade, bloqueando também seu administrador legítimo.
- Pode variar identidades e esgotar agregado, afetando todos. Tokens repostos
  podem ser consumidos pelo atacante, sem promessa de equidade/disponibilidade.
- Rejeições ainda geram leituras Firestore; retries e o documento agregado causam
  contenção/latência/custo. Admitidas podem ampliar armazenamento de identidades.
- Limites não impedem uso de senha já comprometida dentro do orçamento.
- Origin/CSRF não impedem um cliente HTTP externo de enviar o Origin esperado.
- Nenhum limite elimina custo de tráfego HTTP, parsing, threads e cold starts.

Para poucos administradores e uso eventual, a política testada é ponto de partida
controlado, não medição de capacidade de produção. Recomenda-se aceitar somente
como avaliação/homologação, com decisão explícita sobre bloqueio temporário e
operação de recuperação, observação sanitizada de 429/503 e custos. Não adicionar
reset inseguro, segredo no React ou serviço extra para mascarar a limitação.

Render Free documenta suspensão por inatividade após 15 minutos, retomada em cerca
de um minuto, reinícios e limites de uso. O próprio provedor desaconselha Free
para aplicações de produção. Isso limita disponibilidade e previsibilidade, não
justifica enfraquecer autenticação nem mudar de plano sem autorização. Não houve
consulta ao painel ou comprovação do estado/franquia atual da conta.
Fonte oficial consultada: https://render.com/docs/free

## Bloqueios para publicação e próximo passo

A falta de prova criptográfica do IP NÃO é tratada como prova de ingresso privado
nem impede testar este modelo explícito; não é necessário fabricar um verificador
que aceite tudo. Publicação ainda exige aprovação do usuário e homologação:

- Confirmar decisão de operar publicamente e aceitar riscos residuais registrados.
- Aprovar limites reais/transição uniforme, configuração HMAC/cliente/banco/IAM,
  índices, retenção, monitoramento e procedimento para retirar o ramo Admin.
- Confirmar hosts finais same-site HTTPS, TLS/proxy/Uvicorn, CORS/Origin/cookies
  no navegador e comportamento real dos headers, sem alegar garantias ausentes.
- Medir recursos e custos e aceitar limitações Free antes de operação real.

Próximo passo recomendado: revisão operacional desse contrato e checklist de
homologação autorizada, sem ativação automática. Rollback: composição sem
configuração Admin ou entrada pública anterior, preservando documentos/chave e
Kirvano. Não remover requisitos existentes da modalidade de ingresso verificado.

## Testes e preservação

Somente TestClient/dados sintéticos/armazenamento em memória. Lookup administrativo
mockado; Argon2, serviços e transações fake existentes reutilizados. Testes não
comprovam Render, TLS real, IAM/índices ou contenção real do Firestore. Emulator
não foi necessário para esta mudança de entrada; não foi acessado nem limpo.

Cobertura: default desabilitado, acesso direto sem sessão, senha incorreta/correta,
owner/operator, CF artificialmente variado, identidade/agregado, bloqueio antes
da senha, configuração incompleta/dois buckets, Origin/CSRF/CORS/HTTPS, sessão
expirada, admin desabilitado, negação de permissão, falhas de admissão/sessão,
rotas públicas/Kirvano e app.main sem Admin. Nenhum teste de ataque/carga enviado
a produção; nenhum segredo real usado ou gerado.

Nenhum Admin/Frontend, visual, regras Kirvano, Render, HostGator, DNS, credencial,
owner real ou servidor local foi alterado. Nenhuma contratação/publicação.
Não iniciar PASSO 89.

Resultados executados:

- 21 novos cenários unitários aprovados.
- Conjunto específico de entrada/autenticação/admissão/composição/permissões/
  origem/login/regressão Kirvano: 389 aprovados.
- Suíte Backend completa: 1.384 aprovados, 52 subtestes aprovados,
  228 testes de integração desselecionados.
- Nenhuma falha. Aviso existente de depreciação TestClient/httpx, sem instalar
  dependências. Contagens se sobrepõem, não somar.
- git diff --check passou; app/main.py sem diff e sem routers Admin.

Arquivos alterados nesta etapa: app/admin_entrypoint.py (nova modalidade tipada),
ADMIN_ENTRYPOINT.md (nota sobre o novo contrato). Arquivos criados:
tests/test_admin_public_entrypoint.py e ADMIN_PUBLIC_API.md. Todas as demais
alterações locais anteriores foram preservadas. Nenhuma configuração real ou
Start Command foi alterado; nada publicado.
