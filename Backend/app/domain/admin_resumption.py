"""Manual resumption result and audit; no new commercial grants."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, AwareDatetime
from app.domain.states import ActivationStatus


class CustomerResumptionResult(BaseModel):
    model_config=ConfigDict(frozen=True,extra='forbid',hide_input_in_errors=True)
    customer_id:str
    activation_status:Literal[ActivationStatus.ACTIVE]=ActivationStatus.ACTIVE
    result:Literal['resumed','already_active']


class CustomerResumptionAudit(BaseModel):
    model_config=ConfigDict(frozen=True,extra='forbid',hide_input_in_errors=True)
    schema_version:Literal[1]=1
    admin_id:str
    customer_id:str
    operation:Literal['resume_customer']='resume_customer'
    previous_activation_status:Literal[ActivationStatus.SUSPENDED]=ActivationStatus.SUSPENDED
    activation_status:Literal[ActivationStatus.ACTIVE]=ActivationStatus.ACTIVE
    human_confirmation:Literal[True]=True
    occurred_at:AwareDatetime


class CustomerResumptionConflict(RuntimeError):
    def __init__(self):super().__init__('Customer resumption preconditions not satisfied.')


class CustomerResumptionUnavailable(RuntimeError):
    def __init__(self):super().__init__('Customer resumption not confirmed.')
