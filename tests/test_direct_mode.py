"""Direct-mode execution tests using official GenLayer in-memory engine (gltest.direct)."""

import os
import sys
import tempfile
from pathlib import Path
import pytest

from gltest.direct.vm import VMContext
import gltest.direct.loader as loader

# Windows file-locking monkeypatch for os.unlink after os.dup2
_orig_inject = loader._inject_message_to_fd0


def _win_safe_inject_message_to_fd0(vm):
    from genlayer.py import calldata
    message_data = vm.get_message_raw()
    encoded = calldata.encode(message_data)
    fd, path = tempfile.mkstemp()
    try:
        os.write(fd, encoded)
        os.lseek(fd, 0, os.SEEK_SET)
        original_stdin = os.dup(0)
        vm._original_stdin_fd = original_stdin
        os.dup2(fd, 0)
    finally:
        os.close(fd)
        try:
            os.unlink(path)
        except OSError:
            pass


loader._inject_message_to_fd0 = _win_safe_inject_message_to_fd0


TARGET_REPO = "uniswap/v4-core"
ADVISORY_URL = "https://raw.githubusercontent.com/uniswap/v4-core/v1.0.0/advisories/GHSA-1234.txt"
PATCH_COMMIT = "a" * 40


def test_direct_mode_lifecycle_and_storage():
    """Verify deployment, funding, submission, and initial state via official GenVM direct runner."""
    saved_genlayer = sys.modules.get("genlayer")
    if saved_genlayer is not None and not hasattr(saved_genlayer, "__file__"):
        del sys.modules["genlayer"]

    try:
        vm = VMContext()
        sponsor = loader.create_address("sponsor")
        whitehat = loader.create_address("whitehat")
        vm.sender = sponsor

        with vm.activate():
            # 1. Deploy via direct GenVM loader
            contract = loader.deploy_contract(
                Path("contracts/autonomous_vulnerability_bounty.py"),
                vm,
                target_repo=TARGET_REPO,
                advisory_pinned_url=ADVISORY_URL,
                duration_seconds=86400 * 30,
                sdk_version="v0.2.16",
            )
            assert contract.target_repo == TARGET_REPO
            assert contract.status == 0
            assert contract.submission_count == 0

            # 2. Fund bounty via direct message value
            vm.value = 10 * 10**18
            contract.fund_bounty()
            assert contract.status == 1
            assert contract.bounty_amount == 10 * 10**18

            # 3. Submit patch via whitehat sender
            vm.sender = whitehat
            vm.value = 0
            contract.submit_patch(commit_sha=PATCH_COMMIT)
            assert contract.status == 2
            assert contract.submission_count == 1

            # Verify active submission structure & initial UNCLEAR predicates
            state = contract.get_bounty_state()
            assert state["status"] == 2
            assert state["patch_commit"] == PATCH_COMMIT
            
            audit = contract.get_patch_audit()
            assert audit["target_commit"] == PATCH_COMMIT
            assert audit["p1_exploit_resolved"] == "UNCLEAR"
    finally:
        if saved_genlayer is not None:
            sys.modules["genlayer"] = saved_genlayer
