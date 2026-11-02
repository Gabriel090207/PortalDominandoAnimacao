"""Directed read recovery with real emulator transactions, exact-ID cleanup."""
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import Aborted
from google.cloud.firestore_v1.document import DocumentReference
from google.cloud.firestore_v1.transaction import Transaction

from app.persistence.admin_admission_repository import AdminAdmissionUnavailable
from app.services.admin_login_service import AdminLoginService
from test_admin_complementary_admission import policy
from test_admin_complementary_admission_integration import emulator_client

pytestmark=pytest.mark.firestore_emulator


@pytest.mark.parametrize('position',[1,4])
@pytest.mark.parametrize('persistent',[False,True])
def test_precommit_read_recovery_real_transactions(emulator_client,monkeypatch,position,persistent):
    _,_,build,documents=emulator_client
    service=build(rule=policy(aggregate=20))
    transactions=[];reads={};commits=[]
    original_begin=Transaction._begin
    original_read=DocumentReference.get
    original_commit=Transaction._commit
    def begin(tx,*args,**kwargs):
        if not any(tx is item for item in transactions):transactions.append(tx)
        return original_begin(tx,*args,**kwargs)
    def read(ref,*args,**kwargs):
        tx=kwargs.get('transaction')
        if tx is not None:
            key=transactions.index(tx);reads[key]=reads.get(key,0)+1
            if reads[key]==position and (key==0 or persistent):
                raise Aborted('Synthetic directed read conflict')
        return original_read(ref,*args,**kwargs)
    def commit(tx,*args,**kwargs):
        commits.append(transactions.index(tx))
        return original_commit(tx,*args,**kwargs)
    auth=Mock();sessions=Mock();auth.authenticate.side_effect=lambda *args:sessions.create()
    with monkeypatch.context() as patch:
        patch.setattr(Transaction,'_begin',begin)
        patch.setattr(DocumentReference,'get',read)
        patch.setattr(Transaction,'_commit',commit)
        login=AdminLoginService(service,auth)
        if persistent:
            with pytest.raises(AdminAdmissionUnavailable):
                login.authenticate('192.0.2.1','synthetic@example.com','synthetic password')
        else:login.authenticate('192.0.2.1','synthetic@example.com','synthetic password')
    assert len(transactions)==2 and transactions[0] is not transactions[1]
    assert reads[0]==position
    if persistent:
        assert reads[1]==position and commits==[] and documents()=={}
        auth.authenticate.assert_not_called();sessions.create.assert_not_called()
    else:
        assert reads[1]==4 and commits==[1]
        assert auth.authenticate.call_count==sessions.create.call_count==1
        stored=documents();assert len(stored)==4
        for doc in stored.values():
            rule=doc['policy'];unit=rule['refill_period_seconds']*1_000_000
            assert doc['credits']==(rule['capacity']-1)*unit
