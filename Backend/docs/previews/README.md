# Prévia local do e-mail de boas-vindas — PASSO 97.8

Abra `boas-vindas.html` diretamente no Chrome (⌘O e selecione o arquivo).
Não precisa iniciar servidor, autenticar ou conectar ao Resend. Use a largura
normal e uma janela estreita para avaliar apresentação em desktop e celular.
Não foi realizada homologação em clientes reais Gmail/Outlook.

Para regenerar a partir da raiz do projeto:

```sh
cd Backend
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app.tools.preview_purchase_welcome
```

O gerador usa o MESMO `render_purchase_welcome` do dispatcher, com nome
`Cliente Exemplo`, e-mail sintético e IDs sintéticos em memória. Depois neutraliza
mecanicamente todos os links WhatsApp para `#whatsapp-preview`, identifica a
prévia no título e adiciona a âncora no body. Não contém um segundo layout, não
lê `.env`/RESEND_API_KEY, não cria intenção nem toca em Firestore ou no provedor.
O teste de paridade confirma que o arquivo está atualizado com o renderizador.

O template real fica em `Backend/app/templates/purchase_welcome.html`. Usa tabelas,
estilos inline, fontes locais seguras e largura máxima 600px. O cabeçalho tem
fallback ciano sólido para clientes que ignoram gradiente; há botão VML condicional
para Outlook e link alternativo. Não usa imagens, logo inventado, JavaScript ou
fontes remotas. Nome e URL são escapados; a validação wa.me permanece a existente.
No envio real, o contato chega da configuração PURCHASE_WELCOME_WHATSAPP_URL pelo
mesmo objeto de contato do dispatcher, sem número fixado no template.

O texto confirma compra e cadastro, mas informa que a equipe libera o acesso após
contato. Não inclui senha, código, prazo ou promessa de ativação automática.
Snapshots já reservados continuam armazenados no Firestore pelo fluxo existente;
esta atualização visual não os reabre nem os reenvia.

Validação desta etapa: 91 testes direcionados aprovados, com mocks e transporte
HTTP fake. Nenhuma mensagem real foi enviada. Não foi necessário acessar Emulator,
Render, DNS ou banco real; não houve commit ou push.
