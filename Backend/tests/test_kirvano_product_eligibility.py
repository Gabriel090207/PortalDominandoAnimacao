"""Product-only eligibility; offers stay bound to their original subscription."""
import copy
import pytest
from commerce_fake import Client
from test_kirvano_commercial import payload, classify, cancellation_payload
from test_kirvano_commerce_transaction import receive, docs, root, renewal_payload, event_root
from app.services.kirvano_commercial_service import AUTHORIZED_PRODUCT_ID, AUTHORIZED_OFFER_ID
from app.domain.kirvano_commercial import CommercialClassification

NEW_OFFER='synthetic-monthly-one-real-offer'


@pytest.mark.parametrize('offer',[AUTHORIZED_OFFER_ID,NEW_OFFER,'another-synthetic-offer'])
@pytest.mark.parametrize('event',['SALE_APPROVED','SUBSCRIPTION_RENEWED','SUBSCRIPTION_CANCELED'])
def test_all_valid_offers_match_only_authorized_monthly_product(offer,event):
    data=cancellation_payload() if event=='SUBSCRIPTION_CANCELED' else payload()
    data['event']=event;data['products'][0]['offer_id']=offer;data['total_price']='R$ 1,00'
    result=classify(data)
    assert result.classification==CommercialClassification.ELIGIBLE
    assert result.candidate.product_id==AUTHORIZED_PRODUCT_ID and result.candidate.offer_id==offer


@pytest.mark.parametrize('offer',[None,'','invalid offer','x'*129,False,123])
def test_offer_must_still_be_present_and_valid(offer):
    data=payload();data['products'][0]['offer_id']=offer
    assert classify(data).candidate is None


@pytest.mark.parametrize('change',[('type','ONE_TIME'),('frequency','YEARLY'),('product','other'),('bump',True)])
def test_no_silent_expansion_of_other_business_rules(change):
    data=payload();data['products'][0]['offer_id']=NEW_OFFER
    if change[0]=='frequency':data['plan']['charge_frequency']=change[1]
    elif change[0]=='product':data['products'][0]['id']=change[1]
    elif change[0]=='bump':data['products'][0]['is_order_bump']=change[1]
    else:data['type']=change[1]
    assert classify(data).candidate is None


def test_two_different_offers_in_same_product_are_ambiguous_not_first_wins():
    data=payload();data['products'].append({**data['products'][0],'offer_id':NEW_OFFER})
    assert classify(data).candidate is None


def test_new_offer_persists_and_renewal_cancel_do_not_create_welcome():
    client=Client();data=payload();data['products'][0]['offer_id']=NEW_OFFER
    data['total_price']='R$ 1,00';data['customer']['name']='Gabriel Oliveira'
    receive(client,data);before=copy.deepcopy(docs(client,'transactional_emails'))
    receive(client,data)
    assert len(docs(client,'purchases'))==len(before)==1 and docs(client,'transactional_emails')==before
    assert next(iter(docs(client,'users').values()))['activation_status']=='pending'
    assert next(iter(before.values()))['customer_name']=='Gabriel Oliveira'
    for name in ('purchases','subscriptions'):assert next(iter(docs(client,name).values()))['offer_id']==NEW_OFFER
    renewed=renewal_payload();renewed['products'][0]['offer_id']=NEW_OFFER;receive(client,renewed)
    assert len(docs(client,'purchases'))==2 and docs(client,'transactional_emails')==before
    cancelled=cancellation_payload();cancelled['products'][0]['offer_id']=NEW_OFFER;receive(client,cancelled)
    assert next(iter(docs(client,'subscriptions').values()))['status']=='canceled'
    for event in ('SALE_REFUNDED','SALE_CHARGEBACK'):
        negative={**data,'event':event,'status':event.removeprefix('SALE_')};receive(client,negative)
        assert event_root(client,negative)['business_status']=='review_required'
    assert docs(client,'transactional_emails')==before


@pytest.mark.parametrize('event',['SUBSCRIPTION_RENEWED','SUBSCRIPTION_CANCELED'])
def test_other_offer_cannot_rebind_existing_subscription(event):
    client=Client();receive(client,payload())
    changed=renewal_payload() if event=='SUBSCRIPTION_RENEWED' else cancellation_payload()
    changed['products'][0]['offer_id']=NEW_OFFER
    before=copy.deepcopy({k:v for k,v in client.data.items() if not k.startswith('kirvano_events/')})
    receive(client,changed)
    assert event_root(client,changed)['business_status']=='review_required'
    assert {k:v for k,v in client.data.items() if not k.startswith('kirvano_events/')}==before
