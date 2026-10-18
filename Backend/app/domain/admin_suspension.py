"""Manual suspension response and audit using existing activation states."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, AwareDatetime
from app.domain.states import ActivationStatus


class CustomerSuspensionResult(BaseModel):
    model_config=ConfigDict(frozen=True,extra='forbid',hide_input_in_errors=True)
    customer_id:str
    activation_status:Literal[ActivationStatus.SUSPENDED]=ActivationStatus.SUSPENDED
    result:Literal['suspended','already_suspended']


class CustomerSuspensionAudit(BaseModel):
    model_config=ConfigDict(frozen=True,extra='forbid',hide_input_in_errors=True)
    schema_version:Literal[1]=1
    admin_id:str
    customer_id:str
    operation:Literal['suspend_customer']='suspend_customer'
    previous_activation_status:Literal[ActivationStatus.ACTIVE]=ActivationStatus.ACTIVE
    activation_status:Literal[ActivationStatus.SUSPENDED]=ActivationStatus.SUSPENDED
    human_confirmation:Literal[True]=True
    occurred_at:AwareDatetime


class CustomerSuspensionConflict(RuntimeError):
    def __init__(self):super().__init__('Customer suspension preconditions not satisfied.')


class CustomerSuspensionUnavailable(RuntimeError):
    def __init__(self):super().__init__('Customer suspension not confirmed.')
