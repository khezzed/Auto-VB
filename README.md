# AutonomousVulnerabilityBounty

An autonomous, contested two-round vulnerability remediation and bounty adjudication Intelligent Contract for GenLayer.

`AutonomousVulnerabilityBounty` (`contracts/autonomous_vulnerability_bounty.py`) enables open-source projects and decentralized protocols to escrow native bounties, evaluate whitehat vulnerability patches via decentralized validator consensus, and subject proposed fixes to an adversarial, staked counter-exploit challenge window before funds are disbursed.

---

## 1. Overview & Problem Context

Traditional bug bounty programs (e.g., Immunefi, HackerOne, Code4rena) process millions of dollars annually but suffer from two core limitations:
1. **Centralized Triage Bottleneck**: Protocols and researchers depend on centralized triage teams to verify exploit reproduction, assess patch validity, and authorize payments. This introduces 30-90 day disbursement delays, opaque dispute resolutions, and single points of failure.
2. **Standard Smart Contract Blindness**: Traditional smart contracts cannot inspect git diffs, examine security advisories, or verify whether code changes actually resolve a security vulnerability without introducing regressions.

**The Solution**: `AutonomousVulnerabilityBounty` bridges on-chain escrow with off-chain code evaluation through GenLayer's GenVM execution environment and Optimistic Democracy consensus.

### Key Architectural Mechanisms

1. **Two-Stage Contested Adjudication Protocol**:
   - **Round 1 (Patch Qualification)**: A whitehat submits a patch pinned to an immutable commit hash on `raw.githubusercontent.com`. Validators independently retrieve the evidence and evaluate three discrete predicates:
     - `p1_exploit_resolved`: Does the diff directly resolve the target vulnerability?
     - `p2_no_regressions`: Is the diff free of backdoors, unauthorized privileges, or critical side effects?
     - `p3_tests_adequate`: Does the diff include meaningful unit test coverage asserting the fix?
   - **Round 2 (Economic Counter-Exploit Challenge Window)**: If qualified in Round 1, the contract enters an operational 48-hour challenge window. Any third-party researcher or maintainer can post collateral (10% of bounty pool) to submit an exploit proof proving the vulnerability remains or that a bypass exists.
     - **If Refuted**: The patch is rejected, the whitehat is disqualified, and the challenger receives their stake back plus a 50% bounty penalty reward.
     - **If Defended**: The challenger's stake is slashed directly into the bounty pool, and the whitehat is cleared to claim the fortified reward.
2. **Exact Consensus & Grounded Citations**:
   - Eliminates fuzzy numerical margins and subjective score thresholds. Consensus requires exact equality across all core predicates (`p1_exploit_resolved`, `p2_no_regressions`, `p3_tests_adequate` in Round 1; `c1_bypass_proven` in Round 2), commit hashes, and error states, while deterministically verifying that every extracted citation is sorted and grounded verbatim in the raw evidence payload.
3. **Fail-Closed Pinned Evidence Verification**:
   - All external evidence is pinned to immutable raw git blobs on `raw.githubusercontent.com` capped at 25,000 raw bytes (checked prior to UTF-8 decoding). Any non-200 HTTP status, empty payload, or oversized payload fails closed (`UNCLEAR` or `CONTRADICTED`), preventing unverified payouts.
4. **Deterministic Gate Enforcements**:
   - Code-level invariants prevent LLM hallucinations: if git diff headers contain no test file patterns (`test/`, `_test.*`, `.t.sol`), test adequacy (`p3_tests_adequate`) is deterministically forced to `CONTRADICTED`, regardless of LLM claims.

---

## 2. Architecture & Lifecycle State Machine

```
                                  [STATUS_CREATED] (0)
                                         │ fund_bounty() (Sponsor deposit)
                                         ▼
                                  [STATUS_FUNDED] (1)
                                         │ submit_patch(commit_sha) (Whitehat)
                                         ▼
                             [STATUS_PATCH_SUBMITTED] (2)
                                         │ evaluate_patch() (Round 1 Consensus)
                     ┌───────────────────┴───────────────────┐
                     ▼                                       ▼
        All Atoms == HOLDS                      Any Atom != HOLDS
                     │                                       │
                     ▼                                       ▼
         [STATUS_CHALLENGE_WINDOW] (3)          [STATUS_REMEDIATION_REQUIRED] (4)
                     │
         ┌───────────┴───────────────────────────────────────┐
         │ No challenge within 48h                           │ submit_challenge() (Challenger + 10% stake)
         ▼                                                   ▼
   claim_bounty()                                  [STATUS_CHALLENGED] (5)
         │                                                   │ evaluate_challenge() (Round 2 Consensus)
         ▼                                       ┌───────────┴───────────┐
[STATUS_SETTLEMENT_EMITTED] (8)                  ▼                       ▼
                                           C1 == HOLDS             C1 != HOLDS
                                                 │                       │
                                                 ▼                       ▼
                                        [STATUS_REFUTED] (7)    [STATUS_DEFENDED] (6)
                                                 │                       │
                                                 ▼                       ▼
                                        Challenger paid         Whitehat claims fortified pool
```

---

## 3. State Machine Specification

| Status Code | Constant Name | Description |
| :---: | :--- | :--- |
| `0` | `STATUS_CREATED` | Initialized via constructor; immutable parameters locked; awaiting funding. |
| `1` | `STATUS_FUNDED` | Escrow funded with native wei by sponsor; open for whitehat patch submissions. |
| `2` | `STATUS_PATCH_SUBMITTED` | Patch submitted; 7-day protected evaluation window active. |
| `3` | `STATUS_CHALLENGE_WINDOW` | Passed Round 1 evaluation; 48-hour operational counter-challenge window active. |
| `4` | `STATUS_REMEDIATION_REQUIRED` | Evaluated as deficient, invalid, or missing tests; revision permitted before deadline. |
| `5` | `STATUS_CHALLENGED` | Counter-exploit submitted with collateral; awaiting Round 2 consensus evaluation. |
| `6` | `STATUS_DEFENDED` | Challenger proof failed; challenger stake slashed into bounty; whitehat eligible to claim. |
| `7` | `STATUS_REFUTED` | Challenger proof succeeded; patch refuted; challenger awarded bounty penalty. |
| `8` | `STATUS_SETTLEMENT_EMITTED` | Terminal state. Reward transfer emitted via ghost contract. |
| `9` | `STATUS_REFUNDED` | Terminal state. Bounty expired without approved patch; sponsor refunded. |

---

## 4. Consensus & Equivalence Implementation

### A. Strict Allowlist & Bounded Classifications
The LLM never chooses outcomes or numeric balances directly. It only classifies bounded atomic predicates:
- `HOLDS`
- `CONTRADICTED`
- `UNCLEAR`

Any unrecognized token or non-conforming JSON structure defaults strictly to `UNCLEAR`.

### B. Consensus Verification Pipeline
1. **Isolated Snapshot (Zero `self` Reference)**: All contract storage parameters are snapshotted into local variables before nondeterministic closures run; module-level helper functions (`_fetch_url_nondet_fn`, `_detect_test_files_fn`, `_parse_llm_dict_fn`) ensure `self` is never referenced inside `leader_fn` or `validator_fn`.
2. **Independent Validator Execution**: Validators independently fetch the pinned raw evidence, verify raw byte size (`<= 25,000` bytes) before UTF-8 decoding, run local evaluations, and ground citations verbatim against the fetched diff/proof payload.
3. **Strict Consensus Equality**: A validator casts an approving vote if and only if the leader's proposal matches their independent evaluation across all outcome-determining fields (`commit`/`proof_commit`, `p1_exploit_resolved`, `p2_no_regressions`, `p3_tests_adequate`, `c1_bypass_proven`, `evidence_error`) and all leader citations are canonically sorted and verified verbatim in the independently fetched payload.

---

## 5. Verification & Test Suite

The contract is validated using the official GenLayer toolchain (`genvm-linter`, `genlayer-test`, and `pyright`):

```powershell
# 1. Run official GenVM linter & validator
$env:PYTHONIOENCODING="utf-8"
genvm-lint check contracts/autonomous_vulnerability_bounty.py

# 2. Run Pyright type checking against GenVM SDK types
genvm-lint typecheck contracts/autonomous_vulnerability_bounty.py

# 3. Run full test suite (unit, adversarial, and direct-mode)
pytest tests/ -v
```

### Test Suite Coverage Highlights (12/12 Passing)
* `test_uncontested_bounty_lifecycle`: End-to-end happy path: deploy, fund, submit patch, pass Round 1, mature through 48h challenge window uncontested, and disburse bounty.
* `test_contested_challenge_refutes_flawed_patch`: Round 2 contested challenge: patch enters challenge window, challenger stakes 10% collateral and submits proof-of-bypass, consensus refutes the patch, and awards challenger the bounty penalty.
* `test_contested_challenge_defended`: Round 2 contested challenge: challenger submits flawed proof, consensus confirms patch is defended, slashes challenger stake into bounty pool, and pays whitehat the fortified pool.
* `test_direct_mode_lifecycle_and_storage`: Executes contract deployment, funding, caller switching (`vm.sender`), and patch submission directly through GenLayer's official in-memory engine (`gltest.direct`).
* `test_missing_test_files_forces_contradicted`: Tests deterministic invariant forcing `p3_tests_adequate` to `CONTRADICTED` if no test files are modified.
* `test_adversarial_leader_divergent_field_rejection`: Tests rejection of an adversarial leader attempting to forge citations or predicate values.
* `test_prompt_injection_resistance_system_override`: Tests prompt injection resistance against instruction override attempts embedded in git diffs.

---

## 6. Live Testnet Deployment (GenLayer StudioNet)

* **Network**: GenLayer StudioNet (`https://studio.genlayer.com/api`, Chain ID: `61999`)
* **Contract Address**: [`0xdCc2485f6C2D712E03ec324160591e007abE6cf3`](https://explorer-studio.genlayer.com/address/0xdCc2485f6C2D712E03ec324160591e007abE6cf3)
* **Deployed Commit**: [`6c8a73f8f4f0485134cbca3c12b0f93aa43dd6a4`](https://github.com/khezzed/Auto-VB/commit/6c8a73f8f4f0485134cbca3c12b0f93aa43dd6a4)
* **Git Blob SHA-1 (`contracts/autonomous_vulnerability_bounty.py`)**: `1a5d7437b43d00fc26f0e77458e3001dad0ebf47` (27,966 bytes, LF)
* **Release Manifest**: [`release_manifest.json`](release_manifest.json)

### Pinned On-Chain Evidence Fixtures (Commit `6c8a73f8f4f0485134cbca3c12b0f93aa43dd6a4`)
- **Vulnerability Advisory (`782` bytes)**: [`advisories/GHSA-AUTOVB-2026-001.txt`](https://raw.githubusercontent.com/khezzed/Auto-VB/6c8a73f8f4f0485134cbca3c12b0f93aa43dd6a4/advisories/GHSA-AUTOVB-2026-001.txt)
- **Whitehat Remediation Diff (`890` bytes)**: [`patch.diff`](https://raw.githubusercontent.com/khezzed/Auto-VB/6c8a73f8f4f0485134cbca3c12b0f93aa43dd6a4/patch.diff)
- **Challenger Counter-Exploit Proof (`673` bytes)**: [`exploit_proof.py`](https://raw.githubusercontent.com/khezzed/Auto-VB/6c8a73f8f4f0485134cbca3c12b0f93aa43dd6a4/exploit_proof.py)

### Complete 12-Step On-Chain Transaction Walkthrough

The live contract at [`0xdCc2485f6C2D712E03ec324160591e007abE6cf3`](https://explorer-studio.genlayer.com/address/0xdCc2485f6C2D712E03ec324160591e007abE6cf3) was verified on StudioNet across a 12-transaction sequence demonstrating Round 1 patch adjudication, Round 2 staked counter-exploit challenge adjudication, collateral slashing into the bounty pool, final reward settlement, and 5 deliberate security guard failures:

| Step | Action | Transaction Hash | Status | Leader Execution | Verified On-Chain Behavior |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **1** | **Deploy Contract** | [`0x2a19...fc66`](https://explorer-studio.genlayer.com/transactions/0x2a197c46b0648ee084cff79b2163d6d7f355e7cf99c5a2fce944e993c21ffc66) | `FINALIZED` | `SUCCESS` | Contract instantiated (`status = 0`, `target_repo = "khezzed/Auto-VB"`). |
| **2** | **Guard: Non-Sponsor Fund** | [`0xcd9d...540f`](https://explorer-studio.genlayer.com/transactions/0xcd9d42c09c1ebcefd4a251d1a1b5376b7c5806bd248379b1399c9e72aa52540f) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Unauthorized caller rejected (`Only the sponsor can fund this bounty.`). |
| **3** | **Fund Bounty** | [`0x37d1...cb62`](https://explorer-studio.genlayer.com/transactions/0x37d1fd4ac14cd9404f0f1326b67c54527047c49b8689ec86bfaec394a869cb62) | `FINALIZED` | `SUCCESS` | Sponsor escrows `1000 wei` (`status = 1`, `bounty_amount = 1000`). |
| **4** | **Guard: Invalid Commit SHA** | [`0xef4a...da57`](https://explorer-studio.genlayer.com/transactions/0xef4a99c5cfaf3cc7895d978a479622eef4af12439f27e52b2c67f4623f6eda57) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Non-40-hex commit SHA rejected (`Invalid commit_sha format`). |
| **5** | **Submit Patch** | [`0x257f...5df5`](https://explorer-studio.genlayer.com/transactions/0x257f9f174576b30896d6bf081469cfd1ce71da369eb54c3c150c2e6167bf5df5) | `FINALIZED` | `SUCCESS` | Whitehat submits commit `6c8a73f8f4...` (`status = 2`, `submission_count = 1`). |
| **6** | **Evaluate Patch (Round 1)** | [`0xdb83...2683`](https://explorer-studio.genlayer.com/transactions/0xdb83aaec929d1de5840663a85018beda0d9d2029048e8dcb1318cf91a7492683) | `FINALIZED` | `SUCCESS` | Validators fetch advisory & diff $\to$ `p1=HOLDS`, `p2=HOLDS`, `p3=HOLDS` $\to$ `status = 3` (`CHALLENGE_WINDOW`). |
| **7** | **Guard: Premature Claim** | [`0x5d51...5173`](https://explorer-studio.genlayer.com/transactions/0x5d515d5062330375928ae8ad387656eca75434463299b2300bffe65982545173) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Whitehat claim during active 48h challenge window reverts (`Bounty not eligible for claim.`). |
| **8** | **Guard: Under-Staked Challenge** | [`0x7949...e4b9`](https://explorer-studio.genlayer.com/transactions/0x794919d2cdec655de52388ac1960347f2eeb64d00642bd52f3bb1db91112e4b9) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Challenger staking `10 wei` (< 10% minimum `100 wei`) reverts (`Insufficient challenge stake`). |
| **9** | **Submit Challenge** | [`0xae1f...e952`](https://explorer-studio.genlayer.com/transactions/0xae1fb1b55579cf21751c3c9a2ccd38afe4ca9068230fe85e9641084cd91ae952) | `FINALIZED` | `SUCCESS` | Challenger stakes `100 wei` (10% collateral) with counter-exploit commit (`status = 5`). |
| **10** | **Evaluate Challenge (Round 2)** | [`0x4ce9...ce40`](https://explorer-studio.genlayer.com/transactions/0x4ce9ae8e66ff5c5dc0e06a89ba71962a0caa5924375a1bc200922f905604ce40) | `FINALIZED` | `SUCCESS` | Validators evaluate `exploit_proof.py` $\to$ `c1_bypass_proven = CONTRADICTED` $\to$ `status = 6` (`STATUS_DEFENDED`), challenger's `100 wei` slashed into bounty (`bounty_amount = 1100`). |
| **11** | **Guard: Unauthorized Claim** | [`0xe85e...59ed`](https://explorer-studio.genlayer.com/transactions/0xe85e1700b29f6bd08f1edd3dcb93859c6bc1c34d62574cf685e8bb36374659ed) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Non-whitehat attempt to claim defended bounty reverts (`Only the verified whitehat can claim`). |
| **12** | **Claim Fortified Bounty** | [`0xcb0d...8927`](https://explorer-studio.genlayer.com/transactions/0xcb0d536d3995097e2471364c4ea81c3b265f2f71ffadfd76c19f618226d18927) | `FINALIZED` | `SUCCESS` | Whitehat claims fortified `1100 wei` pool (`1000` base + `100` slashed stake) $\to$ `status = 8` (`STATUS_SETTLEMENT_EMITTED`), `bounty_amount = 0`. |
