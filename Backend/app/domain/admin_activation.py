"""Explicit manual activation result and durable audit, no access grants."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, AwareDatetime
from app.domain.states import ActivationStatus


class CustomerActivationResult(BaseModel):
    model_config=ConfigDict(frozen=True,extra='forbid',hide_input_in_errors=True)
    customer_id:str
    activation_status:Literal[ActivationStatus.ACTIVE]=ActivationStatus.ACTIVE
    result:Literal['activated','already_active']


class CustomerActivationAudit(BaseModel):
    model_config=ConfigDict(frozen=True,extra='forbid',hide_input_in_errors=True)
    schema_version:Literal[1]=1
    admin_id:str
    customer_id:str
    operation:Literal['activate_customer']='activate_customer'
    previous_activation_status:Literal[ActivationStatus.PENDING]=ActivationStatus.PENDING
    activation_status:Literal[ActivationStatus.ACTIVE]=ActivationStatus.ACTIVE
    human_confirmation:Literal[True]=True
    occurred_at:AwareDatetime


class CustomerActivationConflict(RuntimeError):
    def __init__(self):super().__init__('Customer activation preconditions not satisfied.')


class CustomerActivationUnavailable(RuntimeError):
    def __init__(self):super().__init__('Customer activation not confirmed.')
