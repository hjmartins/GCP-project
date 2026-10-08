from datetime import date

import pytest

from telemetry_gen.entities import generate_catalog
from telemetry_gen.readings import generate_day

DAY = date(2026, 10, 1)


@pytest.fixture(scope="session")
def catalog():
    return generate_catalog(seed_base=42, n_users=200)


@pytest.fixture(scope="session")
def daily(catalog):
    return generate_day(catalog.devices, seed_base=42, day=DAY)
