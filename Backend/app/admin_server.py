"""Future Uvicorn --factory entry. Importing does not load config or Firebase."""
import os
from urllib.parse import urlsplit
from starlette.responses import JSONResponse

from app.admin_entrypoint import create_admin_entrypoint,PublicAdminEntryConfiguration
from app.config.admin_startup import load_admin_startup_settings,reject_test_environment,_ENV_FILE


class _APIOriginHost:
    """Restricts only the Admin branch; public webhook host contracts untouched."""
    def __init__(self,app,origin):
        self.app,self.host=app,urlsplit(origin).netloc.encode('ascii')

    async def __call__(self,scope,receive,send):
        hosts=[value for name,value in scope.get('headers',[]) if name.lower()==b'host']
        if hosts!=[self.host]:
            if scope['type']=='websocket':
                return await send({'type':'websocket.close','code':1008})
            return await JSONResponse({'detail':'Administrative entry unavailable.'},status_code=503,
                headers={'Cache-Control':'no-store'})(scope,receive,send)
        await self.app(scope,receive,send)


def create_app(*,environ=None,env_file=_ENV_FILE,firestore_client_factory=None,
               public_app=None,welcome_installation=None):
    """Call once per worker. Dependency overrides are for isolated tests only.

    No module-level app. Invalid admin setup preserves the public entry unchanged.
    Existing Firebase service owns/caches the supplied client; do not close it
    independently while the public webhook may still use it.
    """
    if welcome_installation is not None:
        if public_app is None:
            from app.main import create_app as create_public_app
            public_app=create_public_app(welcome_installation=welcome_installation)
        else:
            from app.services.purchase_welcome_runtime import prepare_purchase_welcome_runtime
            prepare_purchase_welcome_runtime(public_app,welcome_installation)
    disabled=create_admin_entrypoint(public_app=public_app)
    try:
        settings=load_admin_startup_settings(environ=environ,env_file=env_file)
        if settings is None:return disabled
        if firestore_client_factory is None:
            from app.services.firebase_service import get_firestore_client
            firestore_client_factory=get_firestore_client
        client=firestore_client_factory()
        # Firebase's existing loader can populate process .env during initialization.
        # Recheck effective process and client bindings before composing any router.
        reject_test_environment(os.environ if environ is None else environ)
        if (client.project!=settings.project_id or client.project.startswith('demo-') or
            client._database!='(default)' or client._emulator_host is not None):
            return disabled
        entry=create_admin_entrypoint(admin_configuration=PublicAdminEntryConfiguration(
            client,settings.admission_config,settings.security_config,settings.policy),
            public_app=disabled.public_app)
        if entry.composition is None:return disabled
        entry.admin_app=_APIOriginHost(entry.admin_app,settings.api_origin)
        return entry
    except Exception:
        return disabled
