# Proteção opt-in de requisições administrativas

AdminRequestSecurity, em app/api/admin_request_security.py, é uma dependência
FastAPI para futuras operações que alteram estado. Não registra rotas, não muda
main.py/CORS, não lê cookies e não inicializa Firebase. Não usar globalmente nem
no webhook Kirvano. Não autentica: combinar com AdminHTTPAuthentication e sua
require_permission nas futuras operações protegidas; login continuará público
quanto à sessão, mas protegido quanto à origem e admissão.

Configuração explícita: AdminRequestSecurityConfig(allowed_origins=(... ,)).
Não há origem padrão, domínios provisórios ou carregamento automático de ambiente.
A composição futura deverá fornecer a lista aprovada; nenhuma variável nova é
necessária nesta entrega. O objeto é imutável e validado na construção.

Desenvolvimento e produção devem injetar objetos/listas separados. Ambos exigem
HTTPS; desenvolvimento usa origem local HTTPS explícita (por exemplo com TLS
local). Não há flag de desenvolvimento, bypass ou opção HTTP que possa enfraquecer
produção. A implantação futura deve selecionar a configuração correta; essa
seleção operacional não está implementada. Origem local não é adicionada à lista
de produção automaticamente. Ausência/configuração inválida impede construção
com AdminRequestSecurityConfigurationError sanitizado, sem afetar serviços atuais.

Cada chamada exige exatamente um Origin bruto ASGI, ASCII, em representação HTTPS
sem caminho, barra final, credenciais, query, fragmento, espaços, escapes ou
curingas. Hostnames devem estar em minúsculas; IPv6 entre colchetes é validado.
Comparação é literal de esquema+host+porta, sem normalização permissiva ou sufixos.
A porta padrão deve normalmente ser omitida como na serialização do navegador;
`:443` explícito e ausência de porta são entradas diferentes. Configurar exatamente
a origem que o navegador envia. Origin null, ausente ou duplicado é rejeitado.

Mutações permitem POST/PUT/PATCH/DELETE, nunca GET/HEAD/OPTIONS. Exigem exatamente
um X-Admin-Request com valor literal `1` (nome do header case-insensitive). O valor
é público, não é segredo ou prova de identidade. Navegadores não conseguem enviar
esse header em um formulário tradicional; scripts de outra origem dependem de
preflight e da política CORS restrita. Clientes não navegador podem forjar ambos
os headers: a autenticação, autorização e admissão continuam obrigatórias.

Por padrão requires_json=True exige um Content-Type application/json, aceitando
também charset=utf-8 opcional. Nomes de media type/charset não diferenciam caixa;
outros parâmetros, formatos, duplicatas e formulários são rejeitados. Isso valida
o media type, não o conteúdo: a futura rota deve validar o JSON, schema e tamanho.
Para operações SEM corpo, como o logout planejado, usar requires_json=False;
essas operações não devem interpretar corpos alternativos. A opção não remove
validação de Origin ou do header e não deve ser usada em operações que recebem JSON.

Erros fixos: 403 para origem/header inválidos; 415 para Content-Type; 405 com Allow
para método inadequado. Nenhum conteúdo de header é registrado ou retornado.
Nenhum token CSRF separado é emitido: a estratégia combina Origin estrito, header
não simples e JSON, com CORS restrito e cookies seguros na integração futura.
Não protege contra XSS na origem autorizada ou comprometimento dessa origem.

CORS continua independente. Na futura composição, aprovar somente origens exatas,
allow_credentials=True, métodos necessários e headers Content-Type e X-Admin-Request.
Preflight OPTIONS deve ser tratado pelo middleware antes das dependências de
mutação; não exige cookie/sessão e não executa efeitos. Testar erros 401/403/415/
429/503 com CORS adequado. Não permitir todos os subdomínios ou refletir qualquer
Origin. Não aplicar essa política ao tráfego servidor-servidor da Kirvano.

Pendências: origens finais, composição HTTP, CORS, emissão de cookie seguro,
proteção de sessão/permissões e a confirmação operacional da fronteira de IP no
Render para rate limiting. Nada foi habilitado em produção.
