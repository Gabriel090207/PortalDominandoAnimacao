import copy
import json
import unittest
from unittest.mock import Mock, patch
from app.domain.states import KirvanoEventState
from app.services.kirvano_event_service import normalize_event, canonical_json
from app.persistence.kirvano_events_repository import _record_transaction, record_event
from app.persistence.collections import CollectionName


def payload():
    return {'event':'SALE_APPROVED','sale_id':'Sale-A','checkout_id':'checkout','status':'APPROVED','plan':{'charge_number':1},'products':[{'id':'b','price':'R$ 10,00'},{'id':'a','price':'R$ 20,00'}]}


class Store:
    def __init__(self):self.data={};self.pending=[]
    def create(self,ref,data):
        assert ref not in self.data
        self.pending.append((ref,copy.deepcopy(data)))
    def update(self,ref,data):self.pending.append((ref,{**self.data[ref],**copy.deepcopy(data)}))
    def commit(self):
        for ref,data in self.pending:self.data[ref]=data
        self.pending=[]


class Ref:
    def __init__(self,store,path):self.store,self.path=store,path
    def __hash__(self):return hash(self.path)
    def __eq__(self,other):return isinstance(other,Ref) and self.path==other.path
    def get(self,transaction):
        value=self.store.data.get(self);result=Mock(exists=value is not None)
        result.to_dict.return_value=copy.deepcopy(value)
        return result


class EventTests(unittest.TestCase):
    def test_canonicalization_and_duplicates(self):
        a=payload();b=dict(reversed(list(a.items())));b['products']=list(reversed(a['products']))
        self.assertEqual(normalize_event(a),normalize_event(b))
        self.assertEqual(canonical_json({'a':1,'b':2}),canonical_json({'b':2,'a':1}))
        a['products'].append(copy.deepcopy(a['products'][0]))
        self.assertEqual(len(normalize_event(a).normalized_payload['products']),3)
        self.assertNotEqual(normalize_event(a).fingerprint,normalize_event(b).fingerprint)

    def test_identity_and_review(self):
        original=normalize_event(payload())
        self.assertEqual(original.processing_status,KirvanoEventState.RECEIVED)
        a=payload();a['plan']['charge_number']=2
        self.assertNotEqual(original.logical_id,normalize_event(a).logical_id)
        a=payload();a['event']='SUBSCRIPTION_RENEWED'
        self.assertNotEqual(original.logical_id,normalize_event(a).logical_id)
        a=payload();a['checkout_id']={}
        self.assertEqual(normalize_event(a).processing_status,KirvanoEventState.REVIEW_REQUIRED)
        for value in [None,'1',True,1.0,0,-1]:
            a=payload();a['plan']['charge_number']=value;r=normalize_event(a)
            self.assertEqual(r.identity_basis,'content_fallback')
            self.assertEqual(r.processing_status,KirvanoEventState.REVIEW_REQUIRED)
            self.assertNotIn('charge_number',r.normalized_payload)
        a=payload();del a['plan']['charge_number']
        self.assertEqual(normalize_event(a).fingerprint,normalize_event({**a,'plan':{'charge_number':None}}).fingerprint)
        for event in ['UNKNOWN','SALE_REFUNDED','SALE_CHARGEBACK']:
            a['event']=event
            self.assertEqual(normalize_event(a).processing_status,KirvanoEventState.REVIEW_REQUIRED)

    def test_pii_excluded(self):
        a=payload();before=normalize_event(a)
        a.update(customer={'email':'private@example.com','name':'private'},headers={'security-token':'private'},utm={'data':'private'},qrcode='private')
        self.assertEqual(normalize_event(a),before)
        self.assertNotIn('private',json.dumps(before.normalized_payload))

    def test_retry_conflict_and_corruption(self):
        store=Store();a=normalize_event(payload());root=Ref(store,'kirvano_events/'+a.logical_id)
        def receive(event):
            result=_record_transaction(store,root,Ref(store,root.path+'/variants/'+event.fingerprint),event)
            store.commit();return result
        self.assertEqual(receive(a).outcome,'new')
        self.assertEqual(receive(a).outcome,'retry')
        self.assertEqual(len(store.data),2)
        changed=payload();changed['status']='REFUNDED';b=normalize_event(changed)
        self.assertEqual(a.logical_id,b.logical_id)
        self.assertEqual(receive(b).outcome,'conflict')
        self.assertEqual(receive(a).processing_status,KirvanoEventState.CONFLICT)
        self.assertEqual(store.data[root]['receipt_count'],4)
        self.assertEqual(store.data[root]['variant_count'],2)
        self.assertEqual(len(store.data),3)
        store.data[root]['variant_count']=0
        with self.assertRaises(RuntimeError):receive(a)

    def test_orphan(self):
        store=Store();a=normalize_event(payload());root=Ref(store,'root');variant=Ref(store,'variant');store.data[variant]={}
        with self.assertRaises(RuntimeError):_record_transaction(store,root,variant,a)
        self.assertEqual(store.pending,[])

    def test_only_collection(self):
        collection=Mock()
        with patch('app.persistence.kirvano_events_repository.get_firestore_client'), patch('app.persistence.kirvano_events_repository.get_collection_reference',return_value=collection) as getter,patch('app.persistence.kirvano_events_repository.firestore.transactional',return_value=Mock()):
            record_event(normalize_event(payload()))
            getter.assert_called_once_with(CollectionName.KIRVANO_EVENTS)
            collection.document.return_value.collection.assert_called_once_with('variants')

    def test_transaction_retry_before_commit(self):
        store=Store();event=normalize_event(payload());root=Ref(store,'root');variant=Ref(store,'variant')
        _record_transaction(store,root,variant,event)
        store.pending=[]  # Aborted attempt, as in SDK contention retry.
        _record_transaction(store,root,variant,event);store.commit()
        self.assertEqual(store.data[root]['receipt_count'],1)
        self.assertEqual(store.data[variant]['receipt_count'],1)

    def test_product_full_tuple_and_invalid_types(self):
        a=payload();a['products']=[{'id':'same','offer_id':'a','price':'10','is_order_bump':False},{'id':'same','offer_id':'b','price':'20','is_order_bump':True}]
        b=copy.deepcopy(a);b['products'].reverse()
        self.assertEqual(normalize_event(a),normalize_event(b))
        a['created_at']='private@example.com';a['plan']['next_charge_date']=False
        r=normalize_event(a)
        self.assertEqual(r.processing_status,KirvanoEventState.REVIEW_REQUIRED)
        self.assertNotIn('provider_created_at',r.normalized_payload)
        self.assertNotIn('next_charge_date',r.normalized_payload)
