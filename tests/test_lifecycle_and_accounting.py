import pytest
from datetime import datetime, timezone
import json

from genlayer import Address, u256
from conftest import gl_instance, mock_web_responses, mock_llm_responses, emitted_transfers, MockWebResponse
from contracts.autonomous_vulnerability_bounty import (
    AutonomousVulnerabilityBounty,
    STATUS_CREATED,
    STATUS_FUNDED,
    STATUS_PATCH_SUBMITTED,
    STATUS_CHALLENGE_WINDOW,
    STATUS_REMEDIATION_REQUIRED,
    STATUS_CHALLENGED,
    STATUS_DEFENDED,
    STATUS_REFUTED,
    STATUS_SETTLEMENT_EMITTED,
    STATUS_REFUNDED,
)

SPONSOR_ADDR = Address("0x1111111111111111111111111111111111111111")
WHITEHAT_ADDR = Address("0x2222222222222222222222222222222222222222")
CHALLENGER_ADDR = Address("0x3333333333333333333333333333333333333333")

TARGET_REPO = "uniswap/v4-core"
ADVISORY_URL = "https://raw.githubusercontent.com/uniswap/v4-core/v1.0.0/advisories/GHSA-1234.txt"
PATCH_COMMIT = "a" * 40
CHALLENGE_COMMIT = "c" * 40


@pytest.fixture(autouse=True)
def setup_environment():
    emitted_transfers.clear()
    mock_web_responses.clear()
    mock_llm_responses.clear()
    gl_instance.message.sender_address = SPONSOR_ADDR
    gl_instance.message.value = u256(0)
    gl_instance.message_raw = {"datetime": "2026-10-17T12:00:00+00:00"}


def test_uncontested_bounty_lifecycle():
    """T-01: Full lifecycle: Deploy -> Fund -> Submit Patch -> Pass -> Mature Uncontested -> Claim."""
    contract = AutonomousVulnerabilityBounty(
        target_repo=TARGET_REPO,
        advisory_pinned_url=ADVISORY_URL,
        duration_seconds=u256(86400 * 30),
    )
    assert contract.status == STATUS_CREATED

    # Fund
    gl_instance.message.value = u256(10 * 10**18)
    contract.fund_bounty()
    contract.balance = u256(10 * 10**18)
    assert contract.status == STATUS_FUNDED

    # Submit Patch
    gl_instance.message.sender_address = WHITEHAT_ADDR
    gl_instance.message.value = u256(0)
    contract.submit_patch(PATCH_COMMIT)
    assert contract.status == STATUS_PATCH_SUBMITTED

    # Mock Evidence
    mock_web_responses[ADVISORY_URL] = MockWebResponse(200, b"Reentrancy flaw in unlockCallback")
    patch_url = f"https://raw.githubusercontent.com/{TARGET_REPO}/{PATCH_COMMIT}/patch.diff"
    patch_diff = (
        "diff --git a/src/PoolManager.sol b/src/PoolManager.sol\n"
        "+ nonReentrant\n"
        "diff --git a/test/PoolTest.t.sol b/test/PoolTest.t.sol\n"
        "+ function testReentrancy() external {}\n"
    )
    mock_web_responses[patch_url] = MockWebResponse(200, patch_diff.encode("utf-8"))

    def mock_eval(prompt):
        return {
            "p1_exploit_resolved": "HOLDS",
            "p2_no_regressions": "HOLDS",
            "p3_tests_adequate": "HOLDS",
            "citations": ["+ nonReentrant"],
        }
    mock_llm_responses.append(mock_eval)

    # Evaluate Patch
    contract.evaluate_patch()
    assert contract.status == STATUS_CHALLENGE_WINDOW
    audit = contract.get_patch_audit()
    assert audit["p1_exploit_resolved"] == "HOLDS"

    # Premature claim fails
    with pytest.raises(Exception, match="Bounty not eligible for claim"):
        contract.claim_bounty()

    # Fast forward past 48h challenge window
    gl_instance.message_raw = {"datetime": "2026-10-20T12:00:00+00:00"}
    contract.claim_bounty()

    assert contract.status == STATUS_SETTLEMENT_EMITTED
    assert contract.bounty_amount == u256(0)
    assert len(emitted_transfers) == 1
    assert emitted_transfers[0].recipient == WHITEHAT_ADDR
    assert emitted_transfers[0].value == u256(10 * 10**18)


def test_contested_challenge_refutes_flawed_patch():
    """T-02: Round 2 Challenge: Patch enters challenge window -> Challenger submits counter-exploit -> Refuted."""
    contract = AutonomousVulnerabilityBounty(TARGET_REPO, ADVISORY_URL, u256(86400 * 30))
    gl_instance.message.value = u256(10 * 10**18)
    contract.fund_bounty()
    contract.balance = u256(10 * 10**18)

    # Whitehat submits patch
    gl_instance.message.sender_address = WHITEHAT_ADDR
    gl_instance.message.value = u256(0)
    contract.submit_patch(PATCH_COMMIT)

    # Mock evidence for patch pass
    mock_web_responses[ADVISORY_URL] = MockWebResponse(200, b"Reentrancy flaw")
    patch_url = f"https://raw.githubusercontent.com/{TARGET_REPO}/{PATCH_COMMIT}/patch.diff"
    mock_web_responses[patch_url] = MockWebResponse(
        200,
        b"diff --git a/test/t.sol b/test/t.sol\n+ test\n+ patch_code\n"
    )

    def mock_eval(prompt):
        return {
            "p1_exploit_resolved": "HOLDS",
            "p2_no_regressions": "HOLDS",
            "p3_tests_adequate": "HOLDS",
            "citations": ["+ patch_code"],
        }
    mock_llm_responses.append(mock_eval)
    contract.evaluate_patch()
    assert contract.status == STATUS_CHALLENGE_WINDOW

    # Challenger submits counter-exploit with 10% collateral stake (1 GEN)
    gl_instance.message.sender_address = CHALLENGER_ADDR
    gl_instance.message.value = u256(1 * 10**18)
    contract.submit_challenge(CHALLENGE_COMMIT)
    assert contract.status == STATUS_CHALLENGED

    # Mock challenger exploit evidence proving bypass
    challenge_url = f"https://raw.githubusercontent.com/{TARGET_REPO}/{CHALLENGE_COMMIT}/exploit_proof.py"
    mock_web_responses[challenge_url] = MockWebResponse(200, b"def test_bypass(): assert reentrancy_works()")

    def mock_challenge_eval(prompt):
        return {
            "c1_bypass_proven": "HOLDS",
            "citations": ["def test_bypass(): assert reentrancy_works()"],
        }
    mock_llm_responses.append(mock_challenge_eval)

    # Evaluate challenge
    contract.evaluate_challenge()
    assert contract.status == STATUS_REFUTED

    # Challenger is awarded their stake back + 50% bounty penalty (1 + 5 = 6 GEN)
    assert len(emitted_transfers) == 1
    assert emitted_transfers[0].recipient == CHALLENGER_ADDR
    assert emitted_transfers[0].value == u256(6 * 10**18)


def test_contested_challenge_defended():
    """T-03: Round 2 Challenge: Challenger submits flawed exploit -> Defended -> Stake slashed -> Whitehat paid."""
    contract = AutonomousVulnerabilityBounty(TARGET_REPO, ADVISORY_URL, u256(86400 * 30))
    gl_instance.message.value = u256(10 * 10**18)
    contract.fund_bounty()
    contract.balance = u256(11 * 10**18) # 10 GEN bounty + 1 GEN challenge stake

    gl_instance.message.sender_address = WHITEHAT_ADDR
    gl_instance.message.value = u256(0)
    contract.submit_patch(PATCH_COMMIT)

    mock_web_responses[ADVISORY_URL] = MockWebResponse(200, b"Advisory")
    patch_url = f"https://raw.githubusercontent.com/{TARGET_REPO}/{PATCH_COMMIT}/patch.diff"
    mock_web_responses[patch_url] = MockWebResponse(200, b"diff --git a/test/t.py b/test/t.py\n+ test\n")
    mock_llm_responses.append(lambda p: {"p1_exploit_resolved": "HOLDS", "p2_no_regressions": "HOLDS", "p3_tests_adequate": "HOLDS", "citations": ["+ test"]})
    contract.evaluate_patch()

    # Challenger stakes 1 GEN
    gl_instance.message.sender_address = CHALLENGER_ADDR
    gl_instance.message.value = u256(1 * 10**18)
    contract.submit_challenge(CHALLENGE_COMMIT)

    # Proof is refuted (c1 CONTRADICTED)
    challenge_url = f"https://raw.githubusercontent.com/{TARGET_REPO}/{CHALLENGE_COMMIT}/exploit_proof.py"
    mock_web_responses[challenge_url] = MockWebResponse(200, b"failed proof")
    mock_llm_responses.append(lambda p: {"c1_bypass_proven": "CONTRADICTED", "citations": []})

    contract.evaluate_challenge()
    assert contract.status == STATUS_DEFENDED
    assert contract.bounty_amount == u256(11 * 10**18) # 10 GEN + 1 GEN slashed

    # Whitehat claims the fortified pool
    gl_instance.message.sender_address = WHITEHAT_ADDR
    contract.claim_bounty()
    assert contract.status == STATUS_SETTLEMENT_EMITTED
    assert emitted_transfers[-1].recipient == WHITEHAT_ADDR
    assert emitted_transfers[-1].value == u256(11 * 10**18)


def test_sponsor_refund_boundaries():
    """T-04: Sponsor refund rules across deadlines and non-claimable states."""
    contract = AutonomousVulnerabilityBounty(TARGET_REPO, ADVISORY_URL, u256(86400 * 30))
    gl_instance.message.value = u256(5 * 10**18)
    contract.fund_bounty()
    contract.balance = u256(5 * 10**18)

    # Refund before deadline reverts
    with pytest.raises(Exception, match="Bounty is not eligible for refund"):
        contract.claim_refund()

    # Non-sponsor cannot refund
    gl_instance.message.sender_address = WHITEHAT_ADDR
    gl_instance.message_raw = {"datetime": "2026-12-01T12:00:00+00:00"}
    with pytest.raises(Exception, match="Only the sponsor can claim a refund"):
        contract.claim_refund()

    # Sponsor refund after deadline succeeds
    gl_instance.message.sender_address = SPONSOR_ADDR
    contract.claim_refund()
    assert contract.status == STATUS_REFUNDED
    assert emitted_transfers[-1].recipient == SPONSOR_ADDR
    assert emitted_transfers[-1].value == u256(5 * 10**18)
