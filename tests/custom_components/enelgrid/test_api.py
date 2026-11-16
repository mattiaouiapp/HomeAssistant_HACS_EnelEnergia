"""Tests for the HTML helpers of the Enel client."""

from datetime import date

from custom_components.enelgrid.api import _find_input, format_enel_date


def test_find_input():
    html = """
    <form><input type="hidden" name="sessionDataKey" value="abc-123">
    <input name="SAMLResponse" value='PHNhbWw+'/><input name="empty"></form>
    """
    assert _find_input(html, "sessionDataKey") == "abc-123"
    assert _find_input(html, "SAMLResponse") == "PHNhbWw+"
    assert _find_input(html, "empty") == ""
    assert _find_input(html, "missing") is None


def test_format_enel_date():
    assert format_enel_date(date(2025, 3, 5)) == "05032025"
