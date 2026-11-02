"""Local HTML artifact only. Does not import config, Firebase, provider or .env."""
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from app.domain.welcome_email import WelcomeEmailIntent
from app.services.purchase_welcome_email import WelcomeEmailContact, render_purchase_welcome

OUTPUT = Path(__file__).resolve().parents[2] / 'docs' / 'previews' / 'boas-vindas.html'


def preview_html():
    intent = WelcomeEmailIntent(purchase_id='0'*64,user_id='preview-customer',origin_event_id='1'*64,
        recipient='preview@example.com',customer_name='Cliente Exemplo',
        created_at=datetime(2026,1,1,tzinfo=timezone.utc))
    contact = WelcomeEmailContact('https://wa.me/15555550123')
    message = render_purchase_welcome(intent,contact=contact)
    # Mechanical link neutralization ONLY: production layout is never copied.
    return message.html.replace(escape(contact.activation_url(),quote=True),'#whatsapp-preview').replace(
        '<body ', '<body id="whatsapp-preview" ').replace('<title>', '<title>Prévia local — ')


def main():
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(preview_html(),encoding='utf-8')
    print('Prévia local criada em Backend/docs/previews/boas-vindas.html; links WhatsApp desativados.')


if __name__ == '__main__':
    main()
