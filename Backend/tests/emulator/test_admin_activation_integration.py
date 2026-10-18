"""Actual atomic activation/audit and concurrent SDK transactions on demo only."""
import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.cloud.firestore_v1.transaction import Transaction
from app.admin_composition import compose_admin_http
from app.config.admin_admission import load_admin_admission_config
from app.config.admin_http_security import AdminRequestSecurityConfig
from app.domain.admin_activation import CustomerActivationUnavailable
from app.persistence.admin_activation_repository import AdminActivationRepository
from test_admin_activation import records
from test_admin_auth_integration import seed
from test_admin_domain import admin
from test_admin_customers_integration import state
pytestmark=pytest.mark.firestore_emulator
ORIGIN='https://admin.example.test'


def prepare(client,role='owner'):
    seed(client,role)
    data=records()
    for path,value in data.items():
        if not path.startswith('admins/'):
            client.document(path).create(value,timeout=5)
    client.collection('subscriptions').document('sentinel').create({'status':'canceled','unchanged':True},timeout=5)
    return data['purchases/purchase-a']['valid_from']


def composition(client,now):
    return compose_admin_http(firestore_client=client,
        admission_config=load_admin_admission_config(environ={'ADMIN_ADMISSION_HMAC_SECRET':'0123456789abcdef'*4},env_file=None),
        security_config=AdminRequestSecurityConfig((ORIGIN,)),clock=lambda:now)


@pytest.mark.parametrize('role',['owner','operator'])
def test_activation_atomic_audit_minimal_update_idempotent(emulator_client,role):
    now=prepare(emulator_client,role);app=FastAPI();composed=composition(emulator_client,now);app.include_router(composed.router)
    token=composed.session_service.create(admin(role=role)).token.get_secret_value()
    before=state(emulator_client)
    headers={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+token,'X-Admin-Request':'1'}
    with TestClient(app) as http:
        path='/admin/customers/customer-a/activate'
        response=http.post(path,headers=headers,json={'confirm_activation':True})
        assert response.status_code==200 and response.json()['result']=='activated'
        assert response.headers['cache-control']=='no-store'
        assert http.post(path,headers=headers,json={'confirm_activation':True}).json()['result']=='already_active'
        assert http.get('/admin/customers/customer-a',headers=headers).json()['activation_status']=='active'
        assert http.get('/admin/auth/session',headers=headers).status_code==200
    after=state(emulator_client)
    for collection in before:
        if collection!='users':assert after[collection]==before[collection]
    original=before['users']['customer-a'][0]
    assert after['users']['customer-a'][0]==original|{'activation_status':'active'}
    audits=after['activation_audit'];assert len(audits)==1
    audit=next(iter(audits.values()))[0]
    assert audit['admin_id']=='synthetic-admin' and audit['customer_id']=='customer-a'
    assert audit['previous_activation_status']=='pending' and audit['activation_status']=='active'
    assert 'synthetic-private' not in str(audit)


def test_concurrent_activation_one_transition_one_audit(emulator_client,record_property):
    now=prepare(emulator_client);barrier=Barrier(2)
    original=state(emulator_client);failures=[]
    def activate():
        repo=AdminActivationRepository(emulator_client,clock=lambda:now)
        barrier.wait(timeout=10)
        try:return repo.activate('customer-a',admin()).result
        except CustomerActivationUnavailable as error:
            # Test-only, sanitized exception classes; never raw errors/documents.
            chain=[];seen=set()
            while error is not None and id(error) not in seen:
                seen.add(id(error));frames=[];trace=error.__traceback__
                while trace:
                    frames.append((trace.tb_frame.f_code.co_name,trace.tb_lineno));trace=trace.tb_next
                chain.append({'type':type(error).__name__,'frames':frames})
                error=error.__cause__ or error.__context__
            failures.append(chain)
            return 'unconfirmed'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:activate(),range(2)))
    # Always inspect committed state BEFORE the progress assertion, even on 503.
    after=state(emulator_client)
    customer=after['users']['customer-a'][0]
    audits=after.get('activation_audit',{})
    preserved={collection:after.get(collection)==value for collection,value in original.items() if collection!='users'}
    user_fields_preserved=customer==original['users']['customer-a'][0]|{'activation_status':customer['activation_status']}
    diagnostic={'results':results,'calls':len(results),'errors':failures,
        'activation':customer['activation_status'],'account':customer['account_status'],'audits':len(audits),
        'audit_transitions':[{'admin_id':value['admin_id'],'customer_id':value['customer_id'],
            'before':value['previous_activation_status'],'after':value['activation_status']} for value,_ in audits.values()],
        'preserved_collections':preserved,'other_user_fields_preserved':user_fields_preserved}
    # Available to the test recorder BEFORE any invariant/progress assertion.
    record_property('activation_diagnostic',diagnostic)
    assert all(preserved.values()),diagnostic
    assert user_fields_preserved,diagnostic
    assert customer['account_status']=='enabled',diagnostic
    assert customer['activation_status'] in ('pending','active'),diagnostic
    assert len(audits)==(1 if customer['activation_status']=='active' else 0),diagnostic
    for document,_ in audits.values():
        assert document['admin_id']=='synthetic-admin' and document['customer_id']=='customer-a',diagnostic
        assert document['previous_activation_status']=='pending' and document['activation_status']=='active',diagnostic
    # Preserve the original expectation. Do not turn arbitrary failures into passes.
    assert results.count('activated')==1,diagnostic
    assert set(results)<= {'activated','already_active','unconfirmed'},diagnostic
    assert customer['activation_status']=='active',diagnostic
    audit=list(emulator_client.collection('activation_audit').stream(timeout=5))
    before=copy.deepcopy(audit[0].to_dict())
    assert AdminActivationRepository(emulator_client,clock=lambda:now).activate('customer-a',admin()).result=='already_active'
    assert list(emulator_client.collection('activation_audit').stream(timeout=5))[0].to_dict()==before
    assert emulator_client.document('users/customer-a').get(timeout=5).to_dict()['activation_status']=='active'


def test_audit_failure_before_commit_leaves_all_documents_unchanged(emulator_client,monkeypatch):
    now=prepare(emulator_client);before=state(emulator_client)
    original=Transaction.create
    def fail_audit(self,ref,data):
        if ref.parent.id=='activation_audit':raise RuntimeError('synthetic-private')
        return original(self,ref,data)
    monkeypatch.setattr(Transaction,'create',fail_audit)
    with pytest.raises(CustomerActivationUnavailable):
        AdminActivationRepository(emulator_client,clock=lambda:now).activate('customer-a',admin())
    assert state(emulator_client)==before


def test_simulated_lost_commit_acknowledgement_never_announces_success(emulator_client,monkeypatch):
    now=prepare(emulator_client);original=Transaction._commit;commits=[]
    composed=composition(emulator_client,now);app=FastAPI();app.include_router(composed.router)
    token=composed.session_service.create(admin()).token.get_secret_value()
    headers={'Origin':ORIGIN,'Cookie':'__Host-admin_session='+token,'X-Admin-Request':'1'}
    def lose_ack(self,*args,**kwargs):
        activation=any('/activation_audit/' in write.update.name for write in self._write_pbs)
        result=original(self,*args,**kwargs)
        if activation:
            commits.append(True)
            raise RuntimeError('synthetic-lost-acknowledgement')
        return result
    with TestClient(app) as http:
        with monkeypatch.context() as patch:
            patch.setattr(Transaction,'_commit',lose_ack)
            response=http.post('/admin/customers/customer-a/activate',headers=headers,json={'confirm_activation':True})
        assert response.status_code==503 and response.headers['cache-control']=='no-store'
        assert response.json()=={'detail':'Customer activation not confirmed.'}
        assert 'synthetic-lost-acknowledgement' not in response.text
        assert len(commits)==1
        # 503 did not mean that nothing was committed.
        current=http.get('/admin/customers/customer-a',headers=headers)
        assert current.json()['activation_status']=='active'
        assert len(list(emulator_client.collection('activation_audit').stream(timeout=5)))==1
        repeat=http.post('/admin/customers/customer-a/activate',headers=headers,json={'confirm_activation':True})
        assert repeat.json()['result']=='already_active'
        assert len(list(emulator_client.collection('activation_audit').stream(timeout=5)))==1


def test_concurrent_activation_different_customers_preserves_commerce(emulator_client):
    from app.services.kirvano_event_service import digest
    now=prepare(emulator_client);source=records()
    user=source['users/customer-a']|{'email_normalized':'second@example.com'}
    purchase=source['purchases/purchase-a']|{'user_id':'customer-b','subscription_id':'b'*64}
    old_right=next(value for key,value in source.items() if key.startswith('entitlements/'))
    right=old_right|{'user_id':'customer-b','purchase_id':'purchase-b'}
    right_id=digest(['kirvano-entitlement',1,'purchase-b','portal'])
    emulator_client.document('users/customer-b').create(user,timeout=5)
    emulator_client.document('purchases/purchase-b').create(purchase,timeout=5)
    emulator_client.document('entitlements/'+right_id).create(right,timeout=5)
    before=state(emulator_client);barrier=Barrier(2)
    def activate(identifier):
        barrier.wait(timeout=10)
        return AdminActivationRepository(emulator_client,clock=lambda:now).activate(identifier,admin()).result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(activate,['customer-a','customer-b']))
    assert results==['activated','activated']
    after=state(emulator_client)
    for collection,value in before.items():
        if collection!='users':assert after[collection]==value
    for identifier in ('customer-a','customer-b'):
        assert after['users'][identifier][0]==before['users'][identifier][0]|{'activation_status':'active'}
    assert len(after['activation_audit'])==2
    assert {row[0]['customer_id'] for row in after['activation_audit'].values()}=={'customer-a','customer-b'}


@pytest.mark.parametrize('kind',['recover','exhausted','generic'])
def test_native_activation_commit_budget(emulator_client,monkeypatch,kind):
    from google.api_core.exceptions import Aborted
    from app.domain.admin_activation import CustomerActivationUnavailable
    now=prepare(emulator_client);before=state(emulator_client);original=Transaction._commit;attempts=[]
    def inject(self,*args,**kwargs):
        if any('/activation_audit/' in write.update.name for write in self._write_pbs):
            attempts.append(1)
            assert emulator_client.document('users/customer-a').get(timeout=5).to_dict()['activation_status']=='pending'
            assert not list(emulator_client.collection('activation_audit').stream(timeout=5))
            if kind=='generic':raise ValueError('synthetic Aborted text')
            if kind=='exhausted' or len(attempts)<8:
                # Test injection: release/rollback real server transaction BEFORE
                # simulating a confirmed abort. This is not a network uncertainty.
                self._rollback()
                raise Aborted('synthetic confirmed abort')
        return original(self,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Transaction,'_commit',inject)
        repo=AdminActivationRepository(emulator_client,clock=lambda:now)
        if kind=='recover':assert repo.activate('customer-a',admin()).result=='activated'
        else:
            with pytest.raises(CustomerActivationUnavailable):repo.activate('customer-a',admin())
    after=state(emulator_client)
    assert len(attempts)==(1 if kind=='generic' else 8)
    if kind=='recover':
        assert after['users']['customer-a'][0]==before['users']['customer-a'][0]|{'activation_status':'active'}
        assert len(after['activation_audit'])==1
        for collection,value in before.items():
            if collection!='users':assert after[collection]==value
    else:assert after==before


@pytest.mark.parametrize('change',['account','entitlement'])
def test_native_retry_revalidates_persisted_conditions(emulator_client,monkeypatch,change):
    from google.api_core.exceptions import Aborted
    from app.domain.admin_activation import CustomerActivationConflict
    now=prepare(emulator_client);original=Transaction._commit;attempts=[]
    def inject(self,*args,**kwargs):
        if any('/activation_audit/' in write.update.name for write in self._write_pbs):
            attempts.append(1);self._rollback()
            if change=='account':emulator_client.document('users/customer-a').update({'account_status':'blocked'},timeout=5)
            else:
                right=next(emulator_client.collection('entitlements').stream(timeout=5))
                right.reference.update({'status':'revoked'},timeout=5)
            raise Aborted('synthetic confirmed abort')
        return original(self,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Transaction,'_commit',inject)
        with pytest.raises(CustomerActivationConflict):
            AdminActivationRepository(emulator_client,clock=lambda:now).activate('customer-a',admin())
    assert len(attempts)==1
    assert emulator_client.document('users/customer-a').get(timeout=5).to_dict()['activation_status']=='pending'
    assert not list(emulator_client.collection('activation_audit').stream(timeout=5))
