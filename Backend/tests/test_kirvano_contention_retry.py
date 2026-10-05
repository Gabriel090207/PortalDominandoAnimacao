"""No network: actual SDK exception chain and bounded outer retry."""
from unittest.mock import Mock, patch
import pytest
from google.api_core.exceptions import Aborted
from google.cloud import firestore
from app.persistence import kirvano_commerce_repository as repo


def exhausted_sdk_error():
    # Execute installed SDK retry/exception machinery without any RPC.
    transaction = Mock(_read_only=False, _max_attempts=5, _id=b'synthetic')
    transaction._commit.side_effect = Aborted('Synthetic contention')
    with pytest.raises(ValueError) as caught:
        firestore.transactional(lambda tx: None)(transaction)
    assert transaction._commit.call_count == 5
    assert isinstance(caught.value.__cause__, Aborted)
    assert caught.value.__context__ is None
    assert caught.value.args == ('Failed to commit transaction in 5 attempts.',)
    return caught.value


def test_actual_sdk_chain_and_retry_success_fresh_transactions():
    error = exhausted_sdk_error()
    client = Mock()
    first, second = Mock(), Mock()
    client.transaction.side_effect = [first, second]
    runner = Mock(side_effect=[error, 'success'])
    inputs = (Mock(), Mock(), Mock(), 'fixed-synthetic-user')
    with patch.object(repo, 'get_firestore_client', return_value=client), \
         patch.object(repo.firestore, 'transactional', return_value=runner) as decorator, \
         patch.object(repo, '_wait_before_transaction_retry') as wait:
        assert repo.record_commercial_event(*inputs) == 'success'
    assert decorator.call_count == 2
    assert client.transaction.call_count == 2
    assert runner.call_args_list[0].args == (first, client, *inputs)
    assert runner.call_args_list[1].args == (second, client, *inputs)
    wait.assert_called_once_with(0)


def test_limit_three_executions():
    error = exhausted_sdk_error()
    client = Mock()
    runner = Mock(side_effect=error)
    with patch.object(repo, 'get_firestore_client', return_value=client), \
         patch.object(repo.firestore, 'transactional', return_value=runner), \
         patch.object(repo, '_wait_before_transaction_retry') as wait:
        with pytest.raises(ValueError) as caught:
            repo.record_commercial_event(None, None, None, 'fixed-user')
    assert caught.value is error
    assert runner.call_count == client.transaction.call_count == 3
    assert [call.args for call in wait.call_args_list] == [(0,), (1,)]


@pytest.mark.parametrize('error', [RuntimeError('Invalid storage structure'),
                                 LookupError('Unknown failure'),
                                 ValueError('Failed to commit transaction in 5 attempts.')])
def test_nontransient_errors_never_retry(error):
    client = Mock()
    runner = Mock(side_effect=error)
    with patch.object(repo, 'get_firestore_client', return_value=client), \
         patch.object(repo.firestore, 'transactional', return_value=runner), \
         patch.object(repo, '_wait_before_transaction_retry') as wait:
        with pytest.raises(type(error)) as caught:
            repo.record_commercial_event(None, None, None, 'fixed-user')
    assert caught.value is error
    assert runner.call_count == client.transaction.call_count == 1
    wait.assert_not_called()


def test_classifier_uses_only_explicit_recognized_cause():
    assert repo._is_retryable_contention(Aborted('Synthetic'))
    error = ValueError('Unrelated')
    error.__context__ = Aborted('Synthetic')
    assert not repo._is_retryable_contention(error)
    wrapper = RuntimeError('Domain')
    wrapper.__cause__ = Aborted('Synthetic')
    assert not repo._is_retryable_contention(wrapper)


@pytest.mark.parametrize('retry,base', [(0, 0.05), (1, 0.1), (10, 0.1)])
def test_backoff_controlled_and_capped(retry, base):
    for fraction in (0.0, 1.0):
        with patch.object(repo.random, 'uniform', return_value=base*fraction) as jitter, \
             patch.object(repo.time, 'sleep') as sleep:
            repo._wait_before_transaction_retry(retry)
        jitter.assert_called_once_with(0.0, base)
        sleep.assert_called_once_with(min(base*(1+fraction), 0.2))


def test_review_result_returns_without_retry():
    review = Mock(business_status='review_required')
    runner = Mock(return_value=review)
    with patch.object(repo, 'get_firestore_client'), \
         patch.object(repo.firestore, 'transactional', return_value=runner), \
         patch.object(repo, '_wait_before_transaction_retry') as wait:
        assert repo.record_commercial_event(None, None, None, 'fixed-user') is review
    assert runner.call_count == 1
    wait.assert_not_called()
