"""Storage bounds apply to every entry point, including legacy field mappings."""
import re

from sqlalchemy import BigInteger, Integer, SmallInteger

from app.models.lead import Lead


class LeadFieldValidationError(ValueError):
    def __init__(self, field, code):
        self.field, self.code = field, code
        super().__init__(f"Invalid lead field: {field}; reason={code}")


def validate_lead_fields(values):
    for field, value in values.items():
        column = Lead.__table__.c.get(field)
        if value is None or column is None:
            continue
        if isinstance(column.type, Integer):
            if not isinstance(value, int) or isinstance(value, bool):
                raise LeadFieldValidationError(field, "invalid_type")
            bits = 64 if isinstance(column.type, BigInteger) else 16 if isinstance(column.type, SmallInteger) else 32
            if not -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
                raise LeadFieldValidationError(field, "out_of_range")
        limit = getattr(column.type, "length", None)
        if limit:
            if not isinstance(value, str):
                raise LeadFieldValidationError(field, "invalid_type")
            if len(value) > limit:
                raise LeadFieldValidationError(field, "too_long")
        if field == "country" and isinstance(value, str) and re.search(r"https?://|(?:^|\s)(?:www\.|t\.me/)", value, re.I):
            raise LeadFieldValidationError(field, "not_a_country")
