# Preparação estática do Admin — PASSO 86

Nada publicado. Domínios finais e recursos do plano HostGator ainda precisam de
confirmação. API administrativa continua fora do backend público: o pacote não
cria uma API funcional, nem libera login por conta própria.

## Compilar sem alterar o ambiente local em uso

Na pasta Admin, usar Node/dependências já existentes:

```sh
npm run typecheck
npm run lint
npm test
VITE_API_URL="$URL_HTTPS_DA_API_APROVADA" npm run build:hosting
```

Definir a variável de comando acima com a origem HTTPS final aprovada, sem senha,
token, query, fragmento ou caminho. Não usar localhost/IP nem presumir o hostname
Render como solução definitiva. Domínios Admin/API HTTPS sob o mesmo site
registrável preservam o desenho SameSite=Lax existente, sujeito à homologação.

build:hosting executa TypeScript e o Vite de produção existente com base=/,
saída separada dist-hosting/, sem source maps. Ignora arquivos .env e a exposição
automática de VITE_*; define somente VITE_API_URL explicitamente. Os arquivos
privados .env existentes não foram abertos. A configuração padrão de dev/build
continua intacta, e dist/ não foi sobrescrito.

O build comum npm run build continua existindo e usa suas fontes de ambiente
habituais. Para o artefato preparado aqui, usar build:hosting. Qualquer variável
VITE_* é conceitualmente pública: nunca colocar segredos nela, mesmo que este
script filtre variáveis adicionais. O filtro não detecta segredo inserido no
código-fonte. Não versionar chaves ou publicar .env/source/node_modules.

A compilação de validação usou https://api.example.invalid, domínio fictício
sem API. NÃO publicar esse artefato como configuração operacional; recompilar
com o endereço aprovado e revisar a saída antes de uma publicação autorizada.

## Estrutura futura, somente no diretório do Admin

Publicar o CONTEÚDO de dist-hosting (incluindo o arquivo oculto .htaccess) no
document root exclusivo do subdomínio Admin aprovado:

```text
<DIRETORIO_EXCLUSIVO_ADMIN>/
  index.html
  .htaccess
  assets/
    index-<hash>.js
    index-<hash>.css
```

Não hospedar sob /admin de outro site com esta configuração: base=/ e BrowserRouter
sem basename pressupõem raiz do próprio subdomínio. Não substituir .htaccess do
site principal, Frontend ou portal.dominandoanimacao.com. Não modificar DNS,
e-mails ou outros sites como parte desta preparação.

## Fallback e headers

hosting/admin.htaccess.template é EXCLUSIVO do futuro diretório Admin. O build
substitui o marcador de origem da API e grava dist-hosting/.htaccess. Não publicar
o template sem resolver o marcador. Usa mod_rewrite/mod_headers e overrides
locais; se não suportados, corrigir com o provedor, sem remover controles para
silenciar erro 500. Não há IfModule para omitir silenciosamente headers.

Arquivos/diretórios existentes são preservados. Caminhos SPA não existentes
retornam index.html; /assets/ não recebe fallback, inclusive arquivos ausentes
que devem responder 404. A entrega de HTML não concede sessão/permissão: React
continua verificando a sessão antes de renderizar conteúdo protegido.

Headers propostos, limitados ao diretório:

- CSP default-src 'none'; scripts/estilos/fontes próprios; imagens próprias e
  data: para imagens embutidas; connect-src somente a origem HTTPS configurada;
  object-src/base-uri/frame-ancestors 'none'; form-action 'self'. Sem unsafe-eval,
  unsafe-inline ou curingas de conexão. Não há fontes/scripts de terceiros no
  código inspecionado nem style= inline nas telas atuais. Homologar CSP no
  navegador real antes de publicar: configuração de headers não prova execução.
- X-Content-Type-Options: nosniff.
- Referrer-Policy: no-referrer.
- X-Frame-Options: DENY, junto com frame-ancestors.
- Cache-Control: no-store para HTML, fallback e erros.
- JS/CSS com hash Vite e resposta 200: public,max-age=31536000,immutable.

Não modifica CORS, cookies ou HSTS global; não adicionar includeSubDomains sem
analisar todo o domínio. HTTPS/redirect deve ser confirmado no subdomínio pela
hospedagem; não presumir headers de proxy para construir redirects.

## Verificações na HostGator — somente depois de autorização

Confirmar plano/subdomínio disponível, document root isolado, versão real
Apache/LiteSpeed, mod_rewrite/mod_headers, AllowOverride para Options, FileInfo e
DirectoryIndex, ausência de regras herdadas que capturem a SPA, tipos MIME JS/CSS,
limites e cache/CDN do plano. Verificar certificado válido e renovação automática.
HostGator documenta SSL gratuito para diversos planos, mas isso não confirma os
recursos da contratação específica ou seu provisionamento atual.

Depois de publicação autorizada, conferir manualmente:

1. HTTPS sem exceções, domínio correto e HTTP redirecionando para HTTPS.
2. Raiz, navegação interna e reload direto em /clientes e /clientes/ID_SINTETICO.
3. JS/CSS retornando conteúdo/tipos corretos; asset ausente retorna 404, não HTML.
4. Headers nas respostas reais, inclusive fallback/erros; sem headers duplicados
   ou políticas herdadas incompatíveis. Cache HTML no-store e assets immutable.
5. CSP sem violações necessárias ao app, sem ampliar connect-src para '*'.
6. API indisponível e sessão não confirmada não mostram dados protegidos; cookies
   permanecem do navegador, HttpOnly/Secure, sem tokens em localStorage.
7. CORS/Origin/CSRF/sessões e ingresso no backend precisam de aprovação própria.

Não há homologação HostGator ou navegador de produção concluída neste passo.

## Rollback futuro

Antes da publicação, guardar versão anterior completa, configuração pública de
API e .htaccess do Admin em backup fora da área pública. Não fazer backup de
segredos no pacote. Preferir troca coordenada do diretório/artefato se suportada
pelo plano. Evitar HTML novo apontando a assets ainda não publicados; manter assets
antigos durante a janela de transição para abas abertas, conforme espaço/política.
Em rollback, restaurar artefato completo e configuração correspondente, sem
alterar backend/banco/sessões ou o site principal. Verificar caches externos.

## Fontes oficiais

- Apache rewrite: https://httpd.apache.org/docs/2.4/rewrite/flags.html
- Apache headers: https://httpd.apache.org/docs/2.4/mod/mod_headers.html
- HostGator SSL: https://suporte.hostgator.com.br/hc/pt-br/articles/30807155887251-Como-obter-um-certificado-SSL-gratuito

## Resultados locais desta etapa

- TypeScript, lint e build: aprovados.
- 328 testes aprovados, zero falhas (326 anteriores e dois de configuração novos).
- Build separado: index.html, JS e CSS com hash, mais .htaccess gerado; assets
  referenciados por /assets/ na raiz do subdomínio, sem source maps.
- Uma variável VITE_SYNTHETIC_PRIVATE_MARKER com marcador fictício foi fornecida
  ao processo de build: o marcador NÃO apareceu no artefato. Também não apareceram
  127.0.0.1 ou o placeholder não resolvido do template. Nenhum segredo real foi
  usado. Isso não é um scanner universal de segredos existentes no código.
- A API configurada no pacote é somente https://api.example.invalid. Existe um
  literal http://localhost na biblioteca React Router como base auxiliar interna,
  que usa a origem real do navegador quando disponível; não é API, asset remoto
  ou configuração local da aplicação. Não foi alterada a dependência para apagar
  essa string. Logo, não afirmar ausência literal de localhost no bundle inteiro;
  está confirmada a ausência de API local configurada neste build.
- Apache 2.4.66 disponível no macOS: sintaxe aceita e seis verificações HTTP
  aprovadas: raiz, /clientes, /clientes/synthetic-customer, JS, CSS e asset ausente.
  Confirmados fallback com HTML idêntico, cache no-store/immutable, tipos MIME,
  CSP, anti-framing, nosniff e Referrer-Policy. Servidor em porta aleatória de
  loopback, sem acesso a API, encerrado somente o processo criado pelo teste.
- A primeira execução npm ocorreu na raiz sem package.json e falhou; comandos
  repetidos na pasta Admin passaram. As duas primeiras tentativas Apache no
  diretório Documents não serviram a página (403 por restrição de acesso macOS).
  A repetição com cópia temporária em /tmp passou, sem alterar permissões ou
  privacidade do macOS. Não foi corrigido/alterado servidor global.
- Entrega HTTP local não comprova execução JS/CSP em navegador, HTTPS real,
  LiteSpeed ou configuração do plano HostGator. Testes React verificam navegação,
  gates de sessão e API indisponível; não foi feita homologação de navegador.
- git diff --check passou. Backend/, Frontend/, visual/Admin/src, dist/ anterior,
  servidores do usuário e configurações reais foram preservados. Nada publicado.

Próximas decisões: escolher hosts finais, confirmar plano/diretório/overrides/SSL,
aprovar e preparar API administrativa/ingresso e só depois homologar cookies,
CORS e navegador real. Não iniciar PASSO 87 automaticamente.
