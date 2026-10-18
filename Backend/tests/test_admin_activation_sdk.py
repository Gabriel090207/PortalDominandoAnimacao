"""Installed SDK behavior, not an invented external retry policy."""
from unittest.mock import Mock
import pytest
from google.api_core.exceptions import Aborted,DeadlineExceeded
from google.cloud.firestore_v1.transaction import _Transactional


def transaction(max_attempts=5):
    return Mock(_max_attempts=max_attempts,_read_only=False,_id=b'synthetic')


@pytest.mark.parametrize('error',[Aborted('synthetic'),DeadlineExceeded('synthetic')])
def test_sdk_does_not_retry_callback_read_errors(error):
    tx=transaction();callback=Mock(side_effect=error)
    with pytest.raises(type(error)):_Transactional(callback)(tx)
    assert callback.call_count==1
    tx._commit.assert_not_called();tx._rollback.assert_called_once()


def test_sdk_retries_explicit_commit_abort():
    tx=transaction();callback=Mock(return_value='result')
    tx._commit.side_effect=[Aborted('synthetic'),None]
    assert _Transactional(callback)(tx)=='result'
    assert callback.call_count==2 and tx._commit.call_count==2


@pytest.mark.parametrize('attempts',[5,8])
def test_sdk_exhaustion_wraps_commit_aborted_at_native_limit(attempts):
    tx=transaction(attempts);callback=Mock(return_value='result');tx._commit.side_effect=Aborted('synthetic')
    with pytest.raises(ValueError) as error:_Transactional(callback)(tx)
    assert isinstance(error.value.__cause__,Aborted)
    assert callback.call_count==attempts and tx._commit.call_count==attempts


def test_sdk_does_not_retry_uncertain_commit_timeout():
    tx=transaction();callback=Mock(return_value='result');tx._commit.side_effect=DeadlineExceeded('synthetic')
    with pytest.raises(DeadlineExceeded):_Transactional(callback)(tx)
    assert callback.call_count==1 and tx._commit.call_count==1


@pytest.mark.parametrize('error',[ValueError('synthetic Aborted text'),RuntimeError('synthetic'),DeadlineExceeded('synthetic')])
def test_eight_attempt_budget_does_not_retry_unclassified_commit(error):
    tx=transaction(8);callback=Mock(return_value='result');tx._commit.side_effect=error
    with pytest.raises(type(error)):_Transactional(callback)(tx)
    assert callback.call_count==1 and tx._commit.call_count==1


def test_eight_attempt_budget_recovers_later_native_commit_abort():
    tx=transaction(8);callback=Mock(return_value='result')
    tx._commit.side_effect=[Aborted('synthetic')]*7+[None]
    assert _Transactional(callback)(tx)=='result'
    assert callback.call_count==8 and tx._commit.call_count==8


@pytest.mark.parametrize('error',[Aborted('synthetic'),DeadlineExceeded('synthetic'),ValueError('Aborted')])
def test_eight_attempt_budget_does_not_retry_callback_error(error):
    tx=transaction(8);callback=Mock(side_effect=error)
    with pytest.raises(type(error)):_Transactional(callback)(tx)
    assert callback.call_count==1
    tx._commit.assert_not_called()
