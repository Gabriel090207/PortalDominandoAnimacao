import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from pydantic import ValidationError
from app.domain.email import normalize_email
from app.domain.models import Entitlement, UserAccessState
from app.domain.states import AccountStatus, ActivationStatus, EntitlementStatus, ResourceKey
from app.domain import policies
from app.persistence.collections import CollectionName
from app.persistence.firestore import get_collection_reference
from app.services.access_service import can_access_portal


class FoundationTests(unittest.TestCase):
    def test_email(self):
        self.assertEqual(normalize_email(' First.Last+Alias@EXAMPLE.COM '),'first.last+alias@example.com')
        self.assertEqual(normalize_email(normalize_email('User@example.com')),'user@example.com')
        for value in ['', 'invalid', 'a b@example.com', None]:
            with self.assertRaises(ValueError): normalize_email(value)
        with self.assertRaises(ValueError): normalize_email('a@example.com',version=2)

    def test_access(self):
        now=datetime(2026,1,1,tzinfo=timezone.utc)
        user=UserAccessState(account_status=AccountStatus.ENABLED,activation_status=ActivationStatus.ACTIVE)
        right=Entitlement(user_id='u',resource_key=ResourceKey.PORTAL,status=EntitlementStatus.GRANTED,valid_from=now,valid_until=now+timedelta(days=30))
        def access(rights, instant=now, state=user):
            return can_access_portal('u',state,rights,now=instant)
        self.assertTrue(access([right]))
        self.assertFalse(access([]))
        self.assertFalse(access([right],now-timedelta(seconds=1)))
        self.assertFalse(access([right],right.valid_until))
        self.assertEqual(user.activation_status,ActivationStatus.ACTIVE)
        revoked=right.model_copy(update={'status':EntitlementStatus.REVOKED})
        self.assertFalse(access([revoked]))
        self.assertTrue(access([revoked,right]))
        self.assertFalse(access([right.model_copy(update={'user_id':'other'})]))
        for field,value in [('account_status',AccountStatus.BLOCKED),('activation_status',ActivationStatus.PENDING),('activation_status',ActivationStatus.SUSPENDED)]:
            self.assertFalse(access([right],state=user.model_copy(update={field:value})))
        with self.assertRaises(ValueError): access([right],datetime(2026,1,1))
        with self.assertRaises(ValidationError): Entitlement(user_id='u',resource_key=ResourceKey.PORTAL,status=EntitlementStatus.GRANTED,valid_from=now,valid_until=now)

    def test_reference_no_writes(self):
        client=Mock()
        with patch('app.persistence.firestore.get_firestore_client',return_value=client):
            self.assertIs(get_collection_reference(CollectionName.USERS),client.collection.return_value)
            client.collection.assert_called_once_with('users')
            self.assertEqual(len(client.mock_calls),1)
            with self.assertRaises(ValueError): get_collection_reference('unknown')

    def test_policies(self):
        self.assertEqual((policies.LOGIN_CODE_LENGTH,policies.LOGIN_MAX_ATTEMPTS,policies.MAX_ACTIVE_USER_SESSIONS),(6,5,1))
        self.assertEqual(policies.LOGIN_CHALLENGE_LIFETIME,timedelta(minutes=10))
        self.assertEqual(policies.LOGIN_RESEND_COOLDOWN,timedelta(seconds=60))
        self.assertEqual(policies.USER_SESSION_LIFETIME,timedelta(hours=8))
        self.assertEqual(policies.ADMIN_SESSION_LIFETIME,timedelta(hours=8))
