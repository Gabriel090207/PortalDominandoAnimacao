"""PASSO 76: real transactions, only UUID fixture documents, no project wipe.

Reuse PASSO 74's non-destructive fixture. Never run the legacy global cleanup.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from google.api_core.exceptions import Aborted
from google.cloud.firestore_v1.transaction import Transaction
from google.cloud.firestore_v1.base_query import FieldFilter
from fastapi.testclient import TestClient
from app.tools import prepare_local_customer as tool
from app.tools import admin_local as local
from app.persistence.collections import CollectionName as C
from app.persistence.admin_records import AdminRecord
from app.persistence.admin_activation_repository import AdminActivationRepository
from app.persistence.admin_suspension_repository import AdminSuspensionRepository
from app.persistence.admin_resumption_repository import AdminResumptionRepository
from app.persistence.admin_sessions_repository import AdminSessionsRepository
from app.persistence.admin_access_eligibility import _resolve_candidate
from app.domain.admin_activation import CustomerActivationAudit,CustomerActivationUnavailable,CustomerActivationConflict
from app.domain.admin_suspension import CustomerSuspensionAudit,CustomerSuspensionUnavailable,CustomerSuspensionConflict
from app.domain.admin_resumption import CustomerResumptionAudit,CustomerResumptionUnavailable,CustomerResumptionConflict
from app.domain.models import UserAccessState
from app.services.admin_session_service import AdminSessionService
from app.services.admin_password_service import hash_admin_password
from app.services.access_service import can_access_portal
from test_admin_domain import admin
from test_local_customer_lookup_integration import emulator_client  # noqa: F401 - overrides destructive fixture

pytestmark=pytest.mark.firestore_emulator
OPERATIONS={
 'activate':(AdminActivationRepository,CustomerActivationAudit,CustomerActivationUnavailable,CustomerActivationConflict,'active',8),
 'suspend':(AdminSuspensionRepository,CustomerSuspensionAudit,CustomerSuspensionUnavailable,CustomerSuspensionConflict,'suspended',5),
 'resume':(AdminResumptionRepository,CustomerResumptionAudit,CustomerResumptionUnavailable,CustomerResumptionConflict,'active',8),
}


def audits(client):
 return list(client.collection(C.ACTIVATION_AUDIT.value).where(filter=FieldFilter('customer_id','==',tool.USER_ID)).stream(timeout=10))


@pytest.fixture
def case(emulator_client):
 client,refs,owned=emulator_client
 tool.prepare_customer()
 identifier='audit-'+uuid4().hex
 actor=admin(admin_id=identifier,email_normalized=f'{identifier}@example.com')
 ref=client.collection('admins').document(identifier)
 ref.create(AdminRecord(**actor.model_dump(),password_hash=hash_admin_password('synthetic audit-only validation password')).to_document())
 owned.append(ref)
 try:yield client,refs,actor
 finally:
  owned.extend(row.reference for row in audits(client))
  owned.extend(row.reference for row in client.collection('admin_sessions').where(filter=FieldFilter('admin_id','==',identifier)).stream(timeout=10))


def call(case,operation):
 client,_,actor=case
 return getattr(OPERATIONS[operation][0](client),operation)(tool.USER_ID,actor)


def prepare(case,operation):
 if operation in ('suspend','resume'):assert call(case,'activate').result=='activated'
 if operation=='resume':assert call(case,'suspend').result=='suspended'


def snapshot(case):
 client,refs,_=case
 return ({key:(ref.get().to_dict(),ref.get().update_time) for key,ref in refs.items()},
         {row.id:(row.to_dict(),row.update_time) for row in audits(client)})


def assert_commerce_unchanged(before,after):
 for key in (C.SUBSCRIPTIONS,C.PURCHASES,C.ENTITLEMENTS,C.KIRVANO_EVENTS,C.EMAIL_IDENTITIES):
  assert before[0][key]==after[0][key]


def assert_audit_transition(case,operation,previous_count):
 client,refs,actor=case
 model=OPERATIONS[operation][1]
 rows=audits(client)
 assert len(rows)==previous_count+1
 matches=[row.to_dict() for row in rows if row.to_dict()['operation']==model.model_fields['operation'].default]
 assert len(matches)==1
 record=matches[0]
 assert set(record)==set(model.model_fields)
 validated=model.model_validate(record)
 assert validated.customer_id==tool.USER_ID and validated.admin_id==actor.admin_id
 assert validated.human_confirmation is True
 assert refs[C.USERS].get().to_dict()['created_at']<=validated.occurred_at<=datetime.now(timezone.utc)
 assert refs[C.USERS].get().to_dict()['activation_status']==validated.activation_status
 assert not any(key in record for key in ('email','password','token','cookie','password_hash'))


@pytest.mark.parametrize('role',['owner','operator'])
def test_http_lifecycle_author_confirmation_audit_and_noops(case,role):
 client,refs,actor=case
 client.collection('admins').document(actor.admin_id).update({'role':role})
 actor=actor.model_copy(update={'role':role})
 case=(client,refs,actor)
 sessions=AdminSessionService(AdminSessionsRepository(client))
 issued=sessions.create(actor)
 app=local.create_local_app()
 h={'Origin':local.ORIGIN,'X-Admin-Request':'1'}
 initial=snapshot(case)
 with TestClient(app,base_url='https://localhost:8443',client=('127.0.0.1',1234)) as http:
  for operation in OPERATIONS:
   url=f'/admin/customers/{tool.USER_ID}/{operation}'
   assert http.post(url,headers=h,json={}).status_code==401
  http.cookies.set('__Host-admin_session',issued.token.get_secret_value())
  for count,operation in enumerate(OPERATIONS):
   url=f'/admin/customers/{tool.USER_ID}/{operation}'
   confirmation={'confirm_'+{'activate':'activation','suspend':'suspension','resume':'resumption'}[operation]:True}
   before=snapshot(case)
   for body in ({},confirmation|{'admin_id':'forged-author'}):
    assert http.post(url,headers=h,json=body).status_code==400
    assert snapshot(case)==before
   response=http.post(url,headers=h,json=confirmation)
   assert response.status_code==200
   assert_audit_transition(case,operation,count)
   after=snapshot(case)
   assert after[0][C.USERS][0]==before[0][C.USERS][0]|{'activation_status':OPERATIONS[operation][4]}
   assert_commerce_unchanged(before,after)
   assert http.get('/admin/customers/'+tool.USER_ID,headers=h).json()['activation_status']==OPERATIONS[operation][4]
   assert http.post(url,headers=h,json=confirmation).status_code==200
   assert snapshot(case)==after
   projection=_resolve_candidate(None,client,tool.USER_ID,refs[C.PURCHASES].get())
   user=refs[C.USERS].get().to_dict()
   allowed=can_access_portal(tool.USER_ID,UserAccessState(account_status=user['account_status'],activation_status=user['activation_status']),[projection],now=datetime.now(timezone.utc))
   assert allowed==(operation!='suspend')
 assert_commerce_unchanged(initial,snapshot(case))
 assert {r.to_dict()['operation'] for r in audits(client)}=={'activate_customer','suspend_customer','resume_customer'}


@pytest.mark.parametrize('operation',OPERATIONS)
@pytest.mark.parametrize('mode',['audit','before_commit','lost_ack','recover','exhausted'])
def test_atomic_failure_native_budget_and_uncertain_outcome(case,monkeypatch,operation,mode):
 prepare(case,operation);client,refs,_=case
 before=snapshot(case);attempts=[]
 commit,create=Transaction._commit,Transaction.create
 def scoped(tx):return any('/activation_audit/' in write.update.name and tool.USER_ID in str(write) for write in tx._write_pbs)
 def fail_create(tx,ref,data):
  if mode=='audit' and data.get('customer_id')==tool.USER_ID and data.get('operation')==OPERATIONS[operation][1].model_fields['operation'].default:
   raise RuntimeError('synthetic private audit detail')
  return create(tx,ref,data)
 def fail_commit(tx,*args,**kwargs):
  if not scoped(tx):return commit(tx,*args,**kwargs)
  attempts.append(1)
  if mode=='lost_ack':
   commit(tx,*args,**kwargs);raise RuntimeError('synthetic private uncertain acknowledgement')
  if mode=='before_commit':raise RuntimeError('synthetic private before commit')
  if mode=='exhausted' or mode=='recover' and len(attempts)<2:
   tx._rollback();raise Aborted('synthetic confirmed rollback')
  return commit(tx,*args,**kwargs)
 with monkeypatch.context() as patch:
  patch.setattr(Transaction,'create',fail_create);patch.setattr(Transaction,'_commit',fail_commit)
  if mode=='recover':call(case,operation)
  else:
   with pytest.raises(OPERATIONS[operation][2]) as failure:call(case,operation)
   assert 'synthetic private' not in str(failure.value)
 after=snapshot(case)
 assert len(attempts)==(0 if mode=='audit' else OPERATIONS[operation][5] if mode=='exhausted' else 2 if mode=='recover' else 1)
 if mode in ('lost_ack','recover'):
  assert after[0][C.USERS][0]==before[0][C.USERS][0]|{'activation_status':OPERATIONS[operation][4]}
  assert_audit_transition(case,operation,len(before[1]))
  assert call(case,operation).result in ('already_active','already_suspended')
  assert snapshot(case)==after
 else:assert after==before
 assert_commerce_unchanged(before,after)


@pytest.mark.parametrize('operation',OPERATIONS)
@pytest.mark.parametrize('repetition',range(3))
def test_duplicate_concurrent_operations_keep_one_transition(case,operation,repetition,record_property):
 prepare(case,operation);before=snapshot(case)
 def invoke(_):
  try:return call(case,operation).result
  except OPERATIONS[operation][2]:return 'unconfirmed'
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(invoke,range(2)))
 record_property('transaction_results',results)
 success={'activate':'activated','suspend':'suspended','resume':'resumed'}[operation]
 assert results.count(success)<=1
 after=snapshot(case)
 # An unconfirmed result is not proof of rollback: inspect the persisted facts.
 if after[0][C.USERS][0]['activation_status']==OPERATIONS[operation][4]:
  assert_audit_transition(case,operation,len(before[1]))
 else:assert after==before
 assert_commerce_unchanged(before,after)


@pytest.mark.parametrize('operation',OPERATIONS)
@pytest.mark.parametrize('restriction',['blocked','disabled_actor','changed_auth_version'])
def test_persisted_restrictions_rechecked_without_audit(case,operation,restriction):
 prepare(case,operation);client,refs,actor=case
 if restriction=='blocked':refs[C.USERS].update({'account_status':'blocked'})
 else:client.collection('admins').document(actor.admin_id).update({'status':'disabled'} if restriction=='disabled_actor' else {'auth_version':2})
 before=snapshot(case)
 with pytest.raises(OPERATIONS[operation][3]):call(case,operation)
 assert snapshot(case)==before


@pytest.mark.parametrize('operation,restriction',[(op,kind) for op in ('activate','resume') for kind in ('canceled','expired')]+[('resume','missing_history')])
def test_eligibility_and_resumption_history_remain_mandatory(case,operation,restriction):
 prepare(case,operation);client,refs,_=case
 if restriction=='canceled':refs[C.SUBSCRIPTIONS].update({'status':'canceled'})
 elif restriction=='expired':
  end=datetime.now(timezone.utc)-timedelta(hours=1)
  for key in (C.PURCHASES,C.ENTITLEMENTS):refs[key].update({'valid_until':end})
 elif operation=='resume':
  for row in audits(client):row.reference.delete()
 before=snapshot(case)
 with pytest.raises(OPERATIONS[operation][3]):call(case,operation)
 assert snapshot(case)==before


@pytest.mark.parametrize('repetition',range(3))
def test_incompatible_resume_suspend_race_has_a_serializable_audit(case,repetition,record_property):
 prepare(case,'resume');before=snapshot(case)
 def invoke(operation):
  try:return call(case,operation).result
  except OPERATIONS[operation][2]:return 'unconfirmed'
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(invoke,['resume','suspend']))
 record_property('incompatible_results',results)
 after=snapshot(case)
 records=[row.to_dict() for row in audits(case[0])]
 counts={operation:sum(row['operation']==operation for row in records) for operation in ('activate_customer','suspend_customer','resume_customer')}
 assert counts['activate_customer']==1
 assert counts['resume_customer'] in (0,1) and counts['suspend_customer'] in (1,2)
 if counts['resume_customer']==0:assert counts['suspend_customer']==1
 expected='active' if counts['resume_customer']==1 and counts['suspend_customer']==1 else 'suspended'
 assert after[0][C.USERS][0]['activation_status']==expected
 for row in records:
  assert row['admin_id']==case[2].admin_id and row['customer_id']==tool.USER_ID
  assert row['human_confirmation'] is True
  model=next(values[1] for values in OPERATIONS.values() if values[1].model_fields['operation'].default==row['operation'])
  model.model_validate(row)
 assert_commerce_unchanged(before,after)


def test_legitimate_renewal_does_not_remove_administrative_suspension(case):
 from google.cloud import firestore
 from app.services.kirvano_event_service import normalize_event,digest
 from app.services.kirvano_commercial_service import classify_commercial_event
 from app.domain.email_identity import derive_email_identity
 from app.persistence.kirvano_commerce_repository import commercial_transaction
 prepare(case,'resume');client,refs,_=case
 before=snapshot(case)
 payload=tool.sale_payload(datetime.now(timezone.utc))
 payload.update(event='SUBSCRIPTION_RENEWED')
 end=refs[C.PURCHASES].get().to_dict()['valid_until']
 payload['plan']['charge_number']=2
 payload['payment']['finished_at']=end.strftime('%Y-%m-%d %H:%M:%S')
 payload['plan']['next_charge_date']=(end+timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
 classified=classify_commercial_event(payload,timezone_name='UTC');event=normalize_event(payload)
 identity=derive_email_identity(tool.EMAIL,secret=tool._FIXTURE_KEY)
 extra=[client.collection('purchases').document(classified.candidate.purchase_id),
  client.collection('entitlements').document(digest(['kirvano-entitlement',1,classified.candidate.purchase_id,'portal']))]
 root=client.collection('kirvano_events').document(event.logical_id)
 extra.extend([root.collection('variants').document(event.fingerprint),root])
 try:
  firestore.transactional(commercial_transaction)(client.transaction(),client,event,classified,identity,tool.USER_ID)
  assert refs[C.USERS].get().to_dict()==before[0][C.USERS][0]
  assert {r.id:(r.to_dict(),r.update_time) for r in audits(client)}==before[1]
  assert refs[C.USERS].get().to_dict()['activation_status']=='suspended'
  assert extra[0].get().exists and extra[1].get().exists
  projection=_resolve_candidate(None,client,tool.USER_ID,refs[C.PURCHASES].get())
  assert not can_access_portal(tool.USER_ID,UserAccessState(account_status='enabled',activation_status='suspended'),[projection],now=datetime.now(timezone.utc))
 finally:
  for ref in extra:ref.delete(timeout=10)


@pytest.mark.parametrize('order',[('resume','suspend'),('suspend','resume')])
def test_both_serial_orders_preserve_prior_audit_records(case,order):
 prepare(case,'resume');before=snapshot(case)
 for operation in order:call(case,operation)
 after=snapshot(case)
 for identifier,record in before[1].items():assert after[1][identifier]==record
 expected='suspended' if order[-1]=='suspend' else 'active'
 assert after[0][C.USERS][0]['activation_status']==expected
 assert len(after[1])==len(before[1])+(2 if order[0]=='resume' else 1)
 assert_commerce_unchanged(before,after)
