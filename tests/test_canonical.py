"""Tests for harness.canonical — covers the I/O Matrix in the 1.2 plan."""

from __future__ import annotations

import pytest

from harness.canonical import canonical_bytes, canonical_sha256


# --- Happy paths ---

def test_json_dict_key_ordering_invariant():
    assert canonical_bytes({"b": 1, "a": 2}) == canonical_bytes({"a": 2, "b": 1})


def test_json_list_has_no_whitespace():
    assert canonical_bytes([1, 2, 3]) == b"[1,2,3]"


def test_text_canonicalization_lf_and_trailing():
    assert canonical_bytes("hello\r\nworld") == b"hello\nworld\n"


def test_binary_passthrough():
    assert canonical_bytes(b"\x00\x01\x02") == b"\x00\x01\x02"


# --- Edges ---

def test_empty_text_has_no_trailing_lf():
    assert canonical_bytes("") == b""


def test_nfc_normalization_collapses_equivalent_strings():
    # Build NFD explicitly via unicodedata to defeat Python 3.14 PEP 686 source-level NFC.
    import unicodedata
    nfc_form = unicodedata.normalize("NFC", "e\u0301")  # 'é' (NFC, 1 codepoint)
    nfd_form = unicodedata.normalize("NFD", nfc_form)  # 'e' + U+0301 (NFD, 2 codepoints)
    assert len(nfc_form) == 1
    assert len(nfd_form) == 2
    assert canonical_bytes(nfc_form) == canonical_bytes(nfd_form)


# --- Errors ---

def test_int_raises_with_type_name_in_message():
    with pytest.raises(TypeError, match="int"):
        canonical_bytes(42)


def test_custom_object_raises_type_error():
    with pytest.raises(TypeError):
        canonical_bytes(object())


# --- Bonus: canonical_sha256 surface ---

def test_canonical_sha256_returns_sha256_prefixed_hex():
    out = canonical_sha256({"a": 1})
    assert out.startswith("sha256:")
    hex_part = out.split(":", 1)[1]
    assert len(hex_part) == 64
    int(hex_part, 16)  # parses as hex


def test_canonical_sha256_empty_bytes_known_answer():
    # sha256("") is the well-known empty-input digest; this pins the prefix
    # format and protects against accidental drift in canonical_bytes("").
    expected = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert canonical_sha256(b"") == expected
