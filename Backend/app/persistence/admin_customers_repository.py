"""Bounded customer and purchase-evidence reads; no writes or client creation."""
from app.domain.admin_customers import AdminCustomer, AdminCustomerPage, customer_pagination, encode_customer_cursor, validate_document_id, customer_identifier, InvalidCustomerLookup, AmbiguousCustomerLookup
from google.cloud.firestore_v1.base_query import FieldFilter
from app.domain.states import CommercialStatus
# Reuse the existing pure persisted-commerce validator; no event processing.
from app.persistence.kirvano_commerce_repository import _validate_stored
from app.domain.email import normalize_email
from app.persistence.collections import CollectionName

_FIELDS = ('schema_version','email_normalized','email_normalization_version','account_status','activation_status','created_at')


def _project_customer(snapshot):
    document=snapshot.to_dict()
    if (type(document.get('schema_version')) is not int or document['schema_version']!=1 or
        type(document.get('email_normalization_version')) is not int):
        raise ValueError
    email=normalize_email(document['email_normalized'],version=document['email_normalization_version'])
    if email!=document['email_normalized']:
        raise ValueError
    return AdminCustomer(customer_id=validate_document_id(snapshot.id),email=email,
        account_status=document['account_status'],activation_status=document['activation_status'],created_at=document['created_at'])


class AdminCustomersUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Administrative customer query unavailable.')


class AdminCustomersRepository:
    def __init__(self, client):
        self.client=client

    def list_page(self, *, limit=20, cursor=None):
        limit, after = customer_pagination(limit,cursor)
        try:
            collection=self.client.collection(CollectionName.USERS.value)
            query=collection.select(_FIELDS).order_by('__name__')
            if after is not None:
                query=query.start_after({'__name__':collection.document(after)})
            snapshots=list(query.limit(limit+1).stream(timeout=10))
            if len(snapshots)>limit+1:
                raise ValueError
            items=[_project_customer(snapshot) for snapshot in snapshots[:limit]]
            next_cursor=encode_customer_cursor(snapshots[limit-1].id) if len(snapshots)>limit else None
            return AdminCustomerPage(items=items,next_cursor=next_cursor)
        except Exception:
            raise AdminCustomersUnavailable() from None


    def get_by_id(self, customer_id):
        identifier=customer_identifier(customer_id)
        try:
            ref=self.client.collection(CollectionName.USERS.value).document(identifier)
            snapshot=ref.get(field_paths=_FIELDS,timeout=10)
            if not snapshot.exists:
                return None
            if snapshot.id!=identifier:
                raise ValueError
            return _project_customer(snapshot)
        except Exception:
            raise AdminCustomersUnavailable() from None

    def has_approved_purchase(self, customer_id):
        identifier=customer_identifier(customer_id)
        try:
            query=self.client.collection(CollectionName.PURCHASES.value).where(
                filter=FieldFilter('user_id','==',identifier)).where(
                filter=FieldFilter('status','==',CommercialStatus.ACTIVE.value))
            fields=('schema_version','identity_version','source_scope','subscription_id','user_id',
                'charge_number','product_id','offer_id','status','valid_from','valid_until',
                'origin_event_id','origin_fingerprint','created_at')
            snapshots=list(query.select(fields).limit(1).stream(timeout=10))
            if len(snapshots)>1:
                raise ValueError
            if not snapshots:
                return False
            data=snapshots[0].to_dict()
            _validate_stored(CollectionName.PURCHASES,data)
            if data['user_id']!=identifier or data['status']!=CommercialStatus.ACTIVE.value:
                raise ValueError
            return True
        except Exception:
            raise AdminCustomersUnavailable() from None

    def find_by_email(self, email):
        try:
            normalized=normalize_email(email)
        except ValueError:
            raise InvalidCustomerLookup() from None
        try:
            query=self.client.collection(CollectionName.USERS.value).where(
                filter=FieldFilter('email_normalized','==',normalized)).select(_FIELDS).limit(2)
            snapshots=list(query.stream(timeout=10))
            if len(snapshots)>1:
                raise AmbiguousCustomerLookup()
            if not snapshots:
                return None
            customer=_project_customer(snapshots[0])
            if customer.email!=normalized:
                raise ValueError
            return customer
        except AmbiguousCustomerLookup:
            raise
        except Exception:
            raise AdminCustomersUnavailable() from None
