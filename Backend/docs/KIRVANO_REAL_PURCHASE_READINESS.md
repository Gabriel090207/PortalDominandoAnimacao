# PASSO 97.18 — preparação da compra real (sem compra ou envio)

**Atualização no [PASSO 97.21](KIRVANO_PRODUCT_ELIGIBILITY.md):** o bloqueio de
oferta individual descrito abaixo foi substituído por elegibilidade pelo produto.
Ofertas mensais válidas desse produto não exigem whitelist individual. Este texto
registra o diagnóstico histórico; a instalação/habilitação do runtime continua
pendente. A restrição temporária de despacho proposta abaixo não foi implementada.

O envio real isolado anterior foi confirmado pelo usuário. Não foi repetido nem
foi lido/alterado o registro privado para tentar outra operação. O template HTML
aprovado é preservado byte a byte. Esta etapa NÃO habilita runtime ou Resend real.

## Nome do comprador e cadastro

A extração lê `customer.name` do payload autenticado de SALE_APPROVED, não um nome
fixado no renderer. A função optional_customer_name remove espaços nas extremidades,
aceita até 200 caracteres e rejeita texto vazio, tipos incorretos e controles Unicode.
Não verifica identidade legal, não reescreve o nome ou normaliza capitalização/NFC.
Nome ausente/inadequado vira None; a saudação fica `Olá!`. Um nome contendo markup
é tratado como texto e escapado pelo renderer antes de entrar no HTML.

Nova compra elegível cria/reutiliza usuário por e-mail normalizado. O nome opcional
vai para users.display_name quando ausente e para transactional_emails.customer_name.
Não sobrescreve display_name já existente. A intenção de uma NOVA compra usa o nome
recebido nessa compra; não busca automaticamente nome antigo se ele estiver ausente
no webhook. Reenvio não altera o nome, a intenção ou o snapshot já reservado.

O renderer aprovado usa esse campo para `Olá, Gabriel Oliveira!`, tanto em HTML
quanto em texto. `Cliente Exemplo` existe apenas na prévia e na ferramenta de teste
local, nunca como nome fixo no fluxo de produção. O WhatsApp vem do objeto de contato
validado da configuração, sem telefone real no template ou nos testes.

## Kirvano preservada

Webhook exige security-token único, com comparação segura, validação JSON e limite
de corpo. Compra elegível registra inbox/variante, cliente/identidade, assinatura,
compra, direito e intenção em uma transação. Purchase ID deriva de escopo + sale_id
+ número de cobrança; welcome intent ID deriva da compra. Reenvio comprovado não
recria intenção nem envia novamente. Usuário novo fica enabled/pending, sem ativação.

Renovação não cria novas boas-vindas. Cancelamento aplica sua regra existente sobre
assinatura. Reembolso/chargeback permanecem em revisão, sem nova implementação de
revogação financeira. Eventos inválidos, em revisão ou não elegíveis não criam o
conjunto comercial/intenção de boas-vindas. Segurança e respostas não foram alteradas.

## BLOQUEIO: oferta nova não está autorizada comercialmente

O classificador atual aceita somente o par constante:
- produto AUTHORIZED_PRODUCT_ID;
- oferta AUTHORIZED_OFFER_ID;
ambos em app/services/kirvano_commercial_service.py. Não reproduzimos IDs comerciais
como uma nova configuração nem os alteramos nesta etapa.

Também exige type=RECURRING, status=APPROVED, charge_frequency=MONTHLY, número de
cobrança inteiro positivo, um produto/oferta autorizado não order-bump e período
válido entre payment.finished_at e plan.next_charge_date. Timezone é explícito.
Valor monetário não define elegibilidade nem deve identificar o teste.

Portanto, criar uma NOVA oferta de menor valor com outro offer_id NÃO basta:
o webhook continuará aceitando a recepção, mas a aplicação ficará review_required
por produto/oferta não autorizado, sem compra/cliente novos ou intenção. Uma oferta
ONE_TIME também não corresponde à regra comercial atual. Isso é comportamento
existente, não falha Resend. Não substituir o ID autorizado para forçar um teste.

Quando a oferta existir, precisamos receber/confirmar:
1. products[].id (produto) e products[].offer_id (oferta), realmente presentes no payload;
2. tipo de venda e frequência; se a oferta cumpre o contrato mensal vigente;
3. presença de plan.charge_number, payment.finished_at e plan.next_charge_date;
4. URL de checkout apenas para o usuário realizar a compra, sem usá-la como chave;
5. após a compra: sale_id e plan.charge_number para identificar a compra exata.

Se o novo par não corresponder ao atual, falta uma decisão e autorização explícita
sobre a elegibilidade comercial dessa oferta de teste. Não inventar formatos ou
ampliar regras sem os dados. Este documento NÃO autoriza a oferta nem a compra.

## Restrição de despacho proposta — ainda NÃO implementada

Hoje não há allowlist de oferta no despacho: a proteção é comercial, temporal,
de reserva e instalação explícita. Habilitar um runtime geral enviaria para todas
as novas compras comercialmente elegíveis após o corte. Isso NÃO está autorizado.

Menor mudança futura: um escopo de teste explícito, desativado por padrão, exigindo
product_id + offer_id exatos e, quando disponível, sale_id/charge_number da compra
específica. O gate deve comparar o par da COMPRA PERSISTIDA e validada dentro da
transação de reserva, junto de purchase_id/origin_event, antes de chamar o provedor.
O mesmo gate deve valer para trigger e eventual recuperação; validar somente o
payload HTTP ou só filtrar a fila não é suficiente.

Fora do escopo: negar APENAS o despacho, deixando compra/intenção e ACK comercial
intactos. Não ativar recuperação para o primeiro teste. Sem escopo completo,
a instalação de teste deve permanecer indisponível. Adicionar testes de par correto,
produto correto/oferta diferente, oferta correta/produto diferente, sale_id diferente,
concorrência e ausência de envio fora do escopo ANTES de habilitar no Render.

Não implementamos esse gate sem IDs/decisão de oferta: é proposta expressamente
separada do código existente. Não existem variáveis de escopo de teste consumidas
pelo código atual. Para isolamento mais estrito de UMA compra, manter envios
desativados na compra e autorizar posteriormente o ID conhecido; a ferramenta
local test_purchase_welcome NÃO pode ser reutilizada contra produção, pois exige
Emulator. Qualquer execução controlada em produção exigirá implementação/autorização
próprias, sem remover guardas do utilitário local.

## Runtime no Render: NÃO basta configurar variáveis

A entrada pública conhecida é `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
Não consultamos nem alteramos o painel real para confirmar configuração operacional.
O código atual termina em `app = create_app()` sem welcome_installation: mesmo com
variáveis presentes, não instala runtime, provedor ou envio automático. Commit/push
não o habilitam. A entrada administrativa preparada também não é ativada.

Antes da compra com e-mail automático, ainda falta implementar/selecionar um
bootstrap público autorizado que carregue a configuração, construa o cliente
Firestore central correto, injete ResendEmailProvider com transporte TLS normal,
aplique o gate de teste e forneça WelcomeRuntimeInstallation explicitamente.
Reutilizar app.main.create_app, não criar segundo backend ou router de disparo.
A factory sem argumentos e sem instalação continua desabilitada; trocar só para
`app.main:create_app --factory` também NÃO instala envio. Não alterar Start Command
ou variáveis sem a próxima autorização. A configuração completa deve falhar com
e-mail desabilitado, preservando health/webhook, se estiver inválida.

## Configurações EXATAS para a futura habilitação autorizada

| Nome existente | Valor/ação futura |
| --- | --- |
| RESEND_API_KEY | Chave privada de envio do domínio; configurar como segredo no Render, nunca copiar para Git/chat |
| PURCHASE_WELCOME_FROM | boasvindas@envios.dominandoanimacao.com; e-mail simples, sem nome de exibição |
| PURCHASE_WELCOME_WHATSAPP_URL | URL oficial wa.me validada, sem telefone no código |
| PURCHASE_WELCOME_SEND_ENABLED | MANTER false agora; true apenas após bootstrap E gate implementados/revisados e autorização |
| PURCHASE_WELCOME_NOT_BEFORE | Instante ISO-8601 fixo com fuso escolhido pelo usuário para o início autorizado; não definir automaticamente nem retroceder |
| PURCHASE_WELCOME_RECOVERY_ENABLED | false no primeiro teste para não drenar fila |
| PURCHASE_WELCOME_RECOVERY_BATCH_SIZE | Inteiro 1–20, default 5; não ativa recuperação e não é necessário alterá-lo para teste sem recuperação |

Manter as configurações comerciais existentes: KIRVANO_WEBHOOK_TOKEN,
KIRVANO_WEBHOOK_TIMEZONE, EMAIL_IDENTITY_HMAC_SECRET. Firebase usa o loader central:
FIREBASE_CREDENTIALS_JSON não vazio tem prioridade sobre FIREBASE_CREDENTIALS_PATH.
Não modificar credenciais ou reutilizar segredos. Projeto esperado do portal é
portaldominandoanimacao-db, banco (default), sem variáveis de Emulator/teste.
expected_project_id é parâmetro de WelcomeRuntimeInstallation, NÃO uma variável
lida automaticamente pelo runtime. FIREBASE_PROJECT_ID é lida na configuração
Admin preparada; não presumir que fornecê-la instala o runtime público de e-mail.
allow_emulator deve permanecer false no futuro runtime de produção.

Nenhuma nova dependência é necessária para o adapter atual: HTTPX já é dependência
do Firebase Admin. O template HTML precisa estar no checkout junto ao módulo.
Não houve alteração de requirements ou instalação de pacotes nesta etapa.

## Firestore e disponibilidade

IAM da conta de serviço deve permitir as leituras comerciais e leitura/transação/
update de transactional_emails. A transação comercial precisa criar o documento
novo dessa coleção, mesmo com ENVIO desativado. Já ocorre no código versionado.
Confirmar permissões operacionais sem inferir garantia por testes do Emulator.
Não há migração destrutiva, novo índice ou acesso a Resend na inicialização padrão.

Despacho direto por IDs usa reads de documentos e não exige índice novo de fila.
Se recuperação for habilitada FUTURAMENTE, a consulta exige índice composto de
transactional_emails: status ASC, kind ASC, created_at ASC, com ordenação final
__name__ ASC. Nenhum índice foi criado/publicado nesta etapa. Um lote ao boot não
é garantia contínua de entrega sob suspensão/reinício do Render. Reservas incertas
não são reabertas e a retenção idempotente do Resend não é proteção permanente única.

## Validação sintética desta etapa

Novo cenário real ASGI/SDK no Emulator recebe SALE_APPROVED de Gabriel Oliveira,
valida token, passa pelo orquestrador/classificador e transação reais, guarda nome,
compra e intenção, chama SOMENTE fake, rende HTML/texto com o nome e contato
sintético por configuração, verifica usuário pendente e consulta Admin, repete
webhook sem nova chamada e confirma regras existentes de cancelamento/negativos.
Outro cenário comprova que oferta não autorizada recebe ACK e fica em revisão,
sem intenção/envio. Unitários cobrem nome vazio, controles, excesso de tamanho,
escape HTML e preservação do nome já cadastrado.

Fixtures usam e-mails/IDs exclusivos, outbox em namespace próprio, credenciais
anônimas e loopback demo; cleanup apenas de referências criadas pelo teste.
A primeira execução teve uma asserção incorreta sobre o UUID do usuário. O
orquestrador aloca seu próprio UUID; o teste foi corrigido e a limpeza agora segue
a identidade exclusiva da fixture. Um órfão do teste falho foi removido somente
após verificação exata de ID/e-mail sintético. Nenhum documento do usuário foi apagado.

Não executado --send-once, não lido/apagado registro de teste para reenviar, nenhuma
compra/oferta real, nenhuma chamada de API Kirvano/Resend ou alteração de Render/DNS.

Resultados finais: **1617 testes Backend e 52 subtestes aprovados**; **32 testes
Emulator aprovados** nos arquivos explicitamente selecionados, sem limpeza global.
Incluem 6 novos cenários unitários de nome e 2 novos cenários integrados. Na suíte
unitária, 283 cenários Emulator ficaram desmarcados. Uma falha inicial no teste de
UUID foi corrigida como descrito acima; nenhuma falha na execução final. Aviso
preexistente do TestClient; `git diff --check` sem problemas. Hash local confirmou
template aprovado e operation.json privados inalterados. As duas flags locais
de envio/recuperação continuam false. Quatro servidores locais preservados.
