"""Tests for the teaching-scheme loader: the real file, and each validation rule."""

from __future__ import annotations

import copy

import pytest
import yaml

from ingestion.scheme import SCHEME_YAML, SchemeError, load_scheme, parse_scheme


@pytest.fixture
def raw() -> dict:
    with SCHEME_YAML.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_real_scheme_loads() -> None:
    scheme = load_scheme()
    assert [(s.semester, s.year) for s in scheme.semesters] == [(4, "SE"), (6, "TE")]
    by_code = {c.code: c for c in scheme.courses()}
    assert len(by_code) == 11
    os_ = by_code["CE206"]
    assert (os_.L, os_.T, os_.P, os_.include, os_.year) == (3, 0, 2, True, "SE")
    assert by_code["AS201"].include == "if_ce_faculty"
    assert by_code["PR3-I"].include is False
    assert by_code["PR3-I"].exclude_reason == "project (D3)"
    assert scheme.semester(6).note is not None


def test_valid_copy_round_trips(raw: dict) -> None:
    assert parse_scheme(copy.deepcopy(raw)) == load_scheme()


def _course(raw: dict, code: str) -> dict:
    return next(c for s in raw["semesters"] for c in s["courses"] if c["code"] == code)


def test_duplicate_code_rejected(raw: dict) -> None:
    raw["semesters"][1]["courses"].append(dict(_course(raw, "CE206")))
    with pytest.raises(SchemeError, match="duplicate code 'CE206'"):
        parse_scheme(raw)


@pytest.mark.parametrize("value", [-1, 1.5, True, "3", None])
def test_bad_hours_rejected(raw: dict, value: object) -> None:
    _course(raw, "CE207")["P"] = value
    with pytest.raises(SchemeError, match="hours must be non-negative integers"):
        parse_scheme(raw)


@pytest.mark.parametrize("value", ["yes", 1, 0, "true", None])
def test_bad_include_rejected(raw: dict, value: object) -> None:
    _course(raw, "CE208")["include"] = value
    with pytest.raises(SchemeError, match="must be true, false or if_ce_faculty"):
        parse_scheme(raw)


def test_every_problem_is_listed(raw: dict) -> None:
    _course(raw, "CE205")["L"] = -3
    _course(raw, "CE306")["include"] = "maybe"
    del _course(raw, "CE307")["T"]
    with pytest.raises(SchemeError) as info:
        parse_scheme(raw)
    message = str(info.value)
    assert "CE205" in message and "CE306" in message and "CE307" in message
