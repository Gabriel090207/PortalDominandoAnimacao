"""Pure synthetic commercial contracts; no real Firestore."""
import copy
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from unittest.mock import patch
from app.domain.kirvano_commercial import CommercialClassification as State, CommercialReason as Reason
from app.services.kirvano_commercial_service import AUTHORIZED_PRODUCT_ID, AUTHORIZED_OFFER_ID, classify_commercial_event
from app.services.kirvano_event_service import normalize_event


def payload():
    return {'event':'SALE_APPROVED','status':'APPROVED','type':'RECURRING','sale_id':'synthetic-sale',
            'customer':{'email':' Buyer@Example.com '},
            'plan':{'charge_number':1,'charge_frequency':'MONTHLY','next_charge_date':'2026-11-05 12:00:00'},
            'payment':{'finished_at':'2026-10-05 12:00:00'},
            'products':[{'id':AUTHORIZED_PRODUCT_ID,'offer_id':AUTHORIZED_OFFER_ID,'is_order_bump':False}]}


def classify(data, zone='America/Sao_Paulo'):
    return classify_commercial_event(data, timezone_name=zone)


class CommercialTests(unittest.TestCase):
    def test_valid_utc_contract(self):
        result=classify(payload()); candidate=result.candidate
        self.assertEqual(result.classification,State.ELIGIBLE)
        self.assertEqual(result.reason_codes,())
        self.assertEqual(candidate.email_normalized,'buyer@example.com')
        self.assertNotIn(candidate.email_normalized,repr(result))
        self.assertEqual(candidate.valid_from,datetime(2026,10,5,15,tzinfo=timezone.utc))
        self.assertEqual(candidate.valid_until,datetime(2026,11,5,15,tzinfo=timezone.utc))
        self.assertEqual((candidate.schema_version,candidate.identity_version),(1,1))

    def test_required_fields_and_types(self):
        cases=[('customer.email',None,Reason.INVALID_EMAIL),('customer.email','bad',Reason.INVALID_EMAIL),
               ('sale_id',None,Reason.INVALID_SALE_ID),('sale_id','invalid id',Reason.INVALID_SALE_ID),
               *[('plan.charge_number',v,Reason.INVALID_CHARGE_NUMBER) for v in [None,'1',True,0,-1,1.0]],
               ('plan.charge_frequency','YEARLY',Reason.FREQUENCY_NOT_AUTHORIZED),
               ('type','ONE_TIME',Reason.TYPE_NOT_RECURRING),('status','PENDING',Reason.STATUS_NOT_APPROVED),
               *[('event',v,Reason.EVENT_NOT_AUTHORIZED) for v in ['UNKNOWN','SUBSCRIPTION_CANCELED','SALE_REFUNDED','SALE_CHARGEBACK']],
               *[(field,v,reason) for field,reason in [('payment.finished_at',Reason.INVALID_PERIOD_START),('plan.next_charge_date',Reason.INVALID_PERIOD_END)] for v in [None,'bad','2026-10-05T12:00:00','2026-10-05 12:00:00+00:00','2026-2-05 12:00:00','2026-02-30 12:00:00']]]
        for path,value,reason in cases:
            with self.subTest(path=path,value=value):
                data=payload();target=data;keys=path.split('.')
                for key in keys[:-1]:target=target[key]
                if value is None:target.pop(keys[-1])
                else:target[keys[-1]]=value
                result=classify(data)
                self.assertEqual(result.classification,State.REVIEW_REQUIRED)
                self.assertIsNone(result.candidate)
                self.assertIn(reason,result.reason_codes)

    def test_product_matching(self):
        good=payload()['products'][0]
        for products in [[{**good,'id':'other'}],[{**good,'offer_id':'other'}],
                         [{**good,'id':'other'},{**good,'offer_id':'other'}],
                         [{**good,'is_order_bump':True}],[{**good,'is_order_bump':0}],
                         [{'id':good['id'],'offer_id':good['offer_id']}],[]]:
            data=payload();data['products']=products
            self.assertEqual(classify(data).classification,State.REVIEW_REQUIRED)
        data=payload();data['products'].append(copy.deepcopy(good))
        self.assertIn(Reason.MULTIPLE_AUTHORIZED_PRODUCTS,classify(data).reason_codes)

    def test_dates_and_timezone(self):
        for date in ['2026-10-05 12:00:00','2026-10-04 12:00:00']:
            data=payload();data['plan']['next_charge_date']=date
            self.assertIn(Reason.INVALID_PERIOD_ORDER,classify(data).reason_codes)
        for zone in [None,'','Invalid/Zone','/etc/passwd',True]:
            self.assertIn(Reason.INVALID_TIMEZONE,classify(payload(),zone).reason_codes)
        for date in ['2026-03-08 02:30:00','2026-11-01 01:30:00']:
            data=payload();data['payment']['finished_at']=date
            self.assertIn(Reason.INVALID_PERIOD_START,classify(data,'America/New_York').reason_codes)

    def test_invalid_structures(self):
        for value in [None,[],'payload',1]:
            self.assertIn(Reason.INVALID_STRUCTURE,classify(value).reason_codes)
        for key in ['customer','plan','payment','products']:
            for value in [None,'invalid',1]:
                data=payload();data[key]=value
                self.assertEqual(classify(data).classification,State.REVIEW_REQUIRED)
        data=payload();data['products'].append('invalid')
        self.assertIn(Reason.INBOX_VALIDATION_FAILED,classify(data).reason_codes)

    def test_allowlist_no_io_no_mutation_no_inbox_changes(self):
        data=payload();before=copy.deepcopy(data)
        with patch('app.services.firebase_service.get_firestore_client',side_effect=AssertionError('No Firestore')),patch('builtins.print') as printer:
            expected=classify(data)
            self.assertEqual(data,before)
            fingerprint=normalize_event(data)
            data['customer'].update(name='SYNTHETIC_PRIVATE_NAME',phone='SYNTHETIC_PRIVATE_PHONE')
            data['security-token']='SYNTHETIC_SECRET';data['extra']='SYNTHETIC_PRIVATE_EXTRA'
            result=classify(data)
            self.assertEqual(result,expected)
            self.assertNotIn('SYNTHETIC_',str(asdict(result)))
            self.assertEqual(normalize_event(data),fingerprint)
            printer.assert_not_called()

    def test_deterministic_id_components(self):
        base=classify(payload()).candidate
        self.assertEqual(base,classify(payload()).candidate)
        for field,value in [('email','other@example.com'),('checkout','other-checkout'),('charge',2),('sale','other-sale')]:
            data=payload()
            if field=='email':data['customer']['email']=value
            elif field=='checkout':data['checkout_id']=value
            elif field=='charge':data['plan']['charge_number']=value
            else:data['sale_id']=value
            candidate=classify(data).candidate
            self.assertEqual(base.subscription_id==candidate.subscription_id,field!='sale')
            self.assertEqual(base.purchase_id==candidate.purchase_id,field not in ('sale','charge'))
        with patch('app.services.kirvano_commercial_service.SOURCE_SCOPE','another-scope'):
            other=classify(payload()).candidate
            self.assertNotEqual(base.subscription_id,other.subscription_id)
            self.assertNotEqual(base.purchase_id,other.purchase_id)
        self.assertNotEqual(base.subscription_id,base.purchase_id)

    def test_renewal_contract_eligible(self):
        data=payload();data['event']='SUBSCRIPTION_RENEWED';data['plan']['charge_number']=2
        result=classify(data)
        self.assertEqual(result.classification,State.ELIGIBLE)
        self.assertEqual(result.candidate.valid_from,datetime(2026,10,5,15,tzinfo=timezone.utc))

    def test_renewal_contract_fail_closed(self):
        mutations=[('status','PENDING'),('type','ONE_TIME'),('sale_id',None),
                   ('customer.email','bad'),('plan.charge_frequency','YEARLY'),
                   ('plan.charge_number',True),('plan.charge_number','2'),('plan.charge_number',0),
                   ('payment.finished_at','bad'),('plan.next_charge_date','2026-10-05 12:00:00')]
        for path,value in mutations:
            with self.subTest(path=path,value=value):
                data=payload();data['event']='SUBSCRIPTION_RENEWED';target=data;keys=path.split('.')
                for key in keys[:-1]:target=target[key]
                target[keys[-1]]=value
                self.assertEqual(classify(data).classification,State.REVIEW_REQUIRED)
        for zone in (None,'Invalid/Zone'):
            data=payload();data['event']='SUBSCRIPTION_RENEWED'
            self.assertEqual(classify(data,zone).classification,State.REVIEW_REQUIRED)
        for field,value in [('id','other'),('offer_id','other'),('is_order_bump',True)]:
            data=payload();data['event']='SUBSCRIPTION_RENEWED';data['products'][0][field]=value
            self.assertEqual(classify(data).classification,State.REVIEW_REQUIRED)
