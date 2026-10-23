// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {Vault} from "../src/Vault.sol";

contract ReentrantAttacker {
    Vault public vault;

    constructor(Vault _vault) {
        vault = _vault;
    }

    function attackWithdraw() external payable {
        vault.deposit{value: 1 ether}();
        vault.withdraw(1 ether);
    }

    receive() external payable {
        vault.withdraw(1 ether);
    }
}

contract VaultTest is Test {
    Vault public vault;
    ReentrantAttacker public attacker;

    function setUp() public {
        vault = new Vault();
        attacker = new ReentrantAttacker(vault);
        vm.deal(address(vault), 10 ether);
        vm.deal(address(attacker), 1 ether);
    }

    function testReentrancyBlocked() external {
        vm.expectRevert("Transfer failed");
        attacker.attackWithdraw();
        assertEq(address(vault).balance, 10 ether);
    }
}
