"""Read-only customer projection and pagination; no commercial/access changes."""
import base64
import re
import unicodedata
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict
from app.domain.states import AccountStatus, ActivationStatus


class InvalidCustomerPagination(ValueError):
    def __init__(self):
        super().__init__('Invalid customer pagination.')


class InvalidCustomerIdentifier(ValueError):
    def __init__(self):
        super().__init__('Invalid customer identifier.')


def customer_identifier(value):
    try:
        return validate_document_id(value)
    except Exception:
        raise InvalidCustomerIdentifier() from None


class AdminCustomer(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', hide_input_in_errors=True)
    customer_id: str
    email: str
    account_status: AccountStatus
    activation_status: ActivationStatus
    created_at: AwareDatetime


class AdminCustomerPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', hide_input_in_errors=True)
    items: list[AdminCustomer]
    next_cursor: str | None


def validate_document_id(value):
    if (not isinstance(value,str) or not value or '/' in value or value in ('.','..') or
        any(unicodedata.category(char) == 'Cc' for char in value) or
        re.fullmatch(r'__.*__',value) or len(value.encode('utf-8')) > 1500):
        raise ValueError
    return value


def encode_customer_cursor(document_id):
    return base64.urlsafe_b64encode(validate_document_id(document_id).encode('utf-8')).decode('ascii').rstrip('=')


def customer_pagination(limit, cursor):
    try:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError
        if cursor is None:
            return limit,None
        if not isinstance(cursor,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,2000}',cursor):
            raise ValueError
        identifier=validate_document_id(base64.b64decode(cursor+'='*(-len(cursor)%4),altchars=b'-_',validate=True).decode('utf-8'))
        if encode_customer_cursor(identifier) != cursor:
            raise ValueError
        return limit,identifier
    except Exception:
        raise InvalidCustomerPagination() from None


class AdminPurchaseConfirmation(BaseModel):
    """Stored active approval evidence only; never an access or payment grant."""
    model_config = ConfigDict(frozen=True, extra='forbid', hide_input_in_errors=True)
    customer_id: str
    approved_purchase_recorded: bool
    current_payment_validity: Literal['not_verified'] = 'not_verified'
    requires_kirvano_review: Literal[True] = True


class InvalidCustomerLookup(ValueError):
    def __init__(self):
        super().__init__('Invalid customer lookup.')


class AmbiguousCustomerLookup(RuntimeError):
    def __init__(self):
        super().__init__('Customer lookup is ambiguous.')
