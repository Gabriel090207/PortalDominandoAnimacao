# PASSO 97.21 — elegibilidade por produto, sem whitelist de ofertas

## Regra atual

Produto oficial já utilizado pelo Backend:
`0c5f6369-5a8a-467c-ba81-61cde05b7917` (`AUTHORIZED_PRODUCT_ID`).

Antes, classify_commercial_event exigia simultaneamente esse produto e uma oferta
constante. Por isso, uma nova oferta do mesmo produto ficava em revisão. Agora,
seleciona o item de products cujo product_id normalizado corresponde EXATAMENTE
ao produto autorizado e cujo is_order_bump seja false. Não há whitelist de offer_id.
O offer_id recebido precisa continuar presente e sintaticamente válido segundo
normalize_event (identificador ASCII de até 128 caracteres). Não aceita ausência,
tipo incorreto, string vazia ou formato inválido. Dois itens elegíveis do produto,
mesmo com ofertas distintas, são ambíguos e ficam em revisão: não escolhe o primeiro.

Aceita todas as ofertas DESSE produto que cumpram o contrato comercial vigente:
- SALE_APPROVED com status APPROVED;
- type RECURRING, frequência MONTHLY, cobrança inteira positiva;
- e-mail e estruturas obrigatórias válidos;
- payment.finished_at e plan.next_charge_date válidos, com fim posterior ao início;
- timezone explícito, sem datas ambíguas/inexistentes;
- exatamente um item elegível não order-bump do produto autorizado.

O valor (incluindo R$ 1,00) não autoriza produto, não identifica compra e não altera
regras de período. Cobrança avulsa, anual ou outra periodicidade continua em revisão.
A associação oferta/produto vem do MESMO item no webhook autenticado: não consulta
catálogo externo ou inventa campos. Outro produto não obtém efeitos comerciais.
Se houver itens de outros produtos no payload, somente o item elegível autorizado
é processado, mantendo o comportamento anterior de seleção.

## Persistência e ciclo de vida

CommercialCandidate/CancellationCandidate usam o offer_id real recebido, não a
constante antiga. Compra e assinatura já persistiam candidate.offer_id e continuam
fazendo isso, sem migração, troca de schema ou alteração de IDs de compra/evento.
A constante AUTHORIZED_OFFER_ID permanece somente como referência para fixtures
locais existentes; não participa da decisão comercial nem é um cadastro obrigatório.

A seleção por produto também vale para renovação e cancelamento, pois uma nova
assinatura não poderia ser reconhecida corretamente depois se esses eventos ainda
exigissem a oferta antiga. As verificações transacionais de vínculo NÃO foram
relaxadas: renovação/cancelamento devem corresponder ao produto, oferta, usuário,
venda/assinatura originalmente persistidos. Trocar offer_id em uma assinatura já
registrada continua review_required; a mudança não implementa migração de plano.

Nova compra elegível registra cliente/compra e uma intenção por purchase_id na mesma
transação; nome do webhook é preservado, escapado no HTML e saudação usa fallback
quando inválido. Usuário novo continua enabled/pending, sem acesso automático.
Reenvio comprovado não recria intenção nem snapshot ou novo e-mail. Renovação,
cancelamento, reembolso e chargeback não criam boas-vindas adicionais. Regras de
cancelamento e de revisão de reembolso/chargeback permanecem como antes.

Não há varredura, migração ou reprocessamento automático de eventos históricos.
Um novo recebimento autenticado é avaliado pela política atual; aplicações já
comprovadas mantêm sua deduplicação e seus vínculos persistidos.

## Resend continua desativado

Template aprovado, credenciais, .env e registro privado da operação local não
foram alterados. Não instalamos runtime público, provedor real, recuperação, filtro
por oferta ou nova variável de ambiente. main.app continua create_app() sem
welcome_installation. Publicar este código não ativa e-mail.

O bloqueio comercial por oferta descrito no PASSO 97.18 está resolvido. Não é mais
necessário cadastrar cada oferta. A proposta antiga de whitelist de DESPACHO por
oferta não foi implementada nem se torna requisito desta regra; a decisão atual
é que as compras mensais elegíveis do produto recebam boas-vindas quando o envio
for futuramente autorizado e instalado. Nenhum envio geral foi ativado agora.

Para automatizar no Render ainda faltam autorização de habilitação, bootstrap
explícito do runtime/provedor com projeto/banco correto, configuração Resend válida,
WhatsApp oficial e corte temporal fixo escolhido pelo usuário. Os nomes existentes
continuam: RESEND_API_KEY, PURCHASE_WELCOME_FROM,
PURCHASE_WELCOME_WHATSAPP_URL, PURCHASE_WELCOME_SEND_ENABLED,
PURCHASE_WELCOME_NOT_BEFORE, PURCHASE_WELCOME_RECOVERY_ENABLED,
PURCHASE_WELCOME_RECOVERY_BATCH_SIZE. Manter SEND_ENABLED e RECOVERY_ENABLED false
nesta etapa. Variáveis sozinhas não instalam o runtime na entrada pública atual.
IAM e, caso habilitada a recuperação, índice composto precisam ser confirmados na
operação real. Nenhuma alteração de Render, Start Command ou DNS foi feita aqui.

## Validação sintética

Unitários cobrem oferta principal, oferta mensal sintética distinta de R$ 1,00,
terceira oferta, IDs inválidos/ausentes, outro produto, periodicidade/tipo incorreto,
ambiguidade, persistência de offer_id, duplicidade, nome e ativação pendente,
renovação/cancelamento da nova oferta e bloqueio de alteração do vínculo original.
Os contratos antigos que negavam qualquer oferta diferente foram atualizados para
negar oferta inválida ou outro produto, sem remover verificações negativas.

No Emulator, o fluxo HTTP/SDK real foi parametrizado para oferta principal e nova
oferta mensal sintética: security-token, cliente e nome, compra/offer_id, uma intenção,
renderer aprovado, provedor FAKE, duplicidade e eventos negativos. O teste negativo
anterior de oferta diferente passou a usar produto diferente, conforme a nova regra.
IDs próprios e outbox isolada; limpeza somente dos documentos criados nos testes.
Não usa destinatários, compradores, banco ou APIs reais.

Resultado: **1640 testes Backend e 52 subtestes aprovados**, incluindo 23 novos
cenários unitários; **33 testes Emulator aprovados**, com ofertas principal/nova
no fluxo completo e regressões de compra, trigger, runtime e dispatcher. Nenhuma
falha; aviso preexistente do TestClient. 284 cenários Emulator desmarcados na suíte
unitária e executados à parte somente os arquivos isolados selecionados.
