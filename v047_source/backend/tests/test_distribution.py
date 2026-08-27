from app.services.distribution import AccountCapacity, distribute_balanced


def test_limit_is_per_account_4_times_50_equals_200():
    accounts = [AccountCapacity(account_id=i, limit=50) for i in range(1, 5)]
    groups = list(range(1, 201))

    result = distribute_balanced(groups, accounts, seed=42)

    assert len(result) == 200
    assert {account_id: list(result.values()).count(account_id) for account_id in range(1, 5)} == {
        1: 50,
        2: 50,
        3: 50,
        4: 50,
    }


def test_120_groups_are_evenly_distributed():
    accounts = [AccountCapacity(account_id=i, limit=50) for i in range(1, 5)]
    result = distribute_balanced(list(range(120)), accounts, seed=7)
    assert sorted(list(result.values()).count(i) for i in range(1, 5)) == [30, 30, 30, 30]


def test_disabled_accounts_receive_nothing_and_capacity_is_respected():
    accounts = [
        AccountCapacity(account_id=1, limit=2, enabled=True),
        AccountCapacity(account_id=2, limit=100, enabled=False),
        AccountCapacity(account_id=3, limit=2, enabled=True),
    ]
    result = distribute_balanced(list(range(10)), accounts, seed=1)
    assert len(result) == 4
    assert set(result.values()) == {1, 3}

