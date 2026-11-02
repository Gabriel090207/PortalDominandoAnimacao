"""Explicit production startup parsing. No initialization, env writes or defaults."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import ipaddress

from dotenv import dotenv_values
from app.config.admin_admission import AdminAdmissionConfig,load_admin_admission_config
from app.config.admin_admission_policy import load_admin_admission_policy
from app.config.admin_http_security import AdminRequestSecurityConfig,validate_origin
from app.domain.admin_admission import ComplementaryAdminAdmissionPolicy

_ENV_FILE=Path(__file__).resolve().parents[2]/'.env'
_FORBIDDEN=('FIRESTORE_EMULATOR_HOST','DATASTORE_EMULATOR_HOST','FIRESTORE_TEST_PROJECT_ID')


class AdminStartupConfigurationError(RuntimeError):
    def __init__(self):super().__init__('Administrative startup configuration unavailable.')


@dataclass(frozen=True,repr=False)
class AdminStartupSettings:
    security_config: AdminRequestSecurityConfig
    api_origin: str
    admission_config: AdminAdmissionConfig
    policy: ComplementaryAdminAdmissionPolicy
    project_id: str


def _production_origin(value):
    value=validate_origin(value)
    host=urlsplit(value).hostname
    if host=='localhost' or host.endswith(('.localhost','.local')) or '.' not in host:
        raise ValueError
    try:ipaddress.ip_address(host)
    except ValueError:return value
    raise ValueError


def reject_test_environment(environment):
    if any(name in environment for name in _FORBIDDEN):
        raise AdminStartupConfigurationError()


def load_admin_startup_settings(*,environ=None,env_file=_ENV_FILE):
    """Process-only mode opt-in. Other fields may come from read-only .env.

    Never falls back from an explicitly invalid process value. No secret values
    are placed in errors. Schema and four-bucket validation reuse existing code.
    """
    env=os.environ if environ is None else environ
    if 'ADMIN_HTTP_MODE' not in env or env['ADMIN_HTTP_MODE']=='disabled':return None
    try:
        if env['ADMIN_HTTP_MODE']!='public-authenticated':raise ValueError
        values=dict(dotenv_values(env_file,interpolate=False)) if env_file is not None else {}
        values.update(env)
        reject_test_environment(values)
        if values.get('ADMIN_HTTP_ENVIRONMENT')!='production':raise ValueError
        admin_origin=_production_origin(values.get('ADMIN_HTTP_ORIGIN'))
        api_origin=_production_origin(values.get('ADMIN_API_ORIGIN'))
        if admin_origin==api_origin:raise ValueError
        project=values.get('FIREBASE_PROJECT_ID')
        if not isinstance(project,str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]',project) or project.startswith('demo-'):
            raise ValueError
        for name in ('GOOGLE_CLOUD_PROJECT','GCLOUD_PROJECT','GCP_PROJECT'):
            if name in values and values[name]!=project:raise ValueError
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError
                result[key]=value
            return result
        def invalid_constant(value):raise ValueError
        payload=json.loads(values.get('ADMIN_ADMISSION_POLICY_CONFIG',''),object_pairs_hook=unique,parse_constant=invalid_constant)
        policy=load_admin_admission_policy(selection='configured-v1',configuration=payload)
        hmac=load_admin_admission_config(environ=values,env_file=None)
        return AdminStartupSettings(AdminRequestSecurityConfig((admin_origin,)),api_origin,hmac,policy,project)
    except Exception:
        raise AdminStartupConfigurationError() from None
