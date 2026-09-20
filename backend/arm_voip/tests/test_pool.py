import pytest

from arm_voip.pool import OperatorPool, PoolExhausted, sip_password


def test_acquire_gives_distinct_numbers_and_is_idempotent():
    pool = OperatorPool(["2001", "2002"])
    first = pool.acquire("attempt-1")
    assert pool.acquire("attempt-1") == first
    assert pool.acquire("attempt-2") != first


def test_pool_exhausted_and_release():
    pool = OperatorPool(["2001"])
    ext = pool.acquire("a")
    with pytest.raises(PoolExhausted):
        pool.acquire("b")
    pool.release(ext)
    assert pool.acquire("b") == ext


def test_lease_expires():
    now = [0.0]
    pool = OperatorPool(["2001"], ttl_sec=10, clock=lambda: now[0])
    pool.acquire("a")
    now[0] = 11
    assert pool.stats()["busy"] == 0
    assert pool.acquire("b") == "2001"


def test_passwords_are_per_extension_and_stable():
    assert sip_password("s", "2001") == sip_password("s", "2001")
    assert sip_password("s", "2001") != sip_password("s", "2002")
    assert sip_password("s", "2001") != sip_password("other", "2001")
