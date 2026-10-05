import copy
from datetime import datetime, timezone
from unittest.mock import Mock
from google.cloud import firestore
class Ref:
    def __init__(self,c,path): self.c,self.path=c,path
    def __eq__(self,other): return isinstance(other,Ref) and self.path==other.path
    def collection(self,name):return Collection(self.c,self.path+'/'+name)
    def get(self,transaction):
        assert not transaction.writes,'Read after write'
        value=self.c.data.get(self.path);s=Mock(exists=value is not None);s.to_dict.return_value=copy.deepcopy(value);return s
class Collection:
    def __init__(self,c,path):self.c,self.path=c,path
    def document(self,id):return Ref(self.c,self.path+'/'+id)
class Client:
    def __init__(self):self.data={}
    def collection(self,name):return Collection(self,name)
class Transaction:
    def __init__(self,c):self.c,self.writes=c,[]
    def create(self,r,d):self.writes.append(('create',r.path,d))
    def update(self,r,d):self.writes.append(('update',r.path,d))
    def commit(self):
        data=copy.deepcopy(self.c.data)
        def resolve(v):
            if v is firestore.SERVER_TIMESTAMP:return datetime(2026,1,1,tzinfo=timezone.utc)
            if isinstance(v,dict):return {k:resolve(x) for k,x in v.items()}
            if isinstance(v,list):return [resolve(x) for x in v]
            return copy.deepcopy(v)
        for op,path,d in self.writes:
            if op=='create':assert path not in data;data[path]=resolve(d)
            else:assert path in data;data[path].update(resolve(d))
        self.c.data=data
