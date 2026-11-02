"""Pure rendering + future provider port. No credentials, network or dispatcher."""
from dataclasses import dataclass
from html import escape
from pathlib import Path
from string import Template
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
    subject = 'Compra aprovada! Bem-vindo ao Dominando Animação'
    preheader = 'Sua compra foi confirmada. Saiba como solicitar a ativação do seu acesso.'
    text = '\n\n'.join([
        greeting,
        'Sua compra foi aprovada com sucesso!',
        'Seja muito bem-vindo ao Dominando Animação!\nEstamos muito felizes em ter você com a gente.',
        'Seu cadastro já foi registrado em nosso sistema e agora falta apenas um passo para começar sua jornada conosco.',
        'Vamos ativar seu acesso ao portal?',
        'A liberação é realizada pela nossa equipe.',
        'Para solicitar sua ativação, clique no botão abaixo e inicie uma conversa pelo WhatsApp.',
        'Solicitar ativação no WhatsApp: ' + url,
        'Se o botão não abrir, acesse o WhatsApp por este link: ' + url,
        'Nossa equipe dará continuidade à liberação do seu acesso após o contato.',
        'Se você já conversou conosco e solicitou a ativação, não é necessário fazer uma nova solicitação.',
        'Nos vemos em breve!\nEquipe Dominando Animação',
        'Este é um e-mail automático enviado após a confirmação da sua compra.',
    ])
    template = Path(__file__).resolve().parents[1] / 'templates' / 'purchase_welcome.html'
    html = Template(template.read_text(encoding='utf-8')).substitute(
        subject=escape(subject), preheader=escape(preheader),
        greeting=escape(greeting), whatsapp_url=escape(url, quote=True))
    return RenderedWelcomeEmail(intent.recipient, subject, html, text)
