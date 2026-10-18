"""Explicit customer router factory, never included in app.main."""
import re
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from app.api.admin_auth import _NoStoreAdminRoute
from app.api.admin_dependencies import AdminHTTPAuthentication
from app.api.admin_request_security import AdminOriginSecurity, AdminRequestSecurity
from app.domain.admin import AdminPermission, Admin
from app.domain.admin_suspension import CustomerSuspensionResult, CustomerSuspensionConflict
from app.domain.admin_activation import CustomerActivationResult, CustomerActivationConflict
from app.domain.admin_customers import AdminCustomer, AdminCustomerPage, AdminPurchaseConfirmation, InvalidCustomerPagination, InvalidCustomerIdentifier, InvalidCustomerLookup, AmbiguousCustomerLookup


def create_admin_customers_router(*,session_service,customers_service,security_config,activation_service=None,suspension_service=None):
    authentication=AdminHTTPAuthentication(session_service)
    origin=AdminOriginSecurity(security_config)
    router=APIRouter(prefix='/admin',tags=['Admin customers'],route_class=_NoStoreAdminRoute)

    @router.get('/customers',response_model=AdminCustomerPage,dependencies=[Depends(origin),
        Depends(authentication.require_permission(AdminPermission.READ_CUSTOMERS))])
    async def customers(request:Request):
        try:
            params=request.query_params
            if set(params)-{'limit','cursor'} or any(len(params.getlist(key))!=1 for key in params):
                raise InvalidCustomerPagination()
            raw=params.get('limit','20')
            if not re.fullmatch(r'[1-9][0-9]?',raw):
                raise InvalidCustomerPagination()
            return await run_in_threadpool(customers_service.list_customers,limit=int(raw),cursor=params.get('cursor'))
        except InvalidCustomerPagination:
            raise HTTPException(status_code=400,detail='Invalid customer pagination.') from None
        except Exception:
            raise HTTPException(status_code=503,detail='Administrative customer query unavailable.') from None

    @router.get('/customers/{customer_id}',response_model=AdminCustomer,dependencies=[Depends(origin),
        Depends(authentication.require_permission(AdminPermission.READ_CUSTOMERS))])
    async def customer(customer_id:str,request:Request):
        if request.query_params:
            raise HTTPException(status_code=400,detail='Invalid customer request.')
        try:
            result=await run_in_threadpool(customers_service.get_customer,customer_id)
        except InvalidCustomerIdentifier:
            raise HTTPException(status_code=400,detail='Invalid customer identifier.') from None
        except Exception:
            raise HTTPException(status_code=503,detail='Administrative customer query unavailable.') from None
        if result is None:
            raise HTTPException(status_code=404,detail='Customer not found.')
        return result

    @router.get('/customers/{customer_id}/purchase-confirmation',response_model=AdminPurchaseConfirmation,
        dependencies=[Depends(origin),Depends(authentication.require_permission(AdminPermission.READ_CUSTOMERS))])
    async def purchase_confirmation(customer_id:str,request:Request):
        if request.query_params:
            raise HTTPException(status_code=400,detail='Invalid customer request.')
        try:
            result=await run_in_threadpool(customers_service.purchase_confirmation,customer_id)
        except InvalidCustomerIdentifier:
            raise HTTPException(status_code=400,detail='Invalid customer identifier.') from None
        except Exception:
            raise HTTPException(status_code=503,detail='Administrative purchase confirmation unavailable.') from None
        if result is None:
            raise HTTPException(status_code=404,detail='Customer not found.')
        return result

    lookup_security=AdminRequestSecurity(security_config)

    @router.post('/customers/lookup',response_model=AdminCustomer,dependencies=[Depends(lookup_security),
        Depends(authentication.require_permission(AdminPermission.READ_CUSTOMERS))])
    async def lookup_customer(request:Request):
        if request.query_params:
            raise HTTPException(status_code=400,detail='Invalid customer lookup.')
        body=bytearray()
        async for chunk in request.stream():
            if len(body)+len(chunk)>4096:
                raise HTTPException(status_code=413,detail='Customer lookup request too large.')
            body.extend(chunk)
        try:
            def unique_object(pairs):
                result={}
                for key,value in pairs:
                    if key in result:
                        raise ValueError
                    result[key]=value
                return result
            def invalid_constant(value):
                raise ValueError
            data=json.loads(body,object_pairs_hook=unique_object,parse_constant=invalid_constant)
            if not isinstance(data,dict) or set(data)!={'email'} or not isinstance(data['email'],str):
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400,detail='Invalid customer lookup.') from None
        try:
            result=await run_in_threadpool(customers_service.lookup_customer,data['email'])
        except InvalidCustomerLookup:
            raise HTTPException(status_code=400,detail='Invalid customer lookup.') from None
        except AmbiguousCustomerLookup:
            raise HTTPException(status_code=409,detail='Customer lookup is ambiguous.') from None
        except Exception:
            raise HTTPException(status_code=503,detail='Administrative customer lookup unavailable.') from None
        if result is None:
            raise HTTPException(status_code=404,detail='Customer not found.')
        return result

    @router.post('/customers/{customer_id}/activate',response_model=CustomerActivationResult,
        dependencies=[Depends(lookup_security)])
    async def activate_customer(customer_id:str,request:Request,
        administrator:Admin=Depends(authentication.require_permission(AdminPermission.ACTIVATE_CUSTOMER))):
        if request.query_params:
            raise HTTPException(status_code=400,detail='Invalid customer activation request.')
        body=bytearray()
        async for chunk in request.stream():
            if len(body)+len(chunk)>4096:
                raise HTTPException(status_code=413,detail='Customer activation request too large.')
            body.extend(chunk)
        try:
            def unique_object(pairs):
                result={}
                for key,value in pairs:
                    if key in result:raise ValueError
                    result[key]=value
                return result
            def invalid_constant(value):raise ValueError
            data=json.loads(body,object_pairs_hook=unique_object,parse_constant=invalid_constant)
            if not isinstance(data,dict) or set(data)!={'confirm_activation'} or data['confirm_activation'] is not True:
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400,detail='Invalid customer activation request.') from None
        try:
            from app.domain.admin_customers import customer_identifier
            identifier=customer_identifier(customer_id)
            if activation_service is None:raise RuntimeError
            result=await run_in_threadpool(activation_service.activate,identifier,administrator)
        except InvalidCustomerIdentifier:
            raise HTTPException(status_code=400,detail='Invalid customer identifier.') from None
        except CustomerActivationConflict:
            raise HTTPException(status_code=409,detail='Customer activation preconditions not satisfied.') from None
        except Exception:
            raise HTTPException(status_code=503,detail='Customer activation not confirmed.') from None
        if result is None:raise HTTPException(status_code=404,detail='Customer not found.')
        return result

    @router.post('/customers/{customer_id}/suspend',response_model=CustomerSuspensionResult,
        dependencies=[Depends(lookup_security)])
    async def suspend_customer(customer_id:str,request:Request,
        administrator:Admin=Depends(authentication.require_permission(AdminPermission.SUSPEND_CUSTOMER))):
        if request.query_params:
            raise HTTPException(status_code=400,detail='Invalid customer suspension request.')
        body=bytearray()
        async for chunk in request.stream():
            if len(body)+len(chunk)>4096:
                raise HTTPException(status_code=413,detail='Customer suspension request too large.')
            body.extend(chunk)
        try:
            def unique_object(pairs):
                result={}
                for key,value in pairs:
                    if key in result:raise ValueError
                    result[key]=value
                return result
            def invalid_constant(value):raise ValueError
            data=json.loads(body,object_pairs_hook=unique_object,parse_constant=invalid_constant)
            if not isinstance(data,dict) or set(data)!={'confirm_suspension'} or data['confirm_suspension'] is not True:
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400,detail='Invalid customer suspension request.') from None
        try:
            from app.domain.admin_customers import customer_identifier
            identifier=customer_identifier(customer_id)
            if suspension_service is None:raise RuntimeError
            result=await run_in_threadpool(suspension_service.suspend,identifier,administrator)
        except InvalidCustomerIdentifier:
            raise HTTPException(status_code=400,detail='Invalid customer identifier.') from None
        except CustomerSuspensionConflict:
            raise HTTPException(status_code=409,detail='Customer suspension preconditions not satisfied.') from None
        except Exception:
            raise HTTPException(status_code=503,detail='Customer suspension not confirmed.') from None
        if result is None:raise HTTPException(status_code=404,detail='Customer not found.')
        return result

    return router
