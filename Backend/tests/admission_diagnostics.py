"""Opt-in pytest plugin: sanitized stage/count telemetry, NEVER production logging.

Load explicitly with -p admission_diagnostics. No retry, timing or assertion changes.
"""
import json
from threading import local, Lock
from time import monotonic
from collections import Counter

import pytest
from google.cloud.firestore_v1.transaction import Transaction
from google.cloud.firestore_v1.document import DocumentReference
from app.services.admin_admission_service import AdminAdmissionService


def exception_types(error):
    names=[];seen=set()
    while error is not None and id(error) not in seen:
        seen.add(id(error));names.append(type(error).__name__)
        error=error.__cause__ or error.__context__
    return names


@pytest.fixture(autouse=True)
def admission_telemetry(request,emulator_client,monkeypatch):
    if (not request.node.get_closest_marker('firestore_emulator') or
        not isinstance(emulator_client,tuple) or len(emulator_client)!=4):
        yield
        return
    _,_,_,documents=emulator_client
    active=local();lock=Lock();operations=[];started=monotonic()
    def wrap_method(cls,name,stage):
        original=getattr(cls,name)
        def wrapped(instance,*args,**kwargs):
            op=getattr(active,'operation',None)
            if op is not None:
                op['stage']=stage
                op['counts'][stage]+=1
                if name in ('create','update'):op['writes_buffered']=True
                if name=='get' and op['writes_buffered']:op['read_after_write']=True
                if name=='_begin':op['writes_buffered']=False
            try:return original(instance,*args,**kwargs)
            except Exception as error:
                if op is not None:op['errors'].append({'stage':stage,'types':exception_types(error)})
                raise
        monkeypatch.setattr(cls,name,wrapped)
    for name,stage in [('_begin','begin'),('_commit','commit'),('_rollback','rollback'),
                       ('create','buffer_create'),('update','buffer_update')]:
        wrap_method(Transaction,name,stage)
    wrap_method(DocumentReference,'get','read')
    original=AdminAdmissionService.admit_attempt
    def admit(service,*args,**kwargs):
        op={'counts':Counter(),'errors':[],'stage':'service','writes_buffered':False,'read_after_write':False}
        with lock:operations.append(op)
        active.operation=op
        try:
            result=original(service,*args,**kwargs)
            op['result']=str(result.outcome)
            return result
        except Exception as error:
            op['result']='error';op['exception_types']=exception_types(error)
            raise
        finally:active.operation=None
    monkeypatch.setattr(AdminAdmissionService,'admit_attempt',admit)
    try:yield
    finally:
        try:
            stored=documents()
            scopes={}
            for doc in stored.values():
                rule=doc['policy'];scope=doc['scope'];unit=rule['refill_period_seconds']*1_000_000
                item=scopes.setdefault(scope,{'documents':0,'total_debit_tokens':0})
                item['documents']+=1
                item['total_debit_tokens']+=(rule['capacity']*unit-doc['credits'])/unit
            summary={'test':request.node.name,'operations':[
                {key:value for key,value in op.items() if key not in ('writes_buffered',)} for op in operations],
                'persisted_scopes':scopes,'seconds':round(monotonic()-started,3)}
            print('ADMISSION_DIAGNOSTIC '+json.dumps(summary,sort_keys=True))
        except Exception as error:
            print('ADMISSION_DIAGNOSTIC '+json.dumps({'test':request.node.name,'diagnostic_error_types':exception_types(error)}))
