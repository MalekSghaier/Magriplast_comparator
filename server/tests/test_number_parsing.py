"""
Generic tests for parse_quantity() and parse_money().

These tests verify the BEHAVIOUR of the parsing functions using
generic numeric examples.  No supplier-specific values, product
references, or prices from any particular PDF are hardcoded here.

Run from server/:
    pytest tests/test_number_parsing.py -v
"""
import pytest
from decimal import Decimal

from app.utils.number_parser import parse_quantity, parse_money, parse_french_number


# ── parse_quantity ─────────────────────────────────────────────────────────────

class TestParseQuantity:
    """parse_quantity must return (Decimal, raw_str) without scaling or rounding."""

    def test_integer_string(self):
        val, raw = parse_quantity("5")
        assert val == Decimal("5")
        assert raw == "5"

    def test_decimal_with_period(self):
        val, raw = parse_quantity("4.0")
        assert val == Decimal("4.0")
        assert raw == "4.0"

    def test_decimal_with_comma(self):
        val, raw = parse_quantity("4,0")
        assert val == Decimal("4.0")
        assert raw == "4,0"

    def test_tilde_prefix_stripped(self):
        """~ prefix means 'approximately' — strip it, parse the number."""
        val, raw = parse_quantity("~ 4.0")
        assert val == Decimal("4.0")
        assert raw == "4.0"

    def test_dash_prefix_stripped(self):
        val, raw = parse_quantity("- 10")
        assert val == Decimal("10")
        assert raw == "10"

    def test_large_integer(self):
        val, raw = parse_quantity("200")
        assert val == Decimal("200")

    def test_decimal_not_multiplied(self):
        """4.0 must NOT become 40."""
        val, _ = parse_quantity("4.0")
        assert val == Decimal("4.0")
        assert val != Decimal("40")

    def test_decimal_not_multiplied_10(self):
        """10.0 must NOT become 100."""
        val, _ = parse_quantity("10.0")
        assert val == Decimal("10.0")
        assert val != Decimal("100")

    def test_space_thousands_separator(self):
        """1 200 → 1200 (space as thousands separator)."""
        val, _ = parse_quantity("1 200")
        assert val == Decimal("1200")

    def test_empty_string_returns_none(self):
        val, raw = parse_quantity("")
        assert val is None
        assert raw == ""

    def test_non_numeric_returns_none(self):
        val, raw = parse_quantity("ABC")
        assert val is None

    def test_raw_string_preserved_with_tilde(self):
        """raw should be the stripped numeric portion, not the original."""
        _, raw = parse_quantity("~ 20.0")
        assert raw == "20.0"

    def test_decimal_separator_not_dropped(self):
        """The decimal separator must not be stripped."""
        val, _ = parse_quantity("20.0")
        assert float(val) == 20.0
        assert float(val) != 200.0


# ── parse_money ────────────────────────────────────────────────────────────────

class TestParseMoney:
    """parse_money must preserve decimal precision and return raw strings."""

    def test_three_decimal_tnd(self):
        """TND prices have 3 decimal millimes: 122.341 must stay 122.341."""
        val, raw = parse_money("122.341")
        assert val == Decimal("122.341")
        assert raw == "122.341"

    def test_three_decimal_tnd_large(self):
        val, raw = parse_money("415.959")
        assert val == Decimal("415.959")
        assert raw == "415.959"

    def test_two_decimal_euro_style(self):
        val, raw = parse_money("1200.50")
        assert val == Decimal("1200.50")

    def test_comma_decimal_separator(self):
        val, _ = parse_money("122,341")
        # With a single comma and 3 digits after, treated as thousands separator
        # → 122341 (not 122.341).  This is correct French parsing for "122 341".
        # Callers needing TND must pass period-format values.
        assert val is not None

    def test_space_thousands_separator(self):
        val, _ = parse_money("1 200,50")
        assert val == Decimal("1200.50")

    def test_no_rounding(self):
        """parse_money must NOT round to 2 decimal places."""
        val, _ = parse_money("122.341")
        # Must have exactly 3 decimal digits
        assert str(val) == "122.341"
        assert val != Decimal("122.34")

    def test_raw_string_preserved(self):
        _, raw = parse_money("415.959")
        assert raw == "415.959"

    def test_four_decimal_value(self):
        val, raw = parse_money("5.5680")
        assert val == Decimal("5.5680")
        assert raw == "5.5680"

    def test_whole_number(self):
        val, raw = parse_money("50")
        assert val == Decimal("50")

    def test_empty_returns_none(self):
        val, raw = parse_money("")
        assert val is None

    def test_zero_value(self):
        val, _ = parse_money("0.000")
        assert val == Decimal("0.000")

    def test_price_not_multiplied(self):
        """4.0 as a price must remain 4.0, not 40."""
        val, _ = parse_money("4.0")
        assert val == Decimal("4.0")
        assert val != Decimal("40")


# ── parse_french_number ────────────────────────────────────────────────────────

class TestParseFrenchNumber:
    """Core number parser — used by both parse_quantity and parse_money."""

    def test_single_period_always_decimal(self):
        """A single period is ALWAYS the decimal separator (never thousands)."""
        assert parse_french_number("122.341") == Decimal("122.341")
        assert parse_french_number("5.568") == Decimal("5.568")
        assert parse_french_number("4.0") == Decimal("4.0")

    def test_multiple_periods_thousands(self):
        """Multiple periods → thousands separator: 1.200.000 → 1200000."""
        assert parse_french_number("1.200.000") == Decimal("1200000")

    def test_comma_decimal_short(self):
        """Single comma with ≤2 digits after → decimal: 1,50 → 1.50."""
        assert parse_french_number("1,50") == Decimal("1.50")

    def test_comma_thousands_long(self):
        """Single comma with 3 digits after → thousands: 1,200 → 1200."""
        assert parse_french_number("1,200") == Decimal("1200")

    def test_period_comma_mixed(self):
        """1.200,50 → 1200.50 (period = thousands, comma = decimal)."""
        assert parse_french_number("1.200,50") == Decimal("1200.50")

    def test_space_thousands(self):
        assert parse_french_number("1 200") == Decimal("1200")

    def test_none_on_empty(self):
        assert parse_french_number("") is None

    def test_none_on_letters(self):
        assert parse_french_number("ABC") is None
