"""Template content, link safety and preview parity. No config/provider access."""
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from unittest.mock import Mock
import pytest
from app.domain.welcome_email import WelcomeEmailIntent
from app.services.purchase_welcome_email import WelcomeEmailContact, render_purchase_welcome
from app.tools import preview_purchase_welcome as preview


class Document(HTMLParser):
    def __init__(self,html):
        super().__init__();self.links=[];self.tags=[];self.feed(html)
    def handle_starttag(self,tag,attrs):
        self.tags.append(tag)
        if tag=='a':self.links.append(dict(attrs).get('href'))


def message(name='Cliente Exemplo',number='15555550123'):
    intent=WelcomeEmailIntent(purchase_id='0'*64,user_id='preview-customer',origin_event_id='1'*64,
        recipient='preview@example.com',customer_name=name,created_at=datetime(2026,1,1,tzinfo=timezone.utc))
    contact=WelcomeEmailContact('https://wa.me/'+number)
    return render_purchase_welcome(intent,contact=contact),contact


@pytest.mark.parametrize('name',['Cliente Exemplo',None,'<script>alert("x")</script> & $example'])
def test_content_name_and_escape(name):
    mail,_=message(name)
    assert mail.subject=='Compra aprovada! Bem-vindo ao Dominando Animação'
    greeting='Olá, '+name+'!' if name else 'Olá!'
    assert greeting in mail.text and escape(greeting) in mail.html
    assert '<script' not in mail.html and 'preview@example.com' not in mail.html+mail.text
    for text in ['Sua compra foi aprovada com sucesso!', 'Estamos muito felizes em ter você com a gente.',
        'Seu cadastro já foi registrado em nosso sistema', 'Vamos ativar seu acesso ao portal?',
        'A liberação é realizada pela nossa equipe.', 'não é necessário fazer uma nova solicitação.',
        'Nos vemos em breve!', 'Equipe Dominando Animação',
        'Este é um e-mail automático enviado após a confirmação da sua compra.']:
        assert text in mail.html and text in mail.text
    assert 'Sua compra foi confirmada. Saiba como solicitar a ativação do seu acesso.' in mail.html
    assert 'mso-hide:all' in mail.html


@pytest.mark.parametrize('number',['15555550123','15555550124'])
def test_dynamic_whatsapp_button_and_fallback(number):
    mail,contact=message(number=number);doc=Document(mail.html)
    assert doc.links==[contact.activation_url(),contact.activation_url()]
    assert 'Solicitar ativação no WhatsApp' in mail.html+mail.text
    assert 'acesse o WhatsApp por este link' in mail.html
    assert contact.activation_url() in mail.text
    assert 'Cliente' not in contact.activation_url() and 'example.com' not in contact.activation_url()
    assert not {'script','iframe','form','img'} & set(doc.tags)
    assert 'v:roundrect' in mail.html and 'bgcolor="#25D366"' in mail.html
    assert 'background-color:#00bcd4' in mail.html and 'linear-gradient' in mail.html


def test_preview_is_current_renderer_with_only_neutralized_links():
    mail,contact=message()
    expected=mail.html.replace(escape(contact.activation_url(),quote=True),'#whatsapp-preview').replace(
        '<body ', '<body id="whatsapp-preview" ').replace('<title>','<title>Prévia local — ')
    html=preview.preview_html()
    assert html==expected
    assert preview.OUTPUT.read_text(encoding='utf-8')==html
    assert Document(html).links==['#whatsapp-preview','#whatsapp-preview']
    assert 'wa.me' not in html and '15555550123' not in html
    assert 'Cliente Exemplo' in html and 'max-width:600px' in html


def test_preview_generator_never_loads_env_or_provider(monkeypatch,tmp_path):
    forbidden=Mock(side_effect=AssertionError('No real integrations in preview'))
    monkeypatch.setattr('dotenv.load_dotenv',forbidden)
    monkeypatch.setattr('dotenv.dotenv_values',forbidden)
    monkeypatch.setattr('httpx.Client',forbidden)
    monkeypatch.setattr('firebase_admin.initialize_app',forbidden)
    target=tmp_path/'boas-vindas.html';monkeypatch.setattr(preview,'OUTPUT',target)
    preview.main()
    assert target.read_text(encoding='utf-8')==preview.preview_html()
    forbidden.assert_not_called()
