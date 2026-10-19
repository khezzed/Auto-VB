# AutonomousVulnerabilityBounty

An autonomous, contested two-round vulnerability remediation and bounty adjudication Intelligent Contract for GenLayer.

`AutonomousVulnerabilityBounty` enables open-source projects and decentralized protocols to escrow native bounties, evaluate whitehat vulnerability patches via decentralized validator consensus, and subject proposed fixes to an adversarial, staked counter-exploit challenge window before funds are disbursed.

---

## 1. Overview & Problem Context

Traditional bug bounty programs (e.g., Immunefi, HackerOne, Code4rena) process millions of dollars annually but suffer from two core limitations:
1. **Centralized Triage Bottleneck**: Protocols and researchers depend on centralized triage teams to verify exploit reproduction, assess patch validity, and authorize payments. This introduces 30–90 day disbursement delays, opaque dispute resolutions, and single points of failure.
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
2. **Exact Canonical Equality Consensus**:
   - Eliminates fuzzy numerical margins and subjective score thresholds. Consensus requires byte-for-byte canonical identity between the leader's calldata and the validator committee's independent evaluation (`canonical(leader_result) == canonical(validator_result)`).
3. **Fail-Closed Pinned Evidence Verification**:
   - All external evidence is pinned to immutable raw git blobs on `raw.githubusercontent.com` capped at 25,000 raw bytes. Any non-200 HTTP status, empty payload, or truncation deterministically maps to `UNCLEAR`, preventing unverified payouts.
4. **Deterministic Gate Enforcements**:
   - Code-level invariants prevent LLM hallucinations: if git diff headers contain no test file patterns (`test/`, `_test.*`, `.t.sol`), test adequacy is deterministically forced to `CONTRADICTED`, regardless of LLM claims.

---

## 2. Architecture & Lifecycle State Machine

```
                                  [STATUS_CREATED]
                                         │ fund_bounty() (Sponsor deposit)
                                         ▼
                                  [STATUS_FUNDED]
                                         │ submit_patch(commit_sha) (Whitehat)
                                         ▼
                             [STATUS_PATCH_SUBMITTED]
                                         │ evaluate_patch() (Permissionless)
                     ┌───────────────────┴───────────────────┐
                     ▼                                       ▼
        All Atoms == HOLDS                      Any Atom != HOLDS
                     │                                       │
                     ▼                                       ▼
         [STATUS_CHALLENGE_WINDOW]              [STATUS_REMEDIATION_REQUIRED]
                     │
         ┌───────────┴───────────────────────────────┐
         │ No challenge within 48h                   │ submit_challenge() (Challenger + 10% stake)
         ▼                                           ▼
   claim_bounty()                            [STATUS_CHALLENGED]
         │                                           │ evaluate_challenge()
         ▼                                   ┌───────┴───────┐
[STATUS_SETTLEMENT_EMITTED]                  ▼               ▼
                                       C1 == HOLDS      C1 != HOLDS
                                             │               │
                                             ▼               ▼
                                    [STATUS_REFUTED]   [STATUS_DEFENDED]
                                             │               │
                                             ▼               ▼
                                    Challenger paid    Whitehat paid
```

---

## 3. State Machine Specification

| Status Code | Constant Name | Description |
| :---: | :--- | :--- |
| `0` | `STATUS_CREATED` | Initialized via constructor; immutable parameters locked; awaiting funding. |
| `1` | `STATUS_FUNDED` | Escrow funded with native `GEN` by sponsor; open for whitehat patch submissions. |
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
1. **Isolated Snapshot**: All contract storage parameters are snapshotted into local variables before nondeterministic closures run; `self` is never referenced inside consensus closures.
2. **Independent Validator Execution**: Validators independently fetch the pinned raw evidence, run local evaluations, ground citations against actual diff contents, and canonicalize output objects.
3. **Exact Equality**: A validator casts an approving vote if and only if every field of the leader's proposal matches their independent result:
   - `commit` SHA identity
   - `p1_exploit_resolved` match
   - `p2_no_regressions` match
   - `p3_tests_adequate` match
   - `citations` verbatim match
   - `evidence_error` status match

---

## 5. Settlement Semantics & Value Transfers

Per the official [GenLayer Value Transfers Specification](https://docs.genlayer.com/developers/intelligent-contracts/features/value-transfers):
* When `claim_bounty()`, `claim_refund()`, or challenger payout executes:
  1. Internal accounting is zeroed immediately.
  2. `_Recipient(address).emit_transfer(value=amount)` emits an external transaction message.
  3. The contract balance (`self.balance`) is deducted immediately.
* **Child Transaction Semantics**: External transfers execute asynchronously on transaction finalization. If a child transaction fails on the chain layer, the value is not automatically returned to the contract balance.
* **On-Chain Meaning**: Both `STATUS_SETTLEMENT_EMITTED` and `STATUS_REFUNDED` represent cryptographic authorization and emission of payment.

---

## 6. Verification & Test Suite

The contract has been validated using the official GenLayer toolchain (`genvm-linter`, `genlayer-test`, and `pyright`):

```powershell
# 1. Run official GenVM linter & validator
$env:PYTHONIOENCODING="utf-8"
genvm-lint check contracts/autonomous_vulnerability_bounty.py

# 2. Run Pyright type checking against GenVM SDK types
genvm-lint typecheck contracts/autonomous_vulnerability_bounty.py

# 3. Run full test suite (unit, adversarial, and direct-mode)
python -m pytest tests/ -v
```

### Test Suite Coverage Highlights
* `test_uncontested_bounty_lifecycle`: End-to-end happy path: deploy, fund, submit patch, pass Round 1, mature through 48h challenge window uncontested, and disburse bounty.
* `test_contested_challenge_refutes_flawed_patch`: Round 2 contested challenge: patch enters challenge window, challenger stakes 10% collateral and submits proof-of-bypass, consensus refutes the patch, and awards challenger the bounty penalty.
* `test_contested_challenge_defended`: Round 2 contested challenge: challenger submits flawed proof, consensus confirms patch is defended, slashes challenger stake into bounty pool, and pays whitehat the fortified pool.
* `test_direct_mode_lifecycle_and_storage`: Executes contract deployment, funding, caller switching (`vm.sender`), and patch submission directly through GenLayer's official in-memory engine (`gltest.direct`).
* `test_missing_test_files_forces_contradicted`: Tests deterministic invariant forcing `p3_tests_adequate` to `CONTRADICTED` if no test files are modified.
* `test_adversarial_leader_divergent_field_rejection`: Tests rejection of an adversarial leader attempting to forge citations or predicate values.
* `test_prompt_injection_resistance_system_override`: Tests prompt injection resistance against instruction override attempts embedded in git diffs.

---

## 7. Live Deployment & Explorer Verification

The contract is deployed and verified live on **GenLayer Studio Network (Studionet)**:

* **Contract Address**: [`0x644e2994bdd02e3576D05B2BeA6d210E26082695`](https://explorer-studio.genlayer.com/address/0x644e2994bdd02e3576D05B2BeA6d210E26082695)
* **Studio Explorer URL**: [https://explorer-studio.genlayer.com/address/0x644e2994bdd02e3576D05B2BeA6d210E26082695](https://explorer-studio.genlayer.com/address/0x644e2994bdd02e3576D05B2BeA6d210E26082695)
* **Deployment Transaction**: [`0xfae2a22d3b2ae7dbf0a8c627c156d3f85970fa97fce2898b428bfbf18edd9717`](https://explorer-studio.genlayer.com/transactions/0xfae2a22d3b2ae7dbf0a8c627c156d3f85970fa97fce2898b428bfbf18edd9717)
* **Consensus Status**: `ACCEPTED / FINALIZED` (Consensus Result: `MAJORITY_AGREE`, 5/5 validator consensus)

---

## 8. Deployment Guide (GenLayer Studio UI)

To deploy another instance of `AutonomousVulnerabilityBounty` in [GenLayer Studio](https://studio.genlayer.com/contracts):

1. Open **GenLayer Studio** (`https://studio.genlayer.com/contracts`).
2. Create a new contract file: `autonomous_vulnerability_bounty.py`.
3. Paste the contents of [`contracts/autonomous_vulnerability_bounty.py`](contracts/autonomous_vulnerability_bounty.py).
4. Deploy the contract by providing constructor arguments:
   - `target_repo`: e.g., `"uniswap/v4-core"`
   - `advisory_pinned_url`: e.g., `"https://raw.githubusercontent.com/uniswap/v4-core/v1.0.0/advisories/GHSA-1234.txt"`
   - `duration_seconds`: e.g., `2592000` (30 days)
5. Fund the bounty by calling `fund_bounty()` and attaching native `GEN` tokens.
6. Submit a patch commit by calling `submit_patch(commit_sha)`.
7. Trigger consensus evaluation by calling `evaluate_patch()`.
8. Once the challenge window matures (or if challenged and defended), call `claim_bounty()` to disburse the reward.
