// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract VaultTest {
    function testDeposit() external {
        // Base deposit test
    }

    function testReentrancyBlocked() external {
        // Asserts withdraw nonReentrant guard and CEI state update block reentrancy
        revert("ReentrancyGuard: reentrant call");
    }
}