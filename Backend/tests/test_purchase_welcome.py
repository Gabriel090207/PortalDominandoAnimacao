"""Synthetic purchase/outbox/template integration; no real provider exists."""
import copy
from unittest.mock import Mock, patch
import pytest
from commerce_fake import Client, Transaction
from test_kirvano_commercial import payload
from test_kirvano_commerce_transaction import receive, docs, prepared, renewal_payload, cancellation_payload
from app.domain.welcome_email import WelcomeEmailIntent, welcome_intent_id, optional_customer_name
from app.services.purchase_welcome_email import (
    WelcomeEmailContact, WelcomeEmailConfigurationError, render_purchase_welcome,
)


def intent(client):
    return WelcomeEmailIntent.model_validate(next(iter(docs(client, 'transactional_emails').values())))


def test_purchase_customer_intent_atomic_and_duplicate():
    client=Client(); data=payload(); data['customer']['name']='  Cliente Sintético  '
    receive(client,data,False)
    assert client.data=={}
    receive(client,data)
    purchase=next(iter(docs(client,'purchases').values()))
    user_id=next(iter(docs(client,'users'))).split('/')[1]
    user=next(iter(docs(client,'users').values()))
    mail=intent(client)
    assert user['activation_status']=='pending' and user['display_name']=='Cliente Sintético'
    assert user['email_normalized']=='buyer@example.com'
    assert purchase['user_id']==mail.user_id==user_id
    assert mail.recipient=='buyer@example.com' and mail.status=='pending'
    assert mail.customer_name=='Cliente Sintético' and 'sent_at' not in mail.model_dump()
    assert list(docs(client,'transactional_emails'))==['transactional_emails/'+welcome_intent_id(mail.purchase_id)]
    before=copy.deepcopy(docs(client,'transactional_emails'))
    data['customer']['name']='Outro nome no reenvio'
    receive(client,data)
    assert docs(client,'transactional_emails')==before
    assert next(iter(docs(client,'users').values()))['display_name']=='Cliente Sintético'


def test_same_normalized_email_reuses_customer_preserves_name_and_states():
    client=Client();data=payload();receive(client,data)
    user=next(iter(docs(client,'users').values()));user['activation_status']='suspended'
    data['sale_id']='second-sale';data['customer'].update(email='BUYER@example.com',name='Cliente Sintético')
    receive(client,data)
    assert len(docs(client,'users'))==len(docs(client,'email_identities'))==1
    assert len(docs(client,'purchases'))==len(docs(client,'transactional_emails'))==2
    assert next(iter(docs(client,'users').values()))['activation_status']=='suspended'
    assert next(iter(docs(client,'users').values()))['display_name']=='Cliente Sintético'


def test_historical_purchase_is_not_backfilled():
    client=Client();receive(client,payload())
    for key in list(docs(client,'transactional_emails')):del client.data[key]
    receive(client,payload())
    assert not docs(client,'transactional_emails')


@pytest.mark.parametrize('event',['SALE_REFUNDED','SALE_CHARGEBACK','UNKNOWN','SUBSCRIPTION_RENEWED','SUBSCRIPTION_CANCELED'])
def test_non_sale_creates_no_welcome(event):
    client=Client();receive(client,payload())
    before=copy.deepcopy(docs(client,'transactional_emails'))
    data=renewal_payload() if event=='SUBSCRIPTION_RENEWED' else cancellation_payload() if event=='SUBSCRIPTION_CANCELED' else payload()
    data['event']=event;receive(client,data)
    assert docs(client,'transactional_emails')==before


@pytest.mark.parametrize('change',[('status','PENDING'),('event','UNKNOWN')])
def test_ineligible_sale_no_intent(change):
    client=Client();data=payload();data[change[0]]=change[1];receive(client,data)
    assert not docs(client,'purchases') and not docs(client,'transactional_emails')


def test_new_purchase_with_orphan_intent_aborts_without_overwrite():
    client=Client();data=payload();candidate=prepared(data)[1].candidate
    client.data['transactional_emails/'+welcome_intent_id(candidate.purchase_id)]={'status':'pending'}
    before=copy.deepcopy(client.data)
    with pytest.raises(RuntimeError,match='Inconsistent post-purchase intent'):receive(client,data)
    assert client.data==before


def test_failure_buffering_intent_does_not_commit_purchase():
    client=Client();tx=Transaction(client);original=tx.create
    def create(ref,data):
        if ref.path.startswith('transactional_emails/'):raise RuntimeError('synthetic persistence failure')
        original(ref,data)
    tx.create=create
    from app.persistence.kirvano_commerce_repository import commercial_transaction
    with pytest.raises(RuntimeError):commercial_transaction(tx,client,*prepared(payload()),'synthetic-user')
    assert client.data=={}


def test_possible_commit_followed_by_failure_reconciles_without_new_intent():
    # Models a lost acknowledgement, not a guarantee that network failures imply commit.
    client=Client();receive(client,payload())
    before=copy.deepcopy(docs(client,'transactional_emails'))
    receive(client,payload())
    assert docs(client,'transactional_emails')==before and len(docs(client,'purchases'))==1


@pytest.mark.parametrize('value',[None,'',42,'x'*201,'Unsafe\nName','Unsafe\x00Name'])
def test_optional_name_rejects_unusable_metadata(value):
    assert optional_customer_name(value) is None


@pytest.mark.parametrize('name',[None,'Cliente Sintético','<img src=x onerror=alert(1)>'])
def test_render_html_text_and_fake_provider_only(name,caplog):
    client=Client();data=payload();data['customer']['name']=name;receive(client,data)
    record=intent(client);message=render_purchase_welcome(record,contact=WelcomeEmailContact('https://wa.me/15555550123'))
    assert 'liberado manualmente' in message.text
    assert 'e-mail utilizado na compra' in message.text
    assert 'Solicitar liberação no WhatsApp' in message.html
    assert all(color in message.html for color in ['#050913','#141b2d','#00e0ff','#33e8ff','#a0b3d0','#ffffff'])
    assert '<table role="presentation"' in message.html and 'max-width:600px' in message.html
    assert record.recipient not in message.html and record.recipient not in message.text
    assert 'buyer%40' not in message.html and '<img' not in message.html
    if name and '<' in name:assert '&lt;img' in message.html
    fake=Mock();fake.send.return_value='synthetic-provider-id'
    result=fake.send(message,idempotency_key=welcome_intent_id(record.purchase_id))
    assert result=='synthetic-provider-id' and intent(client).status=='pending'
    assert record.recipient not in repr(message)+repr(record)+caplog.text


@pytest.mark.parametrize('url',[None,'','http://wa.me/15555550123','https://evil.example/15555550123',
    'https://wa.me/15555550123?text=private','https://wa.me/15555550123#private','https://wa.me/not-number'])
def test_missing_invalid_contact_fails_sanitized(url):
    with pytest.raises(WelcomeEmailConfigurationError) as caught:WelcomeEmailContact(url)
    assert str(caught.value)=='Purchase welcome email configuration unavailable.'


def test_http_invalid_token_and_persistence_error_no_leaks(caplog):
    from fastapi.testclient import TestClient
    from app.main import app
    env={'KIRVANO_WEBHOOK_TOKEN':'synthetic-only-token'}
    with patch.dict('os.environ',env,clear=True),patch('app.api.kirvano.load_dotenv'),patch('app.api.kirvano.register_event') as process:
        with TestClient(app) as http:
            assert http.post('/webhooks/kirvano',headers={'security-token':'wrong'},json=payload()).status_code==401
            process.assert_not_called()
            process.side_effect=RuntimeError('synthetic-only-private')
            response=http.post('/webhooks/kirvano',headers={'security-token':env['KIRVANO_WEBHOOK_TOKEN']},json=payload())
            assert response.status_code==503
            assert 'synthetic-only-private' not in response.text+caplog.text
            assert 'synthetic-only-token' not in response.text+caplog.text
