from __future__ import annotations

import pytest

from archx_agent.helpers.exceptions import (
    PathEscapesRootError,
    RateLimitedError,
    ModelNotFoundError,
    PROVIDER_ERROR_MAP,
)
from archx_agent.helpers.paths import (
    child_path,
    ensure_directory,
    is_within,
    resolve_within,
    safe_filename,
)
from archx_agent.helpers.result import Err, Ok, Result, WriteOutcome


class TestResult:
    def test_ok_holds_value(self):
        r = Ok(5)
        assert r.is_ok and r.value == 5 and bool(r)

    def test_err_raises_on_value(self):
        r = Err(ValueError("boom"))
        assert r.is_err and not r
        with pytest.raises(ValueError):
            _ = r.value

    def test_requires_exactly_one(self):
        with pytest.raises(ValueError):
            Result()
        with pytest.raises(ValueError):
            Result(value=1, error=ValueError("x"))

    def test_map_and_bind(self):
        assert Ok(2).map(lambda x: x * 3).value == 6
        assert Err(ValueError("e")).map(lambda x: x * 3).is_err
        assert Ok(2).bind(lambda x: Ok(x + 1)).value == 3
        assert Ok(2).bind(lambda x: Err(ValueError("e"))).is_err

    def test_map_captures_exception(self):
        r = Ok(1).map(lambda x: 1 / 0)
        assert r.is_err and isinstance(r.error, ZeroDivisionError)

    def test_unwrap_or(self):
        assert Err(ValueError("e")).unwrap_or(7) == 7

    def test_none_payload_is_allowed(self):
        r: Result[None] = Ok(None)
        assert r.is_ok and r.value is None

    def test_equality(self):
        assert Ok(1) == Ok(1)
        assert Ok(1) != Ok(2)
        assert Err(ValueError("a")) != Ok(1)

    def test_write_outcome_semantics(self):
        assert WriteOutcome.COMMITTED.is_success
        assert WriteOutcome.DUPLICATE.is_success
        assert not WriteOutcome.PENDING.is_success
        assert not WriteOutcome.FAILED.is_success


class TestPaths:
    def test_child_path_happy(self, tmp_path):
        root = ensure_directory(tmp_path / "root")
        p = child_path(root, "a", "b.txt")
        assert p == root / "a" / "b.txt"

    def test_traversal_rejected(self, tmp_path):
        root = ensure_directory(tmp_path / "root")
        with pytest.raises(PathEscapesRootError):
            child_path(root, "..", "escape.txt")
        with pytest.raises(PathEscapesRootError):
            child_path(root, "../escape.txt")
        with pytest.raises(PathEscapesRootError):
            child_path(root, "a/../../escape.txt")

    def test_absolute_outside_rejected(self, tmp_path):
        root = ensure_directory(tmp_path / "root")
        outside = tmp_path / "outside.txt"
        with pytest.raises(PathEscapesRootError):
            resolve_within(root, outside)

    def test_symlink_escape_rejected(self, tmp_path):
        root = ensure_directory(tmp_path / "root")
        outside_dir = ensure_directory(tmp_path / "outside")
        (outside_dir / "secret.txt").write_text("data")
        link = root / "link"
        link.symlink_to(outside_dir, target_is_directory=True)
        with pytest.raises(PathEscapesRootError):
            resolve_within(root, link / "secret.txt")

    def test_is_within_boolean(self, tmp_path):
        root = ensure_directory(tmp_path / "root")
        assert is_within(root, "x/y")
        assert not is_within(root, "../x")

    def test_unicode_and_spaces(self, tmp_path):
        root = ensure_directory(tmp_path / "root")
        p = child_path(root, "فائل name ünïcode.txt")
        assert p.name.startswith("فائل")

    def test_safe_filename(self):
        assert safe_filename("a/b\\c:d") == "a_b_c_d"
        assert safe_filename("../..") == "file"
        assert safe_filename("x" * 500).__len__() == 120
        with pytest.raises(Exception):
            safe_filename("   ")

    def test_missing_root(self, tmp_path):
        with pytest.raises(Exception):
            resolve_within(tmp_path / "nope", "x")


class TestExceptionClassification:
    def test_rate_limit_is_retryable_and_distinct(self):
        assert RateLimitedError.retryable is True
        assert ModelNotFoundError.retryable is False
        assert RateLimitedError.code != ModelNotFoundError.code

    def test_map_covers_all_codes(self):
        assert PROVIDER_ERROR_MAP["rate_limited"] is RateLimitedError
        for cls in PROVIDER_ERROR_MAP.values():
            ctx = cls("x", provider="p", model="m")
            assert ctx.context["provider"] == "p"
            assert ctx.to_dict()["code"] == cls.code
