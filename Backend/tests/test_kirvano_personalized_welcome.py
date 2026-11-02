"""Synthetic mapping of customer.name to stored intent and approved renderer."""
from html import escape
import pytest
from commerce_fake import Client
from test_kirvano_commercial import payload
from test_kirvano_commerce_transaction import receive, docs
from app.domain.welcome_email import WelcomeEmailIntent
from app.services.purchase_welcome_email import render_purchase_welcome
from test_welcome_dispatch import configuration


@pytest.mark.parametrize('name,expected',[
    ('  Gabriel Oliveira  ','Gabriel Oliveira'),(None,None),('Gabriel\nOliveira',None),
    ('x'*201,None),('<b>Gabriel Oliveira</b>','<b>Gabriel Oliveira</b>'),
])
def test_customer_name_persisted_escaped_or_generic_fallback(name,expected):
    client=Client();data=payload();data['customer']['name']=name;receive(client,data)
    intent=WelcomeEmailIntent.model_validate(next(iter(docs(client,'transactional_emails').values())))
    user=next(iter(docs(client,'users').values()))
    assert intent.customer_name==expected and user.get('display_name')==expected
    message=render_purchase_welcome(intent,contact=configuration().contact)
    greeting=f'Olá, {expected}!' if expected else 'Olá!'
    assert escape(greeting) in message.html and greeting in message.text
    assert '<b>Gabriel Oliveira</b>' not in message.html and 'Cliente Exemplo' not in message.html
    assert user['activation_status']=='pending'


def test_existing_name_is_preserved_while_new_intent_uses_purchase_name():
    client=Client();data=payload();data['customer']['name']='Nome cadastrado';receive(client,data)
    data['sale_id']='synthetic-another-personalized-sale';data['customer']['name']='Gabriel Oliveira';receive(client,data)
    assert len(docs(client,'users'))==1
    assert next(iter(docs(client,'users').values()))['display_name']=='Nome cadastrado'
    assert any(d['customer_name']=='Gabriel Oliveira' for d in docs(client,'transactional_emails').values())
