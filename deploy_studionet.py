import hashlib
import json
import pathlib
import sys
import time
from datetime import datetime, timezone
from typing import Any, List, Union
import requests
from web3.types import RPCEndpoint, RPCResponse
import genlayer_py as gl
from genlayer_py import create_account, create_client
from genlayer_py.chains import studionet
from genlayer_py.exceptions import GenLayerError
from genlayer_py.provider.provider import GenLayerProvider
from genlayer_py.types import TransactionHashVariant, TransactionStatus

ENDPOINT = "https://studio.genlayer.com/api"
EXPLORER_BASE = "https://explorer-studio.genlayer.com"
DEPLOYED_COMMIT_SHA = "9c6b55dacc087f8642a752228a3165ef301b29bd"
PATCH_COMMIT_SHA = "9c6b55dacc087f8642a752228a3165ef301b29bd"
TARGET_REPO = "khezzed/Auto-VB"

PINNED_FIXTURES = {
    "advisory_url": f"https://raw.githubusercontent.com/{TARGET_REPO}/{DEPLOYED_COMMIT_SHA}/advisories/GHSA-AUTOVB-2026-001.txt",
    "authoritative_commit_diff_url": f"https://github.com/{TARGET_REPO}/commit/{PATCH_COMMIT_SHA}.diff",
    "authoritative_patched_source_url": f"https://raw.githubusercontent.com/{TARGET_REPO}/{PATCH_COMMIT_SHA}/src/Vault.sol",
    "authoritative_test_source_url": f"https://raw.githubusercontent.com/{TARGET_REPO}/{PATCH_COMMIT_SHA}/test/VaultTest.t.sol",
    "exploit_proof_url": f"https://raw.githubusercontent.com/{TARGET_REPO}/{PATCH_COMMIT_SHA}/exploit_proof.py",
}

CTOR_ARGS = [
    TARGET_REPO,
    PINNED_FIXTURES["advisory_url"],
    2592000,
]


def custom_make_request(self, method: Union[RPCEndpoint, str], params: List[Any]) -> RPCResponse:
    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000),
        "method": method,
        "params": params,
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    last_err = None
    for attempt in range(10):
        try:
            response = requests.post(self.url, json=payload, headers=headers, timeout=45)
            resp = response.json()
            self._raise_on_error(resp, method)
            return resp
        except Exception as err:
            last_err = err
            if attempt < 9:
                time.sleep(3.0 * (attempt + 1))
                continue
            raise GenLayerError(f"Request to {self.url} ({method}) failed: {err}") from err
    raise last_err


GenLayerProvider.make_request = custom_make_request


def _hex_hash(tx_hash: Any) -> str:
    if isinstance(tx_hash, (bytes, bytearray)):
        h = tx_hash.hex()
    else:
        h = str(tx_hash)
    return h if h.startswith("0x") else f"0x{h}"


def _extract_receipt_summary(tx_hash_hex: str, receipt: dict, expected_failure: bool, label: str) -> dict:
    status_name = str(receipt.get("status_name", receipt.get("status", "")))
    consensus_data = receipt.get("consensus_data") or {}
    leader_receipts = consensus_data.get("leader_receipt") or []
    leader_exec = "UNKNOWN"
    leader_error = None
    if len(leader_receipts) > 0 and isinstance(leader_receipts[0], dict):
        leader_exec = str(leader_receipts[0].get("execution_result", "UNKNOWN"))
        genvm_res = leader_receipts[0].get("genvm_result") or {}
        leader_error = genvm_res.get("stderr") or leader_receipts[0].get("error")
    votes = consensus_data.get("votes") or {}
    return {
        "label": label,
        "tx_hash": tx_hash_hex,
        "explorer_url": f"{EXPLORER_BASE}/transactions/{tx_hash_hex}",
        "expected_failure": expected_failure,
        "status_name": status_name,
        "leader_execution_result": leader_exec,
        "leader_error": leader_error,
        "votes": votes,
    }


def _write_lf_json(path: pathlib.Path, data: dict) -> int:
    raw = (json.dumps(data, indent=2) + "\n").replace("\r\n", "\n").encode("utf-8")
    path.write_bytes(raw)
    return len(raw)


def _send_with_resilient_retry(send_callable, max_attempts: int = 6):
    last_e = None
    for attempt in range(max_attempts):
        try:
            return send_callable()
        except Exception as e:
            last_e = e
            if attempt < max_attempts - 1:
                wait_sec = (attempt + 1) * 5
                print(f"Transient error in send_callable ({e}); retrying in {wait_sec}s...", flush=True)
                time.sleep(wait_sec)
                continue
            raise last_e


def main() -> None:
    contract_path = pathlib.Path("contracts/autonomous_vulnerability_bounty.py")
    raw_bytes = contract_path.read_bytes()
    if b"\r\n" in raw_bytes:
        raise RuntimeError("CRLF detected in contracts/autonomous_vulnerability_bounty.py; LF required")

    git_blob_header = f"blob {len(raw_bytes)}\0".encode("utf-8")
    computed_blob_sha1 = hashlib.sha1(git_blob_header + raw_bytes).hexdigest()

    code_str = raw_bytes.decode("utf-8")
    runner_header = code_str.splitlines()[0].strip()

    sponsor_acct = create_account()
    whitehat_acct = create_account()
    challenger_acct = create_account()

    client = create_client(chain=studionet, endpoint=ENDPOINT, account=sponsor_acct)

    print("Funding sponsor, whitehat, and challenger accounts on StudioNet...", flush=True)
    for role_name, acct in (
        ("sponsor", sponsor_acct),
        ("whitehat", whitehat_acct),
        ("challenger", challenger_acct),
    ):
        tx_f = client.fund_account(address=acct.address, amount=10**20)
        print(f"  Funded {role_name} ({acct.address}): {_hex_hash(tx_f)}", flush=True)
    time.sleep(3)

    transactions_log = []

    def send_and_wait_tx(
        *,
        label: str,
        send_callable,
        expected_failure: bool = False,
        accept_retries: int = 80,
    ) -> tuple[dict, dict]:
        tx_hash = _send_with_resilient_retry(send_callable)
        tx_hex = _hex_hash(tx_hash)
        print(f"\nWaiting for ACCEPTED + FINALIZED on [{label}] ({tx_hex})...", flush=True)

        def _wait_receipt_resilient(target_status, retries_count):
            for poll_attempt in range(6):
                try:
                    return client.wait_for_transaction_receipt(
                        transaction_hash=tx_hex,
                        status=target_status,
                        interval=3000,
                        retries=retries_count,
                    )
                except Exception as poll_err:
                    if poll_attempt < 5:
                        print(
                            f"Transient error waiting for {target_status} ({poll_err}); retrying wait in 5s...",
                            flush=True,
                        )
                        time.sleep(5)
                        continue
                    raise poll_err

        accepted_receipt = _wait_receipt_resilient(TransactionStatus.ACCEPTED, accept_retries)
        accepted_status = str(accepted_receipt.get("status_name", accepted_receipt.get("status", "")))
        final_receipt = _wait_receipt_resilient(TransactionStatus.FINALIZED, 80)
        summary = _extract_receipt_summary(tx_hex, final_receipt, expected_failure, label)
        summary["accepted_status_observed"] = accepted_status
        print(
            f"  -> status={summary['status_name']}, "
            f"leader_execution_result={summary['leader_execution_result']}, "
            f"expected_failure={expected_failure}",
            flush=True,
        )
        if summary["status_name"] != "FINALIZED":
            raise RuntimeError(f"Transaction {tx_hex} did not reach FINALIZED: {summary['status_name']}")
        if not expected_failure and summary["leader_execution_result"] != "SUCCESS":
            raise RuntimeError(f"Expected SUCCESS on {label} ({tx_hex}), got: {summary}")
        if expected_failure and summary["leader_execution_result"] != "ERROR":
            raise RuntimeError(f"Expected ERROR on guard {label} ({tx_hex}), got: {summary}")
        transactions_log.append(summary)
        return summary, final_receipt

    # =========================================================================
    # Step 1: Deploy Contract
    # =========================================================================
    print("Step 1: Deploying redesigned AutonomousVulnerabilityBounty to StudioNet...", flush=True)
    deploy_summary, deploy_receipt = send_and_wait_tx(
        label="deploy_contract",
        send_callable=lambda: client.deploy_contract(
            code=code_str,
            account=sponsor_acct,
            args=CTOR_ARGS,
            leader_only=False,
        ),
        expected_failure=False,
    )
    contract_address = (
        deploy_receipt.get("recipient")
        or deploy_receipt.get("to_address")
        or (deploy_receipt.get("data") or {}).get("contract_address")
    )
    if not contract_address:
        raise RuntimeError(f"Could not extract contract_address from deploy receipt: {deploy_receipt}")
    print(f"Deployed Contract Address: {contract_address}", flush=True)

    def read_fn(fn_name: str, args: list | None = None):
        return _send_with_resilient_retry(
            lambda: client.read_contract(
                address=contract_address,
                function_name=fn_name,
                args=args or [],
                account=sponsor_acct,
                transaction_hash_variant=TransactionHashVariant.LATEST_NONFINAL,
            )
        )

    state_0 = read_fn("get_bounty_state")
    deploy_summary["read_backs"] = {"get_bounty_state": state_0}
    assert state_0["status"] == 0
    assert state_0["bounty_amount"] == 0

    # =========================================================================
    # Step 2: Guard - Non-Sponsor Attempt to Fund Bounty (EXPECTED FAILURE)
    # =========================================================================
    send_and_wait_tx(
        label="guard_non_sponsor_fund (EXPECTED FAILURE: Only the sponsor can fund this bounty.)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="fund_bounty",
            account=challenger_acct,
            value=1000,
            args=[],
            leader_only=False,
        ),
        expected_failure=True,
    )

    # =========================================================================
    # Step 3: Sponsor Funds Bounty (1000 wei)
    # =========================================================================
    send_and_wait_tx(
        label="fund_bounty (1000 wei)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="fund_bounty",
            account=sponsor_acct,
            value=1000,
            args=[],
            leader_only=False,
        ),
        expected_failure=False,
    )
    state_funded = read_fn("get_bounty_state")
    transactions_log[-1]["read_backs"] = {"get_bounty_state": state_funded}
    assert state_funded["status"] == 1
    assert state_funded["bounty_amount"] == 1000

    # =========================================================================
    # Step 4: Guard - Invalid Commit SHA Format (EXPECTED FAILURE)
    # =========================================================================
    send_and_wait_tx(
        label="guard_invalid_commit_sha (EXPECTED FAILURE: Invalid commit_sha format)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="submit_patch",
            account=whitehat_acct,
            args=["not_a_valid_40_char_hex_commit_sha"],
            leader_only=False,
        ),
        expected_failure=True,
    )

    # =========================================================================
    # Step 5: Whitehat Submits Authoritative Remediation Commit SHA
    # =========================================================================
    send_and_wait_tx(
        label=f"submit_patch ({PATCH_COMMIT_SHA[:10]}...)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="submit_patch",
            account=whitehat_acct,
            args=[PATCH_COMMIT_SHA],
            leader_only=False,
        ),
        expected_failure=False,
    )
    state_sub = read_fn("get_bounty_state")
    transactions_log[-1]["read_backs"] = {
        "get_bounty_state": state_sub,
        "get_patch_audit": read_fn("get_patch_audit"),
    }
    assert state_sub["status"] == 2
    assert state_sub["patch_commit"] == PATCH_COMMIT_SHA

    # =========================================================================
    # Step 6: Round 1 Consensus - Evaluate Authoritative Commit Diff & Source
    # =========================================================================
    send_and_wait_tx(
        label="evaluate_patch (Round 1 Consensus: Authoritative commit/.diff + src/Vault.sol -> STATUS_CHALLENGE_WINDOW)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="evaluate_patch",
            account=sponsor_acct,
            args=[],
            leader_only=False,
        ),
        expected_failure=False,
    )
    state_eval1 = read_fn("get_bounty_state")
    audit_eval1 = read_fn("get_patch_audit")
    transactions_log[-1]["read_backs"] = {
        "get_bounty_state": state_eval1,
        "get_patch_audit": audit_eval1,
    }
    print(f"Round 1 Audit Read-Back: {audit_eval1}", flush=True)
    assert state_eval1["status"] == 3, f"Expected status 3 (CHALLENGE_WINDOW), got {state_eval1['status']}: {audit_eval1}"
    assert state_eval1["patched_file_path"] == "src/Vault.sol"

    # =========================================================================
    # Step 7: Guard - Premature Bounty Claim During Active Challenge Window
    # =========================================================================
    send_and_wait_tx(
        label="guard_premature_claim (EXPECTED FAILURE: Bounty not eligible for claim.)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="claim_bounty",
            account=whitehat_acct,
            args=[],
            leader_only=False,
        ),
        expected_failure=True,
    )

    # =========================================================================
    # Step 8: Guard - Insufficient Challenge Stake (< 10% of 1000 wei = < 100 wei)
    # =========================================================================
    send_and_wait_tx(
        label="guard_insufficient_challenge_stake (EXPECTED FAILURE: Insufficient challenge stake)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="submit_challenge",
            account=challenger_acct,
            value=10,  # Only 1% (< 10% minimum 100 wei)
            args=[PATCH_COMMIT_SHA],
            leader_only=False,
        ),
        expected_failure=True,
    )

    # =========================================================================
    # Step 9: Challenger Submits Counter-Exploit Challenge with 10% Stake (100 wei)
    # =========================================================================
    send_and_wait_tx(
        label="submit_challenge (100 wei collateral stake)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="submit_challenge",
            account=challenger_acct,
            value=100,
            args=[PATCH_COMMIT_SHA],
            leader_only=False,
        ),
        expected_failure=False,
    )
    state_chal = read_fn("get_bounty_state")
    transactions_log[-1]["read_backs"] = {
        "get_bounty_state": state_chal,
        "get_challenge_audit": read_fn("get_challenge_audit"),
    }
    assert state_chal["status"] == 5

    # =========================================================================
    # Step 10: Round 2 Consensus - Evaluate Counter-Exploit Against Patched Source
    # =========================================================================
    send_and_wait_tx(
        label="evaluate_challenge (Round 2 Consensus: Retrieves src/Vault.sol + commit/.diff + exploit_proof.py -> STATUS_DEFENDED)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="evaluate_challenge",
            account=sponsor_acct,
            args=[],
            leader_only=False,
        ),
        expected_failure=False,
    )
    state_eval2 = read_fn("get_bounty_state")
    audit_eval2 = read_fn("get_challenge_audit")
    transactions_log[-1]["read_backs"] = {
        "get_bounty_state": state_eval2,
        "get_challenge_audit": audit_eval2,
    }
    print(f"Round 2 Challenge Audit Read-Back: {audit_eval2}", flush=True)
    assert state_eval2["status"] == 6, f"Expected status 6 (STATUS_DEFENDED), got {state_eval2['status']}: {audit_eval2}"
    assert state_eval2["bounty_amount"] == 1100  # 1000 original + 100 slashed challenger stake

    # =========================================================================
    # Step 11: Guard - Unauthorized Stranger Attempt to Claim Bounty
    # =========================================================================
    send_and_wait_tx(
        label="guard_unauthorized_claim (EXPECTED FAILURE: Only the verified whitehat can claim)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="claim_bounty",
            account=challenger_acct,
            args=[],
            leader_only=False,
        ),
        expected_failure=True,
    )

    # =========================================================================
    # Step 12: Whitehat Claims Fortified Bounty Pool (1100 wei)
    # =========================================================================
    send_and_wait_tx(
        label="claim_bounty (Whitehat claims 1100 wei fortified reward)",
        send_callable=lambda: client.write_contract(
            address=contract_address,
            function_name="claim_bounty",
            account=whitehat_acct,
            args=[],
            leader_only=False,
        ),
        expected_failure=False,
    )
    state_final = read_fn("get_bounty_state")
    transactions_log[-1]["read_backs"] = {"get_bounty_state": state_final}
    assert state_final["status"] == 8  # STATUS_SETTLEMENT_EMITTED
    assert state_final["bounty_amount"] == 0

    # =========================================================================
    # Emit Complete Machine-Readable Release Manifest
    # =========================================================================
    manifest_data = {
        "project": "AutonomousVulnerabilityBounty - Contested Two-Round Vulnerability Remediation & Bounty Protocol",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": {
            "name": "studionet",
            "chain_id": 61999,
            "rpc_endpoint": ENDPOINT,
            "explorer_base_url": EXPLORER_BASE,
        },
        "source_verification": {
            "repository_url": "https://github.com/khezzed/Auto-VB",
            "contract_path": "contracts/autonomous_vulnerability_bounty.py",
            "deployed_commit_sha": DEPLOYED_COMMIT_SHA,
            "git_blob_sha1": computed_blob_sha1,
            "byte_length": len(raw_bytes),
            "line_endings": "LF",
            "runner_header": runner_header,
        },
        "toolchain": {
            "python_version": sys.version.split()[0],
            "genlayer_py": "0.16.3",
            "genvm_linter": "0.11.0",
            "genlayer_test": "0.29.2",
        },
        "evidence_fixtures": [
            {"id": k, "url": v, "http_status": 200} for k, v in PINNED_FIXTURES.items()
        ],
        "deployment": {
            "contract_address": contract_address,
            "explorer_contract_url": f"{EXPLORER_BASE}/address/{contract_address}",
            "sponsor_address": sponsor_acct.address,
            "whitehat_address": whitehat_acct.address,
            "challenger_address": challenger_acct.address,
            "patch_commit_sha": PATCH_COMMIT_SHA,
            "constructor_args": CTOR_ARGS,
        },
        "transactions": transactions_log,
    }

    manifest_path = pathlib.Path("release_manifest.json")
    _write_lf_json(manifest_path, manifest_data)
    print(f"\nSUCCESS! Full 12-step live StudioNet demo complete. Wrote {manifest_path.resolve()}", flush=True)


if __name__ == "__main__":
    main()
