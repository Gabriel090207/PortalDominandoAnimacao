# PASSO 97.26 — envio geral preparado, desativado por padrão

Este documento sucede o gate somente de teste do PASSO 97.22. O comando público
continua `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Não exige outro serviço.
Nenhuma configuração externa é alterada pelo código ou pelo commit.

## Configuração para ativação posterior pelo operador

O bootstrap público lê somente o ambiente efetivo do processo, não o arquivo .env
como fallback para as configurações de envio. Configurar no serviço existente:

- `PURCHASE_WELCOME_SEND_ENABLED=true`: autorização explícita; ausente/false não
  inicializa o envio. Manter **false** até a decisão operacional de ativação.
- `PURCHASE_WELCOME_AUDIENCE_MODE=all`: qualquer destinatário válido de uma compra
  comercialmente elegível. Não exige TEST_RECIPIENT nem TEST_AUTHORIZED e ignora
  filtros de teste antigos. O modo `test` preserva ambas as exigências anteriores.
- `PURCHASE_WELCOME_NOT_BEFORE`: novo instante ISO-8601 com `T` e fuso explícito,
  escolhido antes da ativação geral. Não reutilizar automaticamente o corte de teste.
- `PURCHASE_WELCOME_RECOVERY_ENABLED=false`: obrigatório neste bootstrap público.
- `RESEND_API_KEY`: segredo privado com permissão de envio no domínio verificado.
- `PURCHASE_WELCOME_FROM=boasvindas@envios.dominandoanimacao.com`: mailbox simples,
  sem nome de exibição; domínio/remetente precisam estar autorizados no Resend.
- `PURCHASE_WELCOME_WHATSAPP_URL`: URL oficial HTTPS wa.me já validada, sem divulgar
  número em logs/documentação pública. Não substituí-la por exemplo fictício.
- `FIREBASE_PROJECT_ID=portaldominandoanimacao-db`: projeto esperado; banco `(default)`.

Preservar credenciais Firebase existentes e segredos de autenticação comercial,
`KIRVANO_WEBHOOK_TIMEZONE` correto e `EMAIL_IDENTITY_HMAC_SECRET` existente.
Não gerar novos segredos ou alterar identidades para ativar envio.

## Produto, periodicidade e contrato

Somente produto `0c5f6369-5a8a-467c-ba81-61cde05b7917`, com um único item principal
não order bump identificável, aceita ofertas diferentes com offer_id válido.
`type=RECURRING`, status/evento e número positivo inteiro de cobrança permanecem
obrigatórios. `MONTHLY` mapeia para intervalo interno `monthly`; `ANNUALLY` para
`yearly`. Não aceitar `YEARLY` como alias externo. A persistência e a comparação
de vínculos em renovação/cancelamento usam o mesmo mapeamento, preservando produto,
oferta, identidade e intervalo originais. Uma mudança de frequência vai para revisão.

Trimestral/semestral permanecem em revisão: não encontramos valores exatos do
campo `plan.charge_frequency` comprovados por contrato oficial. Enums internos
ou nomes em inglês presumidos não são evidência de labels externos.

Fontes oficiais consultadas:
- https://help.kirvano.com/hc/pt-br/articles/1765385505-configurando-integracao-via-webhook
- https://help.kirvano.com/hc/central-de-ajuda/articles/1775656489-ex

Os exemplos anuais mostram ANNUALLY, mas omitem `plan.charge_number`. O Backend
exige esse campo para a identidade da cobrança e deduplicação; sua ausência gera
revisão, sem inventar número 1 ou usar parcelas como número da renovação. Confirmar
com a Kirvano/payload autenticado sanitizado antes de prometer sucesso do teste real.
Isso não impede testar uma compra mensal que cumpra o contrato atual.

Datas vêm de `payment.finished_at` e `plan.next_charge_date`, convertidas com o fuso
configurado. Não calculamos 30/365 dias no código comercial nem mudamos direitos de
assinaturas existentes. Anual recebe suporte ao contrato validado, não inferência
pela diferença de datas. Renovação não cria boas-vindas; cancelamento só aplica sua
regra existente; atraso/reembolso/chargeback permanecem em revisão, sem envio ou
novos efeitos financeiros.

## Corte e ativação segura

1. Manter envio e recuperação false; confirmar revisão implantada antes do teste.
2. Confirmar projeto/banco da credencial e IAM do serviço existente: Firestore API
   habilitada, acesso transacional de leitura e criação/atualização dos documentos
   comerciais e transactional_emails (por exemplo, papel Datastore User apropriado,
   conforme política IAM do projeto). Não usar papel de administrador só para enviar.
   Validação local de metadados não comprova IAM real; nenhuma consulta real é feita
   nesta etapa. Emulator/test flags devem estar ausentes; projetos conflitantes falham.
3. Definir um novo instante de corte explícito com fuso, próximo à janela de ativação,
   antes da compra. Conferir UTC/fuso e relógio; não retroagir para escoar pendências.
4. Configurar all e demais valores; habilitar SEND_ENABLED somente por ação explícita
   posterior. Reinicialização/deploy deve carregar a configuração. Health 200 sozinho
   não comprova que o runtime de e-mail foi instalado: configuração inválida desabilita
   só o e-mail e mantém webhook/health funcionando.
5. Só então efetuar compra mensal autorizada após o corte, com charge_number válido.
   Verificar compra, comprador pending, intenção e resultado no acesso interno confiável
   e painel Resend. Aceitação não comprova entrega na caixa de entrada.
6. Se ocorrer falha/incerteza, não apagar reservas nem repetir compra/webhook para
   forçar e-mail. Desativar flag se necessário e investigar pelo estado sanitizado.

A reserva verifica timestamps da intenção e compra, e o pagamento efetivo valid_from,
contra o corte, além de pagamento não futuro. Compras anteriores não recebem e-mail
mesmo reprocessadas agora. Nenhuma varredura retroativa, polling ou recuperação é
habilitada. Intenções antigas permanecem sem despacho automático.

## Garantias e limites

A audiência é aplicada dentro da reserva transacional e não só no agendamento.
Idempotência, snapshot, fencing por tentativa e revisão de resultados incertos são
preservados. Resend falho não desfaz compra nem ativa cliente; duplicatas não enviam
novamente. HTML aprovado e WhatsApp oficial continuam pelo renderizador existente.

BackgroundTasks não é fila durável. Queda/redeploy/suspensão após commit pode deixar
intenção pending sem envio com recuperação desligada. Não garantimos entrega eventual
ou exactly-once externo. Falhas de confirmação ficam para revisão sem retry cego.

Os testes usam somente fakes e Emulator demo com documentos UUID próprios e limpeza
restrita. Não enviam e-mail, não consultam produção e não modificam Render/.env.
