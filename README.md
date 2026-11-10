# AutonomousVulnerabilityBounty

An autonomous, contested two-round vulnerability remediation and bounty adjudication Intelligent Contract for GenLayer.

`AutonomousVulnerabilityBounty` (`contracts/autonomous_vulnerability_bounty.py`) enables open-source projects and decentralized protocols to escrow native bounties, evaluate whitehat vulnerability patches via decentralized validator consensus grounded directly in the **submitted commit's authoritative GitHub diff (`commit/<sha>.diff`) and post-patch source code**, and subject proposed fixes to an adversarial, staked counter-exploit challenge window before funds are disbursed.

---

## 1. Overview & Problem Context

Traditional bug bounty programs (e.g., Immunefi, HackerOne, Code4rena) process millions of dollars annually but suffer from two core limitations:
1. **Centralized Triage Bottleneck**: Protocols and researchers depend on centralized triage teams to verify exploit reproduction, assess patch validity, and authorize payments. This introduces 30-90 day disbursement delays, opaque dispute resolutions, and single points of failure.
2. **Standard Smart Contract Blindness**: Traditional smart contracts cannot inspect git commit diffs, examine patched source files, or verify whether code changes actually resolve a security vulnerability without introducing regressions.

**The Solution**: `AutonomousVulnerabilityBounty` bridges on-chain escrow with off-chain code evaluation through GenLayer's GenVM execution environment and Optimistic Democracy consensus.

### Key Architectural Mechanisms

1. **Two-Stage Contested Adjudication Grounded in Authoritative Commit Diffs & Patched Source**:
   - **Round 1 (Authoritative Commit Diff & Source Qualification)**: A whitehat submits a 40-char git commit SHA (`patch_commit`). Validators independently retrieve:
     1. The **pinned security advisory** (`advisory_pinned_url`).
     2. The **submitted commit's authoritative GitHub diff** (`https://github.com/{target_repo}/commit/{patch_commit}.diff`).
     3. The **authoritative post-patch source file** extracted from the diff headers (`https://raw.githubusercontent.com/{target_repo}/{patch_commit}/{patched_file_path}`, e.g., `src/Vault.sol`).
     Validators then classify three bounded predicates:
     - `p1_exploit_resolved`: Do the authoritative commit diff and resulting patched source file directly resolve the target vulnerability?
     - `p2_no_regressions`: Are the commit diff and patched source file free of backdoors, unauthorized privileges, or critical regressions?
     - `p3_tests_adequate`: Does the commit diff add or modify meaningful unit test coverage asserting the fix?
   - **Round 2 (Economic Counter-Exploit Challenge Against Patched Source)**: If qualified in Round 1, the contract records `patched_file_path` in storage and enters a 48-hour challenge window. Any third-party researcher can stake a strictly positive collateral amount ($\ge 10\%$ of the bounty pool enforced via ceiling division `(bounty_amount * 10 + 99) // 100`, minimum `1` wei) and submit a counter-exploit commit (`challenge_commit`). Validators independently retrieve **both**:
     1. The **authoritative patched source file** (`https://raw.githubusercontent.com/{target_repo}/{patch_commit}/{patched_file_path}`) and **authoritative commit diff** (`commit/{patch_commit}.diff`).
     2. The **challenger's counter-exploit proof** (`https://raw.githubusercontent.com/{target_repo}/{challenge_commit}/exploit_proof.py`).
     - **If Substantively Refuted (`evidence_error == "NONE"` and `c1_bypass_proven == "HOLDS"`)**: The patch is rejected (`STATUS_REFUTED`), the whitehat is disqualified, and the challenger receives their stake back plus a 50% bounty penalty reward.
     - **If Substantively Defended (`evidence_error == "NONE"` and `c1_bypass_proven == "CONTRADICTED"`)**: Only a substantive `CONTRADICTED` verdict defends the patch (`STATUS_DEFENDED`), slashes the challenger's stake into the bounty pool, and makes the whitehat eligible to claim the fortified reward.
     - **If Non-Final (`c1_bypass_proven == "UNCLEAR"` or `evidence_error != "NONE"`)**: The contract remains in `STATUS_CHALLENGED` without releasing the bounty or confiscating the challenger's stake. Adjudication can be retried via `evaluate_challenge()` before `review_deadline`, or safely unwound after `review_deadline` via `claim_refund()` (which returns `challenge_stake` in full to the challenger and `bounty_amount` in full to the sponsor).
2. **Exact Consensus & Grounded Citations**:
   - Eliminates fuzzy numerical margins and subjective score thresholds. Consensus requires exact equality across all core fields (`commit`/`proof_commit`, `patched_file_path`, `p1_exploit_resolved`, `p2_no_regressions`, `p3_tests_adequate` in Round 1; `c1_bypass_proven` in Round 2; and `evidence_error`), while deterministically verifying that every extracted citation is sorted and grounded verbatim in the independently fetched diff/source/proof payload.
3. **Fail-Closed Pinned Evidence Verification**:
   - All external evidence is capped at 25,000 raw bytes (checked prior to UTF-8 decoding). Any non-200 HTTP status, empty payload, or oversized payload fails closed (`UNCLEAR` or `CONTRADICTED`), preventing unverified payouts.
4. **Deterministic Gate Enforcements**:
   - Code-level invariants prevent LLM hallucinations: if the authoritative git diff headers contain no test file patterns (`test/`, `_test.*`, `.t.sol`), test adequacy (`p3_tests_adequate`) is deterministically forced to `CONTRADICTED`, regardless of LLM claims.

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
                                         │ evaluate_patch() (Round 1: commit/<sha>.diff + patched source)
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
         │                                                   │ evaluate_challenge() (Round 2: patched source + proof)
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
| `2` | `STATUS_PATCH_SUBMITTED` | Patch commit submitted; 7-day protected evaluation window active. |
| `3` | `STATUS_CHALLENGE_WINDOW` | Passed Round 1 evaluation; `patched_file_path` locked; 48-hour counter-challenge window active. |
| `4` | `STATUS_REMEDIATION_REQUIRED` | Evaluated as deficient, invalid, or missing tests; revision permitted before deadline. |
| `5` | `STATUS_CHALLENGED` | Counter-exploit submitted with collateral; awaiting Round 2 consensus evaluation. |
| `6` | `STATUS_DEFENDED` | Challenger proof failed against patched source; challenger stake slashed into bounty; whitehat eligible to claim. |
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
1. **Isolated Snapshot (Zero `self` Reference)**: All contract storage parameters are snapshotted into local variables before nondeterministic closures run; module-level helper functions (`_fetch_url_nondet_fn`, `_extract_non_test_patched_file_fn`, `_detect_test_files_fn`, `_parse_llm_dict_fn`) ensure `self` is never referenced inside `leader_fn` or `validator_fn`.
2. **Independent Validator Execution**: Validators independently fetch the pinned advisory, the authoritative GitHub commit diff (`commit/<sha>.diff`), and the post-patch source file (`raw.githubusercontent.com/<repo>/<sha>/<patched_file_path>`), verify raw byte size (`<= 25,000` bytes) before UTF-8 decoding, and ground citations verbatim against the fetched payloads.
3. **Strict Consensus Equality**: A validator casts an approving vote if and only if the leader's proposal matches their independent evaluation across all outcome-determining fields (`commit`/`proof_commit`, `patched_file_path`, `p1_exploit_resolved`, `p2_no_regressions`, `p3_tests_adequate`, `c1_bypass_proven`, `evidence_error`) and all leader citations are canonically sorted and verified verbatim in the independently fetched payload.

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

### Test Suite Coverage Highlights (15/15 Passing)
* `test_uncontested_bounty_lifecycle`: End-to-end happy path: deploy, fund, submit patch, pass Round 1 (authoritative commit diff + patched source), mature through 48h challenge window uncontested, and disburse bounty.
* `test_contested_challenge_refutes_flawed_patch`: Round 2 contested challenge: patch enters challenge window, challenger stakes 10% collateral and submits proof-of-bypass evaluated against the patched source file, consensus refutes the patch, and awards challenger the bounty penalty.
* `test_contested_challenge_defended`: Round 2 contested challenge: challenger submits flawed proof evaluated against the patched source file, consensus confirms patch is substantively defended (`CONTRADICTED`), slashes challenger stake into bounty pool, and pays whitehat the fortified pool.
* `test_challenge_unclear_or_fetch_error_remains_non_final_and_allows_retry`: Proves `UNCLEAR` verdicts or HTTP 503/404/oversized fetch errors in Round 2 remain non-final in `STATUS_CHALLENGED` without releasing the bounty or slashing the challenger's stake, and can be safely retried via `evaluate_challenge()`.
* `test_challenge_unclear_timeout_refunds_stake_and_bounty_without_confiscation`: Proves that if a challenge remains `UNCLEAR` past `review_deadline`, `claim_refund()` returns `challenge_stake` in full to the challenger and `bounty_amount` in full to the sponsor (`STATUS_REFUNDED`).
* `test_small_bounty_strictly_positive_minimum_challenge_stake_ceiling`: Proves small bounty amounts (`5` wei, `15` wei) enforce a strictly positive minimum challenge stake preserving the full $\ge 10\%$ requirement via ceiling division.
* `test_direct_mode_lifecycle_and_storage`: Executes contract deployment, funding, caller switching (`vm.sender`), and patch submission directly through GenLayer's official in-memory engine (`gltest.direct`).
* `test_missing_test_files_forces_contradicted`: Tests deterministic invariant forcing `p3_tests_adequate` to `CONTRADICTED` if no test files are modified in the commit diff.
* `test_adversarial_leader_divergent_field_rejection`: Tests rejection of an adversarial leader attempting to forge citations or predicate values.
* `test_prompt_injection_resistance_system_override`: Tests prompt injection resistance against instruction override attempts embedded in git diffs.

---

## 6. Live Testnet Deployment (GenLayer StudioNet)

* **Network**: GenLayer StudioNet (`https://studio.genlayer.com/api`, Chain ID: `61999`)
* **Contract Address**: [`0x81d7f1C5a69bBbFBfB314C6973Bad8800595a13E`](https://explorer-studio.genlayer.com/address/0x81d7f1C5a69bBbFBfB314C6973Bad8800595a13E)
* **Deployed Commit**: [`329e9a9416ddd291fbbabb19c55e181955a7be24`](https://github.com/khezzed/Auto-VB/commit/329e9a9416ddd291fbbabb19c55e181955a7be24)
* **Git Blob SHA-1 (`contracts/autonomous_vulnerability_bounty.py`)**: `05ab7b0a2f330d37ea2d17010f8735199150b89b` (`36,578` bytes, LF)
* **Release Manifest**: [`release_manifest.json`](release_manifest.json)

### Authoritative Commit & Source Evidence Inspected On-Chain (Commit `9c6b55dacc087f8642a752228a3165ef301b29bd`)
- **Pinned Vulnerability Advisory (`861` bytes)**: [`advisories/GHSA-AUTOVB-2026-001.txt`](https://raw.githubusercontent.com/khezzed/Auto-VB/329e9a9416ddd291fbbabb19c55e181955a7be24/advisories/GHSA-AUTOVB-2026-001.txt)
- **Authoritative GitHub Commit Diff**: [`https://github.com/khezzed/Auto-VB/commit/9c6b55dacc087f8642a752228a3165ef301b29bd.diff`](https://github.com/khezzed/Auto-VB/commit/9c6b55dacc087f8642a752228a3165ef301b29bd.diff)
- **Authoritative Patched Source File (`src/Vault.sol`)**: [`https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/src/Vault.sol`](https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/src/Vault.sol)
- **Authoritative Foundry Unit Test (`test/VaultTest.t.sol`)**: [`https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/test/VaultTest.t.sol`](https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/test/VaultTest.t.sol)
- **Challenger Counter-Exploit Proof (`exploit_proof.py`)**: [`https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/exploit_proof.py`](https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/exploit_proof.py)

### Complete 12-Step On-Chain Transaction Walkthrough

The live contract at [`0x81d7f1C5a69bBbFBfB314C6973Bad8800595a13E`](https://explorer-studio.genlayer.com/address/0x81d7f1C5a69bBbFBfB314C6973Bad8800595a13E) was verified on StudioNet across a 12-transaction sequence demonstrating Round 1 authoritative commit diff + source adjudication, Round 2 staked counter-exploit challenge adjudication against the retrieved patched source (`src/Vault.sol`), substantive `CONTRADICTED` collateral slashing into the bounty pool, final reward settlement, and 5 deliberate security guard failures:

| Step | Action | Transaction Hash | Status | Leader Execution | Verified On-Chain Behavior |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **1** | **Deploy Contract** | [`0x2dbd...d749`](https://explorer-studio.genlayer.com/transactions/0x2dbd0d3b321bd708a1825599586be8a82aff80e90e7d1f7ffae3374ca00fd749) | `FINALIZED` | `SUCCESS` | Contract instantiated (`status = 0`, `target_repo = "khezzed/Auto-VB"`). |
| **2** | **Guard: Non-Sponsor Fund** | [`0x405b...838a`](https://explorer-studio.genlayer.com/transactions/0x405be58034cfe9d5851051d5152ba76696cec06652360a6d179365652f29838a) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Unauthorized caller rejected (`Only the sponsor can fund this bounty.`). |
| **3** | **Fund Bounty** | [`0x1a40...c2d8`](https://explorer-studio.genlayer.com/transactions/0x1a40ef4327117549e671ca02387d41366263708bbd4bbeb430246c957f37c2d8) | `FINALIZED` | `SUCCESS` | Sponsor escrows `1000 wei` (`status = 1`, `bounty_amount = 1000`). |
| **4** | **Guard: Invalid Commit SHA** | [`0x6fec...0e4d`](https://explorer-studio.genlayer.com/transactions/0x6fecb251e59fb1692d9b26591554e88ac3e45bd094b5185f3380dcb79b050e4d) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Non-40-hex commit SHA rejected (`Invalid commit_sha format`). |
| **5** | **Submit Patch** | [`0xfafe...0203`](https://explorer-studio.genlayer.com/transactions/0xfafe0b0b651fd1b20db4b062d4c4e1343cc060c6cd15bf8298109c8fa4b10203) | `FINALIZED` | `SUCCESS` | Whitehat submits commit `9c6b55dacc...` (`status = 2`, `submission_count = 1`). |
| **6** | **Evaluate Patch (Round 1)** | [`0xb6c5...b9cd`](https://explorer-studio.genlayer.com/transactions/0xb6c5c86356c06d9b313d945008180184be2e532e38bc893d916a047544feb9cd) | `FINALIZED` | `SUCCESS` | Validators fetch advisory, authoritative `commit/9c6b55dacc....diff`, and `src/Vault.sol` $\to$ `patched_file_path="src/Vault.sol"`, `p1=HOLDS`, `p2=HOLDS`, `p3=HOLDS` $\to$ `status = 3` (`CHALLENGE_WINDOW`). |
| **7** | **Guard: Premature Claim** | [`0xeef4...5002`](https://explorer-studio.genlayer.com/transactions/0xeef45a499283cb7bcea335b5eb3d5c28992d99a55108852fe797123ffac95002) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Whitehat claim during active 48h challenge window reverts (`Bounty not eligible for claim.`). |
| **8** | **Guard: Under-Staked Challenge** | [`0x9238...5a32`](https://explorer-studio.genlayer.com/transactions/0x92387ed808eca151af9c978296d497753b5aad80c1e6b89311ec459196065a32) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Challenger staking `10 wei` (< 10% minimum `100 wei`) reverts (`Insufficient challenge stake`). |
| **9** | **Submit Challenge** | [`0xff44...f900`](https://explorer-studio.genlayer.com/transactions/0xff447f90703ece30488926b961672b37b6b2f781816c72a69d3a48632167f900) | `FINALIZED` | `SUCCESS` | Challenger stakes `100 wei` (10% collateral) with counter-exploit commit (`status = 5`). |
| **10** | **Evaluate Challenge (Round 2)** | [`0x7afc...df41`](https://explorer-studio.genlayer.com/transactions/0x7afcbb00ea50e4cd195dca29d54025a2b2a11dbc87045658925cde3dcccadf41) | `FINALIZED` | `SUCCESS` | Validators fetch patched `src/Vault.sol`, `commit/9c6b55dacc....diff`, and `exploit_proof.py` $\to$ `c1_bypass_proven = CONTRADICTED` (`evidence_error = NONE`) $\to$ `status = 6` (`STATUS_DEFENDED`), challenger's `100 wei` slashed into bounty (`bounty_amount = 1100`). |
| **11** | **Guard: Unauthorized Claim** | [`0xd032...4a95`](https://explorer-studio.genlayer.com/transactions/0xd032779509cda5feaeb2ddfe586ef11c353264aa08a291b949a7bdab233c4a95) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Non-whitehat attempt to claim defended bounty reverts (`Only the verified whitehat can claim`). |
| **12** | **Claim Fortified Bounty** | [`0x1c3d...03ab`](https://explorer-studio.genlayer.com/transactions/0x1c3d4e21a4b26d8c857048842cd63c7bdfff5876f08e2a8489df5ab6a55003ab) | `FINALIZED` | `SUCCESS` | Whitehat claims fortified `1100 wei` pool (`1000` base + `100` slashed stake) $\to$ `status = 8` (`STATUS_SETTLEMENT_EMITTED`), `bounty_amount = 0`. |
