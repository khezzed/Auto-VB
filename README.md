# AutonomousVulnerabilityBounty (GenLayer Intelligent Contract Primitive)

A production-grade, standalone **GenLayer Intelligent Contract** primitive engineered for the **GenLayer Builder Portal ("Contracts" Track)**.

It implements an autonomous, contested two-round vulnerability remediation and bounty adjudication mechanism powered by **GenLayer's GenVM, Optimistic Democracy, and Equivalence Principle consensus**.

---

## 1. Executive Summary & Problem Context

In Web3 security, bug bounty platforms (e.g., Immunefi, Code4rena) process millions of dollars annually but suffer from two critical limitations:
1. **Centralized Triage Bottleneck**: Protocols and whitehats depend on opaque human triage teams to review patches, evaluate exploit reproduction, and decide payouts, introducing 30–90 day payment delays.
2. **Solidity / EVM Blindness**: Standard smart contracts cannot inspect git diffs, examine security advisories, or verify whether a patch resolves a vulnerability without introducing regressions.

**The Solution**: `AutonomousVulnerabilityBounty` enables a protocol sponsor to lock a native `GEN` bounty in escrow and autonomously evaluate submitted patches.

### What Makes This Contract Distinctive (150-Point Mechanism)
Unlike generic templates that merely pass a diff to an LLM for arbitrary scoring ($0-100$) with fuzzy tolerance ($\Delta \le 12$), this contract implements:
1. **Contested Two-Stage Adjudication**:
   - **Round 1 (Patch Qualification)**: Whitehat submits a patch pinned to an immutable commit on `raw.githubusercontent.com`. Validators independently evaluate bounded discrete predicates (`p1_exploit_resolved`, `p2_no_regressions`, `p3_tests_adequate`).
   - **Round 2 (Economic Counter-Exploit Challenge)**: During a 48-hour challenge window, any challenger can stake collateral to submit a proof-of-bypass commit. Validators evaluate whether the proof demonstrates that the flaw persists or regressions exist. If proven, the patch is refuted, whitehat is rejected, and the challenger earns the challenge reward.
2. **Exact Canonical Equality Consenus**:
   - Zero fuzzy numeric margins. Consensus requires `canonical(leader_result) == canonical(validator_result)`.
3. **Fail-Closed Pinned Evidence**:
   - Pinned to `raw.githubusercontent.com` blobs with strict byte limits (max 25,000 bytes). Any 404, 503, or truncation maps strictly to `UNCLEAR`, preventing unverified payouts.

---

## 2. Core Architecture & Lifecycle State Machine

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

## 3. Authoritative State Machine

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

## 4. Consensus & Equivalence Specifications

### A. Strict Allowlist & Bounded Classifications
The LLM never chooses outcomes or numeric points directly. It only classifies bounded atomic predicates:
- `HOLDS`
- `CONTRADICTED`
- `UNCLEAR`

Any unrecognized token or non-conforming JSON defaults strictly to `UNCLEAR`.

### B. Deterministic Invariant Enforcement
- **Test File Invariant**: If no test file patterns (`test/`, `_test.*`, `.t.sol`) exist in the diff, `p3_tests_adequate` is deterministically forced to `CONTRADICTED`, regardless of LLM claims.
- **Verbatim Citation Grounding**: All citations returned by the LLM must exist verbatim in the independently fetched diff, or consensus rejects the proposal.
- **Canonical Equality**: Validator independently fetches the raw files, runs the rubric, canonicalizes the JSON representation, and asserts byte-for-byte identity with the leader's calldata.

---

## 5. Settlement Semantics & Limitations

Per the official [GenLayer Value Transfers Specification](https://docs.genlayer.com/developers/intelligent-contracts/features/value-transfers):
* When `claim_bounty()`, `claim_refund()`, or challenger payout executes:
  1. Internal accounting is zeroed immediately.
  2. `_Recipient(address).emit_transfer(value=amount)` emits an external transaction message.
  3. The contract balance (`self.balance`) is deducted immediately.
* **Child Transaction Semantics**: External transfers execute asynchronously on finalization. If a child transaction fails on the chain layer, the value is not automatically returned to the contract balance.
* **On-Chain Meaning**: Both `STATUS_SETTLEMENT_EMITTED` and `STATUS_REFUNDED` represent cryptographic authorization and emission of payment.

---

## 6. Verification & Test Suite

The contract passes the official GenLayer toolchain (`genvm-linter`, `genlayer-test`, and `pyright`):

```powershell
# 1. Run official GenVM linter & validator
$env:PYTHONIOENCODING="utf-8"
genvm-lint check contracts/autonomous_vulnerability_bounty.py

# 2. Run Pyright type checking against GenVM SDK types
genvm-lint typecheck contracts/autonomous_vulnerability_bounty.py

# 3. Run full test suite (unit, adversarial, and direct-mode)
python -m pytest tests/ -v
```

---

## 7. GenLayer Studio Deployment Guide

To deploy and demonstrate `AutonomousVulnerabilityBounty` in [GenLayer Studio](https://studio.genlayer.com/contracts):

1. Open **GenLayer Studio** (`https://studio.genlayer.com/contracts`).
2. Create a new contract file: `autonomous_vulnerability_bounty.py`.
3. Paste the contents of `contracts/autonomous_vulnerability_bounty.py`.
4. Deploy the contract by providing constructor arguments:
   - `target_repo`: e.g., `"uniswap/v4-core"`
   - `advisory_pinned_url`: e.g., `"https://raw.githubusercontent.com/uniswap/v4-core/v1.0.0/advisories/GHSA-1234.txt"`
   - `duration_seconds`: e.g., `2592000` (30 days)
5. Fund the bounty by calling `fund_bounty()` and attaching native `GEN` tokens.
6. Submit a patch commit by calling `submit_patch(commit_sha)`.
7. Trigger consensus evaluation by calling `evaluate_patch()`.
8. Once the challenge window matures (or if challenged and defended), call `claim_bounty()` to disburse reward.
