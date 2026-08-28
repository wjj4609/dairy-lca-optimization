"""Small validation helpers shared by the Production-only modules."""

from __future__ import annotations

from math import isclose, isfinite
from numbers import Real
from typing import Iterable

from .exceptions import InvalidModelInputError


def identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidModelInputError(f"{name} must be a non-empty string")
    return value.strip()


def number(
    name: str,
    value: object,
    *,
    nonnegative: bool = False,
    positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise InvalidModelInputError(f"{name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise InvalidModelInputError(f"{name} must be finite")
    if positive and result <= 0:
        raise InvalidModelInputError(f"{name} must be > 0")
    if nonnegative and result < 0:
        raise InvalidModelInputError(f"{name} must be >= 0")
    return result


def fraction(name: str, value: object) -> float:
    result = number(name, value, nonnegative=True)
    if result > 1:
        raise InvalidModelInputError(f"{name} must be in [0, 1]")
    return result


def whole_number(name: str, value: object, *, nonnegative: bool = True) -> int:
    result = number(name, value, nonnegative=nonnegative)
    if not result.is_integer():
        raise InvalidModelInputError(f"{name} must be a whole number")
    return int(result)


def shares_sum_to_one(
    name: str,
    values: Iterable[float],
    *,
    tolerance: float = 1e-9,
) -> None:
    shares = tuple(values)
    if not shares:
        raise InvalidModelInputError(f"{name} must contain at least one share")
    for index, value in enumerate(shares):
        fraction(f"{name}[{index}]", value)
    if not isclose(sum(shares), 1.0, rel_tol=0.0, abs_tol=tolerance):
        raise InvalidModelInputError(f"{name} must sum to 1")
