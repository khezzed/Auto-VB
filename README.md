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
   - **Round 2 (Economic Counter-Exploit Challenge Against Patched Source)**: If qualified in Round 1, the contract records `patched_file_path` in storage and enters a 48-hour challenge window. Any third-party researcher can stake collateral ($\ge 10\%$ of the bounty pool) and submit a counter-exploit commit (`challenge_commit`). Validators independently retrieve **both**:
     1. The **authoritative patched source file** (`https://raw.githubusercontent.com/{target_repo}/{patch_commit}/{patched_file_path}`) and **authoritative commit diff** (`commit/{patch_commit}.diff`).
     2. The **challenger's counter-exploit proof** (`https://raw.githubusercontent.com/{target_repo}/{challenge_commit}/exploit_proof.py`).
     - **If Refuted (`c1_bypass_proven == HOLDS`)**: The patch is rejected, the whitehat is disqualified, and the challenger receives their stake back plus a 50% bounty penalty reward.
     - **If Defended (`c1_bypass_proven != HOLDS`)**: The challenger's stake is slashed directly into the bounty pool, and the whitehat is immediately eligible to claim the fortified reward.
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

### Test Suite Coverage Highlights (12/12 Passing)
* `test_uncontested_bounty_lifecycle`: End-to-end happy path: deploy, fund, submit patch, pass Round 1 (authoritative commit diff + patched source), mature through 48h challenge window uncontested, and disburse bounty.
* `test_contested_challenge_refutes_flawed_patch`: Round 2 contested challenge: patch enters challenge window, challenger stakes 10% collateral and submits proof-of-bypass evaluated against the patched source file, consensus refutes the patch, and awards challenger the bounty penalty.
* `test_contested_challenge_defended`: Round 2 contested challenge: challenger submits flawed proof evaluated against the patched source file, consensus confirms patch is defended, slashes challenger stake into bounty pool, and pays whitehat the fortified pool.
* `test_direct_mode_lifecycle_and_storage`: Executes contract deployment, funding, caller switching (`vm.sender`), and patch submission directly through GenLayer's official in-memory engine (`gltest.direct`).
* `test_missing_test_files_forces_contradicted`: Tests deterministic invariant forcing `p3_tests_adequate` to `CONTRADICTED` if no test files are modified in the commit diff.
* `test_adversarial_leader_divergent_field_rejection`: Tests rejection of an adversarial leader attempting to forge citations or predicate values.
* `test_prompt_injection_resistance_system_override`: Tests prompt injection resistance against instruction override attempts embedded in git diffs.

---

## 6. Live Testnet Deployment (GenLayer StudioNet)

* **Network**: GenLayer StudioNet (`https://studio.genlayer.com/api`, Chain ID: `61999`)
* **Contract Address**: [`0xE05c54769D4f784E80167Ac8799d7e8Da9015982`](https://explorer-studio.genlayer.com/address/0xE05c54769D4f784E80167Ac8799d7e8Da9015982)
* **Deployed Commit**: [`9c6b55dacc087f8642a752228a3165ef301b29bd`](https://github.com/khezzed/Auto-VB/commit/9c6b55dacc087f8642a752228a3165ef301b29bd)
* **Git Blob SHA-1 (`contracts/autonomous_vulnerability_bounty.py`)**: `ff76ded0123ab26073542c9e3c3bc08e449c5d20` (`34,586` bytes, LF)
* **Release Manifest**: [`release_manifest.json`](release_manifest.json)

### Authoritative Commit & Source Evidence Inspected On-Chain (Commit `9c6b55dacc087f8642a752228a3165ef301b29bd`)
- **Pinned Vulnerability Advisory (`861` bytes)**: [`advisories/GHSA-AUTOVB-2026-001.txt`](https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/advisories/GHSA-AUTOVB-2026-001.txt)
- **Authoritative GitHub Commit Diff**: [`https://github.com/khezzed/Auto-VB/commit/9c6b55dacc087f8642a752228a3165ef301b29bd.diff`](https://github.com/khezzed/Auto-VB/commit/9c6b55dacc087f8642a752228a3165ef301b29bd.diff)
- **Authoritative Patched Source File (`src/Vault.sol`)**: [`https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/src/Vault.sol`](https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/src/Vault.sol)
- **Authoritative Foundry Unit Test (`test/VaultTest.t.sol`)**: [`https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/test/VaultTest.t.sol`](https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/test/VaultTest.t.sol)
- **Challenger Counter-Exploit Proof (`exploit_proof.py`)**: [`https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/exploit_proof.py`](https://raw.githubusercontent.com/khezzed/Auto-VB/9c6b55dacc087f8642a752228a3165ef301b29bd/exploit_proof.py)

### Complete 12-Step On-Chain Transaction Walkthrough

The live contract at [`0xE05c54769D4f784E80167Ac8799d7e8Da9015982`](https://explorer-studio.genlayer.com/address/0xE05c54769D4f784E80167Ac8799d7e8Da9015982) was verified on StudioNet across a 12-transaction sequence demonstrating Round 1 authoritative commit diff + source adjudication, Round 2 staked counter-exploit challenge adjudication against the retrieved patched source (`src/Vault.sol`), collateral slashing into the bounty pool, final reward settlement, and 5 deliberate security guard failures:

| Step | Action | Transaction Hash | Status | Leader Execution | Verified On-Chain Behavior |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **1** | **Deploy Contract** | [`0x4248...ae9b`](https://explorer-studio.genlayer.com/transactions/0x4248774e4265aa0d720631db4361ef7be2fdad5db24cbc6ba5426216f4a7ae9b) | `FINALIZED` | `SUCCESS` | Contract instantiated (`status = 0`, `target_repo = "khezzed/Auto-VB"`). |
| **2** | **Guard: Non-Sponsor Fund** | [`0x153a...592f`](https://explorer-studio.genlayer.com/transactions/0x153aefb40f357a93fd7e76fd97ed6523ac7834f89f90811d2995863d75f2592f) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Unauthorized caller rejected (`Only the sponsor can fund this bounty.`). |
| **3** | **Fund Bounty** | [`0xa6f7...0bdb`](https://explorer-studio.genlayer.com/transactions/0xa6f74f22f48e26ea04a1660b95273219bdb48989f9d59351c229d4276b250bdb) | `FINALIZED` | `SUCCESS` | Sponsor escrows `1000 wei` (`status = 1`, `bounty_amount = 1000`). |
| **4** | **Guard: Invalid Commit SHA** | [`0x1dbb...1794`](https://explorer-studio.genlayer.com/transactions/0x1dbb6d8e357e00786b44201f03473957a6dff9ccd529cd86fbd0c6c719081794) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Non-40-hex commit SHA rejected (`Invalid commit_sha format`). |
| **5** | **Submit Patch** | [`0x0403...2da4`](https://explorer-studio.genlayer.com/transactions/0x04030c7b85fc9e84d8eb43e78666c044fed6bad7b2afb98d8757dc2ff7382da4) | `FINALIZED` | `SUCCESS` | Whitehat submits commit `9c6b55dacc...` (`status = 2`, `submission_count = 1`). |
| **6** | **Evaluate Patch (Round 1)** | [`0x223a...0680`](https://explorer-studio.genlayer.com/transactions/0x223a8b7c6ba96e658d5ccb0473b5b396b18aaaba823bfd64629ff75967b00680) | `FINALIZED` | `SUCCESS` | Validators fetch advisory, authoritative `commit/9c6b55dacc....diff`, and `src/Vault.sol` $\to$ `patched_file_path="src/Vault.sol"`, `p1=HOLDS`, `p2=HOLDS`, `p3=HOLDS` $\to$ `status = 3` (`CHALLENGE_WINDOW`). |
| **7** | **Guard: Premature Claim** | [`0xe6bc...635b`](https://explorer-studio.genlayer.com/transactions/0xe6bc85d5c80ac7bb6c5c907d031cbc38269cce9e7b2553ab5edded5e7efa635b) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Whitehat claim during active 48h challenge window reverts (`Bounty not eligible for claim.`). |
| **8** | **Guard: Under-Staked Challenge** | [`0x657a...a975`](https://explorer-studio.genlayer.com/transactions/0x657a38037855d18e31b2517492e0e96e4b7527f9857bdf6c71998adb605ba975) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Challenger staking `10 wei` (< 10% minimum `100 wei`) reverts (`Insufficient challenge stake`). |
| **9** | **Submit Challenge** | [`0xd443...01b5`](https://explorer-studio.genlayer.com/transactions/0xd4431b8389d46b53ec3c20c80766ae3468ce5842599d75d905966cdedd9301b5) | `FINALIZED` | `SUCCESS` | Challenger stakes `100 wei` (10% collateral) with counter-exploit commit (`status = 5`). |
| **10** | **Evaluate Challenge (Round 2)** | [`0x1297...514e`](https://explorer-studio.genlayer.com/transactions/0x129797fa4b6ce174a6e48c2395720843df6286e034c49e21e945c373f60c514e) | `FINALIZED` | `SUCCESS` | Validators fetch patched `src/Vault.sol`, `commit/9c6b55dacc....diff`, and `exploit_proof.py` $\to$ `c1_bypass_proven = CONTRADICTED` (citing `"balances[msg.sender] -= amount;"`) $\to$ `status = 6` (`STATUS_DEFENDED`), challenger's `100 wei` slashed into bounty (`bounty_amount = 1100`). |
| **11** | **Guard: Unauthorized Claim** | [`0xa884...b5b4`](https://explorer-studio.genlayer.com/transactions/0xa88489fee5bf91bfde9b315d019a124843459bbfea5504a0d0dcc38950d3b5b4) | `FINALIZED` | `ERROR` | `EXPECTED FAILURE`: Non-whitehat attempt to claim defended bounty reverts (`Only the verified whitehat can claim`). |
| **12** | **Claim Fortified Bounty** | [`0x029d...edf7`](https://explorer-studio.genlayer.com/transactions/0x029da3242bbf19cab0662ea1c8787dd6b2fcdd9174ae1bb4dfc9fc66e636edf7) | `FINALIZED` | `SUCCESS` | Whitehat claims fortified `1100 wei` pool (`1000` base + `100` slashed stake) $\to$ `status = 8` (`STATUS_SETTLEMENT_EMITTED`), `bounty_amount = 0`. |
