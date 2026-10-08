import pyarrow.compute as pc

from telemetry_gen.entities import generate_catalog


def test_catalog_is_deterministic():
    a = generate_catalog(seed_base=42, n_users=200)
    b = generate_catalog(seed_base=42, n_users=200)
    assert a.users.equals(b.users)
    assert a.devices.equals(b.devices)


def test_different_seed_changes_catalog():
    a = generate_catalog(seed_base=42, n_users=200)
    b = generate_catalog(seed_base=7, n_users=200)
    assert not a.devices.equals(b.devices)


def test_volumes_and_unique_keys(catalog):
    assert catalog.users.num_rows == 200
    assert catalog.devices.num_rows == 250
    assert pc.count_distinct(catalog.users["user_id"]).as_py() == 200
    assert pc.count_distinct(catalog.devices["device_id"]).as_py() == 250


def test_every_device_has_an_owner_and_every_user_a_device(catalog):
    user_ids = set(catalog.users["user_id"].to_pylist())
    owners = catalog.devices["user_id"].to_pylist()
    assert set(owners) == user_ids
    assert max(owners.count(u) for u in user_ids) == 2


def test_device_activated_after_signup(catalog):
    signup = dict(
        zip(
            catalog.users["user_id"].to_pylist(),
            catalog.users["data_cadastro"].to_pylist(),
            strict=True,
        )
    )
    for user_id, activated in zip(
        catalog.devices["user_id"].to_pylist(),
        catalog.devices["ativado_em"].to_pylist(),
        strict=True,
    ):
        assert activated >= signup[user_id]


def test_no_personal_data_columns(catalog):
    forbidden = {"nome", "name", "email", "cpf", "documento"}
    assert forbidden.isdisjoint(catalog.users.column_names)
