CONTRACT = "contracts/Meter.py"
URL_A = "https://www.coingecko.com/"
URL_B = "https://coinmarketcap.com/"
LENDER = "0x1111111111111111111111111111111111111111"


def _open(contract, vm, borrower, window_end="2026-12-31"):
    vm.sender = borrower
    return contract.open_position(
        LENDER,
        "ETH",
        "2000",
        "2026-10-01",
        window_end,
        URL_A,
        URL_B,
        value=10**18,
    )


def test_borrower_cannot_be_lender(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("borrower and lender must be different"):
        contract.open_position(
            str(direct_alice),
            "ETH",
            "2000",
            "2026-10-01",
            "2026-12-31",
            URL_A,
            URL_B,
            value=10**18,
        )


def test_sources_must_differ(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("rate sources must come from two different hosts"):
        contract.open_position(
            LENDER,
            "ETH",
            "2000",
            "2026-10-01",
            "2026-12-31",
            URL_A,
            "https://www.coingecko.com/en/coins/ethereum",
            value=10**18,
        )


def test_rejects_impossible_date(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("window_end must be a real calendar date"):
        contract.open_position(
            LENDER,
            "ETH",
            "2000",
            "2026-10-01",
            "2026-02-31",
            URL_A,
            URL_B,
            value=10**18,
        )


def test_early_liquidate_and_release_blocked(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    position_id = _open(contract, direct_vm, direct_alice)
    raw = contract.get_position(position_id)
    assert "LOCKED" in raw
    assert "2027-01-01" in raw
    with direct_vm.expect_revert("liquidation cannot open before"):
        contract.liquidate(position_id)
    with direct_vm.expect_revert("collateral cannot release before"):
        contract.release(position_id)
    assert "LOCKED" in contract.get_position(position_id)


def test_release_not_open_on_window_end(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    position_id = _open(contract, direct_vm, direct_alice, window_end="2026-10-05")
    raw = contract.get_position(position_id)
    assert "2026-10-05" in raw
    assert "2026-10-06" in raw
    with direct_vm.expect_revert("collateral cannot release before"):
        contract.release(position_id)
    assert "LOCKED" in contract.get_position(position_id)


def test_release_returns_collateral_once(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    position_id = _open(contract, direct_vm, direct_alice, window_end="2020-01-01")
    assert "2020-01-02" in contract.get_position(position_id)
    contract.release(position_id)
    after = contract.get_position(position_id)
    assert "RELEASED" in after
    assert "RETURNED_TO_BORROWER" in after
    assert contract.get_reserved_collateral() == "0"
    with direct_vm.expect_revert("collateral is not releasable"):
        contract.release(position_id)


def test_single_host_breach_does_not_pay(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    position_id = _open(contract, direct_vm, direct_alice, window_end="2026-10-05")

    def disagree(_item):
        return {"verdict": "DISAGREE"}

    contract._adjudicate = disagree
    contract.liquidate(position_id)
    after = contract.get_position(position_id)
    assert "LOCKED" in after
    assert "DISAGREE" in after
    assert "LIQUIDATED" not in after
    assert contract.get_reserved_collateral() == str(10**18)


def test_dual_breach_pays_lender(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    position_id = _open(contract, direct_vm, direct_alice, window_end="2026-10-05")

    def breach(_item):
        return {"verdict": "BREACH"}

    contract._adjudicate = breach
    contract.liquidate(position_id)
    after = contract.get_position(position_id)
    assert "LIQUIDATED" in after
    assert "PAID_TO_LENDER" in after
    assert contract.get_reserved_collateral() == "0"
    with direct_vm.expect_revert("position is not locked"):
        contract.liquidate(position_id)