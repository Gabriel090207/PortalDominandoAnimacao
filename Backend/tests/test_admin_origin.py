"""Synthetic ASGI headers only. No HTTP server, network or Firebase."""
import pytest
from starlette.requests import Request

from app.api.admin_origin import resolve_cf_connecting_ip, AdminOriginResolutionError


@pytest.mark.parametrize("value,canonical", [
    ("192.0.2.123", "192.0.2.123"),
    ("2001:db8::1", "2001:db8::1"),
    ("2001:0DB8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
    ("::ffff:192.0.2.123", "192.0.2.123"),
    ("0:0:0:0:0:FFFF:C000:027B", "192.0.2.123"),
    (" \t192.0.2.123\t ", "192.0.2.123"),
    ("::1", "::1"),
    ("2001:db8::1:443", "2001:db8::1:443"),
])
@pytest.mark.parametrize("name", [b"cf-connecting-ip", b"CF-CONNECTING-IP", b"Cf-Connecting-Ip"])
def test_valid_addresses_and_case_insensitive_name(value, canonical, name):
    assert resolve_cf_connecting_ip([(name, value.encode("ascii"))]) == canonical


@pytest.mark.parametrize("value", [
    b"", b" ", b"\t", b"999.0.2.1", b"192.0.2", b"192.000.002.001",
    b"example.com", b"2001:db8:::1", b"2001:xyz::1", b"192.0.2.1, 198.51.100.1",
    b"192.0.2.1 198.51.100.1", b"192.0.2.1:443", b"[2001:db8::1]:443",
    b"[2001:db8::1]", b"fe80::1%eth0", b"fe80::1%25eth0", b"192.0.2.1/24",
    b"\r\n192.0.2.1", b"192.0.2.1\n", b"192.0.2.1\x00", b"\xff",
    b"x"*129,
])
def test_invalid_values_are_sanitized(value, capsys, caplog):
    with pytest.raises(AdminOriginResolutionError) as caught:
        resolve_cf_connecting_ip([(b"cf-connecting-ip", value)])
    assert str(caught.value) == "Administrative origin could not be resolved."
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    output = capsys.readouterr()
    assert output.out == output.err == caplog.text == ""


@pytest.mark.parametrize("second_name", [b"cf-connecting-ip", b"CF-Connecting-IP"])
@pytest.mark.parametrize("values", [(b"192.0.2.1", b"192.0.2.1"),
    (b"192.0.2.1", b"198.51.100.1"), (b"", b"192.0.2.1")])
def test_duplicates_always_rejected(second_name, values):
    with pytest.raises(AdminOriginResolutionError):
        resolve_cf_connecting_ip([(b"cf-connecting-ip", values[0]), (second_name, values[1])])


@pytest.mark.parametrize("headers", [[], [(b"x-forwarded-for", b"192.0.2.1")],
    [(b"x-real-ip", b"192.0.2.1")], [(b"cf-connecting-ip", b"invalid"), (b"x-forwarded-for", b"192.0.2.1")],
    [(b"cf-connecting-ip", b""), (b"x-real-ip", b"192.0.2.1")]])
def test_no_fallback_even_with_request_client(headers):
    request = Request({"type":"http", "headers":headers, "client":("192.0.2.99", 12345)})
    with pytest.raises(AdminOriginResolutionError):
        resolve_cf_connecting_ip(request.scope["headers"])


@pytest.mark.parametrize("headers", [None, {}, {"cf-connecting-ip":"192.0.2.1"},
    "cf-connecting-ip", [("cf-connecting-ip", "192.0.2.1")], [(b"cf-connecting-ip", None)],
    [(b"cf-connecting-ip",)], [(b"cf-connecting-ip", b"192.0.2.1", b"extra")]])
def test_requires_raw_asgi_pairs(headers):
    with pytest.raises(AdminOriginResolutionError): resolve_cf_connecting_ip(headers)


def test_other_forwarded_headers_never_override_cf():
    assert resolve_cf_connecting_ip([(b"x-forwarded-for", b"198.51.100.66"),
        (b"x-real-ip", b"198.51.100.66"), (b"cf-connecting-ip", b"192.0.2.1")]) == "192.0.2.1"


def test_syntactically_valid_forgery_cannot_be_detected_by_parser(capsys, caplog):
    # The exact same bytes could be supplied by a caller or a trusted edge.
    # Accepting syntax must NOT be described as authenticating the source.
    forged = [(b"cf-connecting-ip", b"192.0.2.66")]
    assert resolve_cf_connecting_ip(forged) == "192.0.2.66"
    output = capsys.readouterr()
    assert output.out == output.err == caplog.text == ""


def test_errors_never_expose_headers_or_parser_details():
    private = b"SYNTHETIC_PRIVATE_TOKEN password=synthetic hash=synthetic"
    with pytest.raises(AdminOriginResolutionError) as caught:
        resolve_cf_connecting_ip([(b"authorization", private), (b"cf-connecting-ip", private)])
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)+repr(caught.value)
    assert "password=" not in str(caught.value)


def test_raw_request_preserves_case_variant_duplicates():
    request = Request({"type":"http", "headers":[(b"CF-Connecting-IP", b"192.0.2.1"),
        (b"cf-connecting-ip", b"192.0.2.1")]})
    with pytest.raises(AdminOriginResolutionError): resolve_cf_connecting_ip(request.scope["headers"])
