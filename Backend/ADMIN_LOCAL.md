# Admin local — PASSO 72

Aplicação separada: `app.tools.admin_local`. **Não usar em hospedagem pública.**
`app.main` continua sem routers Admin e não importa esta ferramenta. Não há
alteração do webhook, das regras comerciais ou de credenciais existentes.
O PASSO 71 (reembolso/chargeback) permanece pendente.

## Pré-requisitos

- Dependências já existentes do Backend e Admin, Java e o JAR do Firestore Emulator.
- Certificado TLS local com SAN localhost. No PASSO 73 foi autorizada uma opção
  **autoassinada**, sem instalar ferramentas/CA nem modificar a confiança do
  macOS. O Chrome pode exigir uma exceção individual para cada porta. Se não
  permitir essa exceção ou bloquear as requisições, interromper e relatar;
  não usar flags para ignorar certificados ou desabilitar validação TLS.
- Portas locais 8080, 8443 e 5174 livres. Não publicar túneis, port-forwarding ou
  proxies. Outros processos/usuários locais não confiáveis estão fora desta
  fronteira de isolamento; usar máquina de desenvolvimento confiável.

## 1. Emulator

Em um terminal, usando o caminho do JAR já disponível na máquina:

```sh
java -jar "$HOME/.cache/firebase/emulators/cloud-firestore-emulator-v1.22.0.jar" --host 127.0.0.1 --port 8080 --project_id demo-dominando-animacao-test --single_project_mode true --single_project_mode_error true
```

Não usar dados reais nem importar/exportar cópias de produção. Os testes
automatizados limpam esse projeto demo: não executá-los enquanto usa a interface.

## 2. Configuração temporária do terminal

Na raiz do projeto, em um terminal dedicado, sem carregar `.env` de produção:

```sh
export ADMIN_LOCAL_ENABLED=true
export ADMIN_LOCAL_ENVIRONMENT=development
export FIRESTORE_EMULATOR_HOST=127.0.0.1:8080
export FIRESTORE_TEST_PROJECT_ID=demo-dominando-animacao-test
export ADMIN_ADMISSION_HMAC_SECRET="$(Backend/.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_LOCAL_TLS_CERT="$PWD/Backend/credentials/local-tls/localhost-735ovkb6/localhost-cert.pem"
export ADMIN_LOCAL_TLS_KEY="$PWD/Backend/credentials/local-tls/localhost-735ovkb6/localhost-key.pem"
export VITE_API_URL=https://localhost:8443
```

O segredo acima é **descartável e exclusivamente local**. Não imprimir, versionar,
reutilizar em produção ou trocar enquanto utiliza os buckets locais. Manter o
mesmo segredo entre reinícios/instâncias que compartilhem esses buckets. Nenhuma
configuração é gravada em arquivos `.env`. O código local não lê dotenv, não usa
Firebase Admin SDK nem credenciais ADC: o cliente tem credenciais anônimas,
endpoint fixo loopback, projeto demo fixo e banco `(default)` explícito.

## 3. Identidade sintética e Backend

```sh
cd Backend
.venv/bin/python -m app.tools.admin_local --prepare-owner
.venv/bin/python -m app.tools.admin_local
```

A preparação pede e confirma uma **senha fictícia nova** via getpass; não usar uma
senha real. E-mail sintético: `local-admin@example.com`. Reutiliza Argon2id,
AdminRecord e a transação de primeiro owner, somente no emulator. Não sobrescreve
administrador nem consome bootstrap real. Uma segunda preparação é rejeitada;
para uma nova identidade, reiniciar um emulator descartável vazio conscientemente.
Falhas são sanitizadas e não confirmam criação: não presumir sucesso após erro.

O runner exige todas as condições locais antes de criar o cliente; falha sem
emulator configurado e sem HMAC válido. Nunca usar `uvicorn --host 0.0.0.0` com
esta factory. O runner oficial fixa `127.0.0.1:8443`, TLS, desativa proxy headers
e access logs. A aplicação também exige peer loopback, HTTPS e Host
`localhost:8443`. Cabeçalhos CF-Connecting-IP/X-Forwarded-For/X-Real-IP não
participam da origem de rate limiting. A procedência de IP em produção continua
pendente de validação própria; esta solução local não resolve essa pendência.

## 4. Admin Vite

Em outro terminal, configure os mesmos valores locais de ativação, ambiente,
certificado, chave e VITE_API_URL (o Vite não precisa do segredo HMAC), depois:

```sh
cd Admin
npm run dev
```

Abrir **https://localhost:5174**. Não substituir localhost por 127.0.0.1 no
navegador. Não usar `vite preview` para este fluxo. O modo local é opt-in e só
afeta `serve`; build e a configuração padrão permanecem independentes.

Não é necessário proxy: o Axios existente usa URL HTTPS absoluta e
`withCredentials`. As duas origens são distintas, porém do mesmo site. O cookie
`__Host-admin_session` continua host-only, Path=/, Secure, HttpOnly, SameSite=Lax,
com prazo máximo de oito horas; portas não isolam cookies. Somente serviços
locais confiáveis devem compartilhar localhost. O navegador envia Origin em
requisições CORS, inclusive a consulta GET da sessão.

CORS permite apenas `https://localhost:5174`, GET/POST, Content-Type e
X-Admin-Request com credenciais. Origin exato, marcador X-Admin-Request e JSON nas
mutações continuam obrigatórios, além da autenticação e permissões existentes.
Não há fallback permissivo para requisições sem Origin, renovação automática ou
retry automático de sessão. Login continua submetido aos dois buckets e Argon2id.

## 5. Verificação manual

1. Sem cookie, páginas protegidas ficam fechadas; sessão retorna 401.
2. Login com a identidade sintética leva ao painel; GET /admin/auth/session
   confirma sessão e permissões sem retornar token.
3. Logout revoga a sessão no emulator e remove o cookie; as páginas ficam fechadas.
4. Parar o Backend deve mostrar o estado de falha de confirmação, sem converter
   indisponibilidade em autenticação ou logout confirmado. Repetir só manualmente.
5. Na aplicação pública `app.main`, `/admin/auth/session` e `/admin/auth/login`
   continuam ausentes (404). Não testar esse item contra a API publicada.

## Testes e limites

Os testes `test_admin_local.py` verificam gates sem rede; os testes
`emulator/test_admin_local_integration.py` exercitam a factory, criação sintética,
login, sessão, cookies, proteção CSRF e logout com Firestore real **emulado**.
Usam o isolamento e as proteções existentes em `tests/emulator_support.py`.
TestClient não é navegador e não comprova comportamento de confiança TLS, CORS ou
cookies no navegador. A homologação visual/interativa continua necessária.

Nenhuma dependência nova, migração ou mudança do ambiente Render/Netlify é exigida.
Encerrar os processos e o terminal dedicado ao finalizar o uso local.

## Homologação no navegador — PASSO 73

Decisão atual: não instalar mkcert/CA, não alterar a confiança do macOS e não
controlar o Chrome. O usuário executa a homologação manualmente. A validação
HTTPS por cliente automatizado não equivale à homologação no navegador.

### Certificado autoassinado preparado

Foi utilizado `/usr/bin/openssl` (LibreSSL 3.3.6), já existente, para gerar um
certificado temporário RSA 2048/SHA-256, válido por sete dias, com SAN
`DNS:localhost` e `IP:127.0.0.1`, finalidade serverAuth e CA:FALSE.

Arquivos desta preparação (não versionados):

- `Backend/credentials/local-tls/localhost-735ovkb6/localhost-cert.pem`
- `Backend/credentials/local-tls/localhost-735ovkb6/localhost-key.pem`

O diretório está sob a regra `credentials/` já existente no `.gitignore` do
Backend, com pasta privada e arquivos modo 600. Não usar `git add -f`, não copiar
as chaves para outro diretório versionado e não compartilhar a chave privada.
O certificado expira em **26/10/2026 às 19:59:57 (America/Sao_Paulo)**; após esse
prazo, preparar outro certificado temporário, sem sobrescrever chaves existentes.

Nos terminais do Backend e do Admin, partindo da raiz do projeto:

```sh
export ADMIN_LOCAL_ENABLED=true
export ADMIN_LOCAL_ENVIRONMENT=development
export ADMIN_LOCAL_TLS_CERT="$PWD/Backend/credentials/local-tls/localhost-735ovkb6/localhost-cert.pem"
export ADMIN_LOCAL_TLS_KEY="$PWD/Backend/credentials/local-tls/localhost-735ovkb6/localhost-key.pem"
export VITE_API_URL=https://localhost:8443
```

No terminal do Backend, configurar também emulator/projeto demo e HMAC descartável
como na etapa 2, antes de executar a preparação interativa e o runner. Manter o
mesmo terminal/segredo para reiniciar o Backend durante a homologação. Não usar
senhas reais. As etapas 1–4 acima continuam sendo a única forma de execução.

### Conflito local encontrado e verificação HTTPS

A checagem encontrou um Vite HTTP preexistente em `[::1]:5174`, enquanto o runner
HTTPS autorizado utiliza `127.0.0.1:5174`. Os dois podem coexistir, mas localhost
pode resolver primeiro para IPv6 e atingir o servidor HTTP, causando erro TLS.
O processo preexistente não foi encerrado. Antes da homologação, o operador deve
parar com Ctrl+C o servidor antigo em seu terminal e conferir as portas:

```sh
lsof -nP -iTCP:5174 -sTCP:LISTEN
lsof -nP -iTCP:8443 -sTCP:LISTEN
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

Não encerrar processos desconhecidos. Com as portas disponíveis, iniciar apenas
os três serviços descritos acima. Não mudar os URLs do navegador para IP como
atalho: a allowlist Origin permanece https://localhost:5174.

Na verificação automatizada desta preparação, o Backend respondeu 401 por HTTPS
sem sessão com certificado/hostname validados. O Vite HTTPS respondeu 200 ao
resolver **somente naquela chamada** localhost para 127.0.0.1 com `curl --resolve`
e `--cacert` apontando ao certificado local. Isso não altera DNS, confiança do
sistema ou navegador, e não desativa validação TLS. A chamada normal ao Admin
ficou impedida pelo servidor HTTP IPv6 preexistente. Nenhum administrador foi
criado, nenhuma senha foi definida e nenhum fluxo foi homologado no Chrome.
Os serviços temporários iniciados na checagem foram encerrados.

### Aviso do Chrome e condição de parada

Abrir primeiro `https://localhost:8443/admin/auth/session` e depois
`https://localhost:5174`. O certificado é autoassinado: é esperado que o Chrome
apresente um aviso de autoridade não confiável. Se a interface normal oferecer
uma exceção individual para **esse endereço local**, o usuário poderá aceitá-la
manualmente para cada porta. Não há garantia de que a política/perfil do navegador
permita isso ou de que a exceção libere as requisições CORS subsequentes.

Se não houver opção normal de continuar, ou se o Admin continuar apresentando
falha de certificado/rede após as exceções locais, **parar e relatar o erro**.
Não usar atalhos ocultos, flags de ignorar certificados, alterações em chrome://flags,
NODE_TLS_REJECT_UNAUTHORIZED=0, importação de CA ou mudanças da confiança do sistema.
Manter localhost nos URLs, cookies seguros e todas as proteções existentes.

### Roteiro de verificação real

Seguir as etapas 1–4 deste guia, mantendo o mesmo segredo HMAC no Backend entre
reinícios. Preparar a senha sintética apenas no terminal. Não executar testes
automatizados que limpam o emulator durante esta verificação.

1. Abrir `https://localhost:8443/admin/auth/session` e conferir se o aviso local pode ser tratado pela interface normal do Chrome. Uma
   navegação direta pode retornar 403 por ausência de Origin: isso é esperado,
   não significa falha de certificado. A consulta autenticada deve partir do Admin.
2. Abrir `https://localhost:5174`: Conexão local liberada pelo usuário, login legível e nenhum conteúdo
   protegido sem sessão. Abrir DevTools, sem exportar HAR nem copiar cookies.
3. Entrar com `local-admin@example.com` e a senha fictícia preparada no terminal.
   Em Network, verificar POST `/admin/auth/login` 200 e GET `/admin/auth/session`
   200. O POST deve ter Origin `https://localhost:5174`, JSON e X-Admin-Request=1.
   Confirmar ausência de erros CORS/certificado e entrada no painel.
4. Em Application/Storage, conferir somente os atributos do cookie:
   `__Host-admin_session`, Secure, HttpOnly, SameSite=Lax, Path=/, host-only.
   O prazo restante deve respeitar oito horas. Não copiar seu valor. Validar
   expiração temporal completa exige cenário próprio ou aguardar o prazo; conferir
   atributos não equivale a demonstrar oito horas reais de expiração no navegador.
5. Atualizar a página: a sessão deve ser consultada e o painel permanecer acessível.
   Navegar para clientes e voltar; só utilizar dados sintéticos.
6. Parar **apenas** o runner local com Ctrl+C e atualizar o Admin. Deve aparecer
   “Não foi possível confirmar o acesso”, sem dados de clientes e sem afirmar
   logout. A animação não deve causar novas consultas de sessão em Network.
7. Conferir título branco em uma linha no desktop, descrição compacta, cartão,
   ícone animado e botão. Verificar viewport móvel sem scroll horizontal e emular
   prefers-reduced-motion: reduce, conferindo a ausência da animação decorativa.
8. Clicar no botão uma vez enquanto o Backend está parado: somente a consulta
   manual deve ocorrer. Reiniciar o mesmo runner no terminal, preservando as
   variáveis locais, e clicar novamente: a sessão válida deve recuperar o painel.
9. Na origem do Admin, testar a ausência do marcador sem enviar senha/token no
   código: `fetch('https://localhost:8443/admin/auth/logout', {method:'POST', credentials:'include'})`.
   Deve retornar 403 e preservar a sessão. O Origin é gerenciado pelo navegador;
   não tentar falsificá-lo. Origens indevidas são verificadas nos testes isolados.
10. Efetuar logout pela interface: POST logout 200, cookie removido, retorno ao
    login. Atualizar e usar Voltar: não liberar conteúdo protegido. GET de sessão
    realizado pelo Admin deve responder 401. Não confundir resposta 503/rede com
    confirmação de logout.

Anotar resultados e mensagens sanitizadas, sem senhas, tokens, cookies, HAR ou
payloads privados. Não alterar configurações de produção durante este roteiro.

## Consulta com cliente fictício — PASSO 74

No mesmo terminal configurado para o Backend local, a partir de `Backend/`:

```sh
.venv/bin/python -m app.tools.prepare_local_customer
```

O comando exige os mesmos gates locais, HMAC administrativo válido, host exato
`127.0.0.1:8080` e projeto `demo-dominando-animacao-test`. Não lê `.env`, não usa
Firebase real, não cria endpoint nem chama a Kirvano. Reutiliza o classificador e
a transação comercial existentes com uma venda totalmente sintética do catálogo
autorizado. A chave HMAC da identidade dessa fixture é sintética, pública e local,
separada da autenticação; nenhum segredo comercial/de produção é carregado.

Cliente preparado:

- E-mail: `cliente-teste@example.com`.
- Documento: `local-step74-customer-v1`.
- Conta `enabled`, ativação `pending`.
- Assinatura mensal `active`, compra `active`, entitlement `granted` para `portal`.
- Vínculos reais de compra/assinatura/entitlement; período sintético de 30 dias,
  iniciado no dia anterior à primeira preparação. Não há extensão automática.
- Compra não ativa a conta: `can_access_portal` continua negando acesso.

Primeira execução cria os registros atomicamente. Uma repetição consistente é
somente leitura: não altera timestamps, contadores ou prazo. Se houver e-mail
duplicado, identidade diferente, documentos incompletos, estado administrativo
alterado ou período vencido, interrompe sem reparar, sobrescrever ou apagar.
Uma falha/resultado incerto não confirma criação; verificar o estado antes de
repetir. Contenção pode esgotar as tentativas nativas do SDK; não há nova política
de retentativas externas neste comando.

### Conferência manual no Chrome

1. Manter os serviços atuais. Abrir `https://localhost:5174` e entrar com o
   administrador **sintético já existente**, usando sua senha local pelo formulário.
2. Em `/clientes`, pesquisar `cliente-teste@example.com`. A busca é exata e aceita
   normalização de espaços externos/maiúsculas; não faz busca parcial.
3. Abrir “Ver cliente” e conferir e-mail, conta habilitada e ativação pendente.
   A ficha também pode ser aberta em
   `https://localhost:5174/clientes/local-step74-customer-v1` após autenticação.
4. Conferir compra aprovada registrada. A confirmação continua retornando
   `approved_purchase_recorded=true`, `current_payment_validity=not_verified` e
   `requires_kirvano_review=true`; isso não comprova validade financeira em tempo real.
5. Voltar aos clientes. A lista usa o cursor existente e 20 registros por consulta;
   não criar clientes para preencher páginas. O contrato HTTP preexistente aceita
   limites de 1 a 50, com padrão 20; este passo não o alterou.
6. **Não executar ativação, suspensão ou retomada neste passo.**

Se o login falhar após reiniciar o emulator, verificar primeiro os três serviços
e a existência da identidade sintética no projeto demo. Não executar
`--prepare-owner` automaticamente, não apagar dados nem recriar administradores
desnecessariamente. O usuário controla o Chrome; testes HTTP/SSR não equivalem
à homologação manual de ponta a ponta.

### Testes com o emulator da homologação ativo

O arquivo novo é explicitamente **não destrutivo** e substitui a fixture padrão
que limpa o projeto inteiro. Usa IDs temporários únicos e remove apenas seus
próprios documentos, mantendo o cliente acima e o administrador da homologação.

```sh
# A partir de Backend/, com as variáveis locais já configuradas:
.venv/bin/python -m pytest --run-firestore-emulator -q tests/emulator/test_local_customer_lookup_integration.py
```

Não executar a pasta inteira `tests/emulator` contra o ambiente manual ativo:
as fixtures antigas ainda fazem limpeza global. Elas não foram alteradas.
