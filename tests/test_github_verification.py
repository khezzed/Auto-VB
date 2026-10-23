import pytest

from genlayer import Address, u256
from conftest import gl_instance, mock_web_responses, mock_llm_responses, MockWebResponse
from contracts.autonomous_vulnerability_bounty import (
    AutonomousVulnerabilityBounty,
    STATUS_FUNDED,
    STATUS_PATCH_SUBMITTED,
    STATUS_REMEDIATION_REQUIRED,
    MAX_EVIDENCE_BYTES,
)

SPONSOR_ADDR = Address("0x1111111111111111111111111111111111111111")
WHITEHAT_ADDR = Address("0x2222222222222222222222222222222222222222")

TARGET_REPO = "uniswap/v4-core"
ADVISORY_URL = "https://raw.githubusercontent.com/uniswap/v4-core/v1.0.0/advisories/GHSA-1234.txt"
PATCH_COMMIT = "a" * 40


@pytest.fixture(autouse=True)
def setup_environment():
    mock_web_responses.clear()
    mock_llm_responses.clear()
    gl_instance.message.sender_address = SPONSOR_ADDR
    gl_instance.message.value = u256(0)
    gl_instance.message_raw = {"datetime": "2026-10-17T12:00:00+00:00"}


def test_evidence_404_handling():
    """Fail-closed on 404: If patch diff, patched source, or advisory is missing, predicates become UNCLEAR."""
    contract = AutonomousVulnerabilityBounty(TARGET_REPO, ADVISORY_URL, u256(86400 * 30))
    gl_instance.message.value = u256(5 * 10**18)
    contract.fund_bounty()

    gl_instance.message.sender_address = WHITEHAT_ADDR
    contract.submit_patch(PATCH_COMMIT)

    # Missing advisory (404)
    mock_web_responses[ADVISORY_URL] = MockWebResponse(404, b"Not Found")
    diff_url = f"https://github.com/{TARGET_REPO}/commit/{PATCH_COMMIT}.diff"
    mock_web_responses[diff_url] = MockWebResponse(200, b"diff --git a/src/Vault.sol b/src/Vault.sol\n+ some diff")

    contract.evaluate_patch()
    assert contract.status == STATUS_REMEDIATION_REQUIRED
    audit = contract.get_patch_audit()
    assert audit["p1_exploit_resolved"] == "UNCLEAR"


def test_oversized_evidence_rejection():
    """Reject oversized commit diff (>25,000 bytes) to prevent resource exhaustion."""
    contract = AutonomousVulnerabilityBounty(TARGET_REPO, ADVISORY_URL, u256(86400 * 30))
    gl_instance.message.value = u256(5 * 10**18)
    contract.fund_bounty()

    gl_instance.message.sender_address = WHITEHAT_ADDR
    contract.submit_patch(PATCH_COMMIT)

    mock_web_responses[ADVISORY_URL] = MockWebResponse(200, b"Advisory")
    diff_url = f"https://github.com/{TARGET_REPO}/commit/{PATCH_COMMIT}.diff"
    # Create diff exceeding MAX_EVIDENCE_BYTES
    oversized_diff = b"diff --git a/src/Vault.sol b/src/Vault.sol\n" + (b"+ large payload\n" * 2000)
    assert len(oversized_diff) > MAX_EVIDENCE_BYTES
    mock_web_responses[diff_url] = MockWebResponse(200, oversized_diff)

    contract.evaluate_patch()
    assert contract.status == STATUS_REMEDIATION_REQUIRED
    audit = contract.get_patch_audit()
    assert audit["p1_exploit_resolved"] == "CONTRADICTED"


def test_transient_network_outage_allows_retry():
    """503 network outage fails closed to UNCLEAR, keeping submission ready for retry."""
    contract = AutonomousVulnerabilityBounty(TARGET_REPO, ADVISORY_URL, u256(86400 * 30))
    gl_instance.message.value = u256(5 * 10**18)
    contract.fund_bounty()

    gl_instance.message.sender_address = WHITEHAT_ADDR
    contract.submit_patch(PATCH_COMMIT)

    mock_web_responses[ADVISORY_URL] = MockWebResponse(503, b"Service Unavailable")
    contract.evaluate_patch()
    assert contract.status == STATUS_REMEDIATION_REQUIRED


def test_invalid_commit_sha_format():
    """Invalid SHA format reverts deterministically."""
    contract = AutonomousVulnerabilityBounty(TARGET_REPO, ADVISORY_URL, u256(86400 * 30))
    gl_instance.message.value = u256(5 * 10**18)
    contract.fund_bounty()

    gl_instance.message.sender_address = WHITEHAT_ADDR
    with pytest.raises(Exception, match="Invalid commit_sha format"):
        contract.submit_patch("not_a_valid_hex_sha")
