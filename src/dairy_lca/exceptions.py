"""Public exception types for the generic LCA calculation engine."""


class DairyLCAError(Exception):
    """Base class for public model errors."""


class ParameterSchemaError(DairyLCAError):
    """Raised when a public parameter definition has an invalid structure."""


class UnknownParameterError(DairyLCAError):
    """Raised when a required parameter ID is absent."""


class UnitMismatchError(DairyLCAError):
    """Raised when a parameter unit differs from the requested unit."""


class InvalidModelInputError(DairyLCAError):
    """Raised when runtime activity data violate a public input contract."""


class InputSchemaError(DairyLCAError):
    """Raised when a public input CSV does not follow the documented schema."""
