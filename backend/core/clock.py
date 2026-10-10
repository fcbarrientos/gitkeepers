"""The device's local date. Tests patch `today` to pin the calendar."""
from datetime import date


def today() -> date:
    return date.today()
