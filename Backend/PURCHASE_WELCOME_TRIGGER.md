# PASSO 95 — gatilho pós-commit e recuperação limitada

Continuação: o [PASSO 96](PURCHASE_WELCOME_RUNTIME.md) conecta a seleção explícita
às factories e ao lifespan, com provedor injetado e instalação gerida. O texto
abaixo registra o escopo original do PASSO 95.

Preparado e testado exclusivamente com HTTP fake e dados sintéticos. Nenhuma
configuração real foi habilitada. Não adiciona endpoint, fila, serviço ou polling.

## Integração existente

A rota Kirvano mantém token, limite do corpo, validação JSON, processamento em
threadpool e resposta. Só DEPOIS do retorno confirmado da persistência chama
`schedule_purchase_welcome`. Apenas SALE_APPROVED com receipt novo e recebido
pode agendar uma BackgroundTask. Reenvio não agenda outra tarefa; os demais eventos
não a agendam. O helper não cria intenção: essa criação continua na transação da
compra. Uma classificação comercial em revisão não terá intenção elegível para enviar.

A tarefa `after_event` lê a aplicação comercial persistida, encontra a intenção
pelo ID determinístico da compra e verifica pending/vínculo/corte. O dispatcher do
PASSO 94 revalida compra/cliente/evento, faz reserva transacional, salva snapshot,
chama HTTP fora da transação e persiste resultado. Destinatário/conteúdo não são
recebidos livremente do navegador. Cadastro, pesquisa Admin e ativação manual
continuam iguais; envio não altera usuário/assinatura/entitlement.

BackgroundTasks executa depois do envio da resposta ASGI. O teste HTTP pode esperar
pelo término da tarefa por comportamento do TestClient; isso não significa que a
transação comercial aguarda o provedor. Firestore e HTTP síncronos rodam fora do
event loop. Falha ao agendar, encontrar intenção ou despachar não transforma compra
confirmada em falha HTTP, nem reverte documentos comerciais. O ACK comercial continua
200; falha de persistência comercial continua 503 e não agenda envio. Não há tentativa
externa de envio dentro do callback Firestore.

## Composição explícita — ainda não ativada

`app.main` agora possui lifespan que consulta opcionalmente
`app.state.purchase_welcome_trigger`. Não registra Admin nem altera CORS ou rotas.
Sem esse runtime instalado, lifespan e webhook não fazem consultas/envios de e-mail.
Importar módulos não compõe serviços, carrega segredo ou conecta a provedor.

`configure_purchase_welcome_trigger(app, firestore_client=..., transport=...,
 environ=..., env_file=...)` é o hook interno para uma futura inicialização
explicitamente autorizada, ANTES de servir a aplicação. Ele reutiliza o loader do
PASSO 94 e instala uma única composição. NÃO foi ligado automaticamente ao ambiente
real: o bootstrap autorizado ainda precisará chamar esse hook com cliente correto e
transporte real explícito. Variáveis sozinhas não instalam um runtime na entrada atual.
Essa separação impede que apenas um segredo presente no ambiente ative envio.

Preserva os campos obrigatórios:
- `PURCHASE_WELCOME_SEND_ENABLED=true` no processo (padrão false).
- `RESEND_API_KEY`, `PURCHASE_WELCOME_FROM`, `PURCHASE_WELCOME_WHATSAPP_URL` válidos.

Acrescenta:
- `PURCHASE_WELCOME_NOT_BEFORE`: obrigatório; instante ISO-8601 com T e fuso,
  representando o início autorizado. Usar um instante UTC fixo, registrado no
  procedimento operacional, não `now()` recalculado a cada boot.
- `PURCHASE_WELCOME_RECOVERY_ENABLED`: true/false, padrão false; habilita um lote
  na inicialização e chamadas internas controladas de recuperação.
- `PURCHASE_WELCOME_RECOVERY_BATCH_SIZE`: inteiro 1 a 20, padrão 5.

O corte não tem default. Não retrocedê-lo para alcançar histórico. Todas as
instâncias devem compartilhar o mesmo corte/política/HMAC aplicável. Antecipar ou
alterar o início é decisão operacional explícita, não uma migração automática.
Nenhum timestamp antigo foi alterado. Valores do processo prevalecem; `.env`, sem
interpolação, só é lido se o chamador fornecer seu caminho e já houver seleção
explícita de envio no processo. Não há credencial, número ou endereço real neste guia.

Configuração ausente retorna sem instalação; incompleta/inválida falha sanitizada
na composição. Ela não é pré-requisito do webhook. Quem integrar o hook futuramente
precisa tratar erro de configuração como e-mail desabilitado, preservando a entrada
pública, sem instalar uma composição parcial. O runtime mantém o adapter; fechar
`runtime.dispatcher.provider.close()` após terminar as tarefas, respeitando o ciclo
de vida do executor. O cliente Firestore compartilhado permanece do chamador.

## Corte e recuperação

A fonte durável é `transactional_emails`, não a BackgroundTask. Recuperação consulta
somente kind=purchase_welcome, status=pending e created_at >= início autorizado,
ordenados por created_at/ID, com limite de lote e timeout de consulta. Não varre toda
a coleção nem usa paginação ilimitada. O corte também é revalidado DENTRO da reserva
transacional; receber um ID diretamente não permite ao caminho automático ignorá-lo.

A inicialização agenda UM lote em uma thread, sem aguardar Resend para liberar health
ou webhook. Não há loop permanente. Encerramento gracioso aguarda esse lote finito;
encerramento forçado pode interrompê-lo. Reserva é transacional entre instâncias;
duas recuperações ou tarefa rápida e recuperação podem disputar, mas somente uma
reserva confirmada chama HTTP. Contenção/Firestore indisponível podem causar uma
falha segura, sem envio. Erros não são exibidos com documentos/PII/credenciais.
`recover_pending()` retorna apenas contadores processed/unavailable; processed conta
chamadas concluídas ao dispatcher, não comprovação de entrega de cada e-mail.

Consulta requer um índice composto compatível no Firestore real:

```json
{"collectionGroup":"transactional_emails","queryScope":"COLLECTION","fields":[
  {"fieldPath":"status","order":"ASCENDING"},
  {"fieldPath":"kind","order":"ASCENDING"},
  {"fieldPath":"created_at","order":"ASCENDING"}
]}
```

A ordenação final por __name__ acompanha a direção ascendente do índice. Confirmar
esse índice na operação futura; não foi criado/publicado. O Emulator aceitar a
consulta NÃO comprova índice em produção. Se faltar índice ou a consulta falhar,
o lote retorna indisponibilidade e não envia. Reserva também valida documentos e
IDs; corrupção detectada no lote interrompe-o de forma segura e exige inspeção,
podendo impedir avanço até saneamento autorizado. Não apaga nem corrige documentos.

Um runtime habilitado também pode executar `recover_pending()` internamente de modo
controlado no MESMO serviço, sem endpoint público. Cada chamada usa o mesmo limite.
Não foi criado gatilho de cron ou mecanismo que permita ao navegador disparar lotes.

## Reinício, suspensão e resultados incertos

- Interrompido antes da tarefa/reserva: intenção continua pending e elegível para
  um lote futuro, se posterior ao corte.
- Interrompido após reserva: in_progress NÃO é reaberto por tempo ou reinício.
- Resend aceita mas gravação falha: reserva continua protegida; reconciliar como
  documentado no PASSO 94. Nunca presumir ausência de envio.
- accepted e requires_review ficam fora da recuperação, inclusive após 24h.
- Rejeição, timeout e rede seguem para revisão pelo dispatcher; não voltam a pending.
- Intenção anterior ao corte não é enviada por tarefa rápida nem recuperação.

Não há exactly-once nem garantia de entrega. O limite de 24h do Resend não é
tratado como deduplicação permanente. Nada neste passo libera reenvio cego.

## Limites de automação sem nova infraestrutura

Um único lote ao boot não garante drenagem contínua: se o serviço não reiniciar
ou houver mais pending do que o lote, pode restar trabalho. Se Render suspender,
não há processamento durante suspensão. Enquanto o processo estiver ativo,
novos eventos podem usar a tarefa rápida; isso ainda não garante sobrevivência a
falha de processo. Reenvio do mesmo webhook não é usado como disparador de e-mail.

Sem wake-up/agendamento garantido na infraestrutura existente, NÃO podemos afirmar
recuperação automática eventual de todas as intenções. Foi preparado o mínimo
controlado: outbox durável, lote ao boot opt-in e chamada interna limitada. A operação
precisará acompanhar contadores/pendências e solicitar novas execuções controladas
quando necessário. Não foram contratados novos serviços para contornar a limitação.

## Primeiro envio real — ainda pendente

Faltam autorização explícita, início autorizado fixo, contato e remetente oficiais
verificados, chave de envio guardada fora do Git, índice/IAM e projeto/banco
confirmados, integração do hook no bootstrap autorizado com transporte real,
destinatário controlado e procedimento de reconciliação/observação. Não basta
`pending` existir ou configurar uma variável. Nada disso foi executado aqui.

## Testes isolados

Os novos testes cobrem seleção de evento/receipt, corte/configuração, falhas de
agendamento/Firestore, startup em background sem bloquear health, webhook confirmado
antes do gatilho, recuperação limitada, interrupção antes da tarefa, concorrência,
sem runtime e estados protegidos. Nos testes Emulator a consulta da outbox fica em
uma subcoleção de namespace UUID de teste, para NÃO selecionar, enviar pelo fake ou
alterar pendências do usuário no Chrome. Demais documentos têm UUIDs próprios;
a limpeza é exata, nunca global. Transporte sempre httpx.MockTransport, credenciais
anônimas no Emulator loopback demo. Nenhum dado de produção ou e-mail real é utilizado.

Resultados finais: **28 novos testes unitários** aprovados; suíte Backend completa
com **1543 testes e 52 subtestes aprovados**, zero falhas. **18 testes Emulator
aprovados**: 12 novos de gatilho/recuperação e 6 de regressão compra/despacho.
Na suíte unitária, 269 cenários Emulator foram desmarcados intencionalmente; só os
três arquivos isolados foram executados à parte. Um aviso preexistente do TestClient.
`git diff --check` sem problemas. Nenhuma instalação, publicação ou alteração externa.
