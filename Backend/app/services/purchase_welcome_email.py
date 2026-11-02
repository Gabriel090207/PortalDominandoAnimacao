"""Pure rendering + future provider port. No credentials, network or dispatcher."""
from dataclasses import dataclass
from html import escape
import re
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from app.domain.welcome_email import WelcomeEmailIntent
from app.domain.welcome_dispatch import WelcomeProviderResult


class WelcomeEmailConfigurationError(RuntimeError):
    def __init__(self):
        super().__init__('Purchase welcome email configuration unavailable.')


@dataclass(frozen=True, repr=False)
class WelcomeEmailContact:
    whatsapp_url: str

    def __post_init__(self):
        # Explicit official wa.me address only. No supplied queries/PII/redirects.
        try:
            if not isinstance(self.whatsapp_url, str):
                raise ValueError
            url = urlsplit(self.whatsapp_url)
            if not re.fullmatch(r'https://wa\.me/[1-9][0-9]{7,14}', self.whatsapp_url):
                raise ValueError
            if url.query or url.fragment:
                raise ValueError
        except Exception:
            raise WelcomeEmailConfigurationError() from None

    def activation_url(self):
        return self.whatsapp_url + '?' + urlencode({'text':
            'Olá! Gostaria de solicitar a liberação do meu acesso ao Dominando Animação.'})


@dataclass(frozen=True, repr=False)
class RenderedWelcomeEmail:
    recipient: str
    subject: str
    html: str
    text: str


class WelcomeEmailProvider(Protocol):
    """Adapters use the immutable intent ID as idempotency key.

    Provider acceptance is not proof of delivery. Dispatch is explicit; no
    automatic trigger or retry is enabled.
    """
    def send(self, message: RenderedWelcomeEmail, *, sender: str,
             idempotency_key: str) -> WelcomeProviderResult: ...


def render_purchase_welcome(intent: WelcomeEmailIntent, *, contact: WelcomeEmailContact):
    if not isinstance(contact, WelcomeEmailContact):
        raise WelcomeEmailConfigurationError()
    # Revalidate even models constructed without Pydantic validation.
    try:
        intent = WelcomeEmailIntent.model_validate(intent.model_dump())
    except Exception:
        raise ValueError('Invalid purchase welcome intent.') from None
    greeting = f'Olá, {intent.customer_name}!' if intent.customer_name else 'Olá!'
    url = contact.activation_url()
    subject = 'Compra aprovada — boas-vindas ao Dominando Animação'
    paragraphs = [
        'Sua compra foi aprovada. Boas-vindas ao Dominando Animação!',
        'Seu acesso ao portal precisa ser liberado manualmente pelo administrador.',
        'Para solicitar a liberação, entre em contato pelo WhatsApp e informe o e-mail utilizado na compra.',
    ]
    text = '\n\n'.join([greeting, *paragraphs,
        'Solicitar liberação no WhatsApp: ' + url, 'Dominando Animação'])
    html = '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Boas-vindas ao Dominando Animação</title>
<style>@media screen and (max-width:600px){.card{padding:24px!important}}
.activation:hover{background-color:#33e8ff!important}</style></head>
<body style="margin:0;padding:0;background-color:#050913;color:#ffffff;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#050913"><tr><td align="center" style="padding:32px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background-color:#141b2d;border:1px solid #26344c;border-radius:16px">
<tr><td class="card" style="padding:40px">
<p style="color:#00e0ff;font-size:13px;letter-spacing:2px;font-weight:bold">DOMINANDO ANIMAÇÃO</p>
<h1 style="color:#ffffff;font-size:26px;line-height:1.3">''' + escape(greeting) + '</h1>'
    html += ''.join('<p style="color:#a0b3d0;font-size:16px;line-height:1.65">' + escape(p) + '</p>' for p in paragraphs)
    html += '<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="padding:16px 0"><a class="activation" href="' + escape(url, quote=True) + '''" style="display:inline-block;background-color:#00e0ff;color:#050913;padding:16px 20px;border-radius:8px;font-size:16px;line-height:1.4;text-decoration:none;font-weight:bold">Solicitar liberação no WhatsApp</a></td></tr></table>
<p style="color:#a0b3d0;font-size:14px;line-height:1.6">Dominando Animação<br>Conte com a nossa equipe para começar.</p>
</td></tr></table></td></tr></table></body></html>'''
    return RenderedWelcomeEmail(intent.recipient, subject, html, text)
