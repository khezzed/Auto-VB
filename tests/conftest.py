import sys
import types
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

# Type variables
K = TypeVar("K")
V = TypeVar("V")
T = TypeVar("T")


class u256(int):
    """GenLayer u256 primitive type."""
    def __new__(cls, val=0):
        v = int(val)
        if v < 0 or v >= (1 << 256):
            raise OverflowError("u256 overflow or negative value")
        return super().__new__(cls, v)

    def __add__(self, other):
        return u256(int(self) + int(other))

    def __sub__(self, other):
        res = int(self) - int(other)
        if res < 0:
            raise OverflowError("u256 underflow")
        return u256(res)

    def __mul__(self, other):
        return u256(int(self) * int(other))

    def __floordiv__(self, other):
        return u256(int(self) // int(other))

    def __radd__(self, other):
        return u256(int(other) + int(self))

    def __rsub__(self, other):
        res = int(other) - int(self)
        if res < 0:
            raise OverflowError("u256 underflow")
        return u256(res)


class Address(str):
    """GenLayer Address primitive type."""
    def __new__(cls, val="0x0000000000000000000000000000000000000000"):
        v = str(val).lower()
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError(f"Invalid Address format: {val}")
        return super().__new__(cls, v)


class TreeMap(Generic[K, V], dict):
    """GenLayer TreeMap storage primitive."""
    pass


class DynArray(Generic[T], list):
    """GenLayer DynArray storage primitive."""
    pass


def allow_storage(cls):
    """Storage decorator."""
    return cls


class _ReturnWrapper:
    """Wrapper corresponding to gl.vm.Return."""
    def __init__(self, calldata: Any):
        self.calldata = calldata


class UserError(Exception):
    """User-facing contract revert."""
    pass


# Global execution context mock
class MessageContext:
    def __init__(self):
        self.sender_address = Address("0x1111111111111111111111111111111111111111")
        self.value = u256(0)


class MockWebResponse:
    def __init__(self, status_code: int, body: bytes, headers: dict = None):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}


# Emitted external transfer record
@dataclass
class EmittedTransfer:
    recipient: Address
    value: u256
    execution_timing: str


emitted_transfers: list[EmittedTransfer] = []
mock_web_responses: dict[str, MockWebResponse] = {}
mock_llm_responses: list[Callable[[str], dict]] = []


class GenLayerMock:
    def __init__(self):
        self.message = MessageContext()
        self.message_raw = {"datetime": "2026-10-16T21:40:00+00:00"}
        
        # Submodules
        self.vm = types.SimpleNamespace(
            Return=_ReturnWrapper,
            UserError=UserError,
            run_nondet_unsafe=self._run_nondet_unsafe,
        )
        
        self.nondet = types.SimpleNamespace(
            web=types.SimpleNamespace(get=self._web_get, render=self._web_render),
            exec_prompt=self._exec_prompt,
        )
        
        # Public method decorators
        class _WriteDecorator:
            def __call__(self, fn):
                fn.__is_public_write__ = True
                return fn

            def payable(self, fn):
                fn.__is_public_write__ = True
                fn.__is_payable__ = True
                return fn

        self.public = types.SimpleNamespace(
            write=_WriteDecorator(),
            view=self._decorator_view,
        )
        
        # EVM interface decorator
        self.evm = types.SimpleNamespace(
            contract_interface=self._contract_interface_decorator
        )

    def _decorator_write(self, fn):
        fn.__is_public_write__ = True
        return fn

    def _decorator_payable(self, fn):
        fn.__is_public_write__ = True
        fn.__is_payable__ = True
        return fn

    def _decorator_view(self, fn):
        fn.__is_public_view__ = True
        return fn

    def _contract_interface_decorator(self, cls):
        class BoundContractInterface:
            def __init__(self, target_address: Address):
                self.target_address = target_address

            def emit_transfer(self, value: u256, on: str = "finalized"):
                emitted_transfers.append(
                    EmittedTransfer(
                        recipient=self.target_address,
                        value=u256(value),
                        execution_timing=on,
                    )
                )

        return BoundContractInterface

    def _web_get(self, url: str) -> MockWebResponse:
        if url in mock_web_responses:
            return mock_web_responses[url]
        # Default 404 if not registered
        return MockWebResponse(status_code=404, body=b'{"message": "Not Found"}')

    def _web_render(self, url: str, mode: str = "text") -> MockWebResponse:
        return self._web_get(url)

    def _exec_prompt(self, prompt: str, response_format: str = "json") -> dict:
        if mock_llm_responses:
            fn = mock_llm_responses[-1]
            return fn(prompt)
        return {
            "exploit_plausibly_resolved": True,
            "no_material_regression_identified": True,
            "test_substance_adequate": True,
            "plausibility_score": 85,
            "evidence_citations": ["+ fix"],
            "residual_risks": "None identified",
            "uncertainty_rating": "LOW",
        }

    def _run_nondet_unsafe(self, leader_fn: Callable[[], Any], validator_fn: Callable[[Any], bool]) -> Any:
        leader_res = leader_fn()
        wrapped = _ReturnWrapper(calldata=leader_res)
        valid = validator_fn(wrapped)
        if not valid:
            raise UserError("Validator equivalence failed: leader result rejected by committee.")
        return leader_res


class ContractBase:
    """Base class for gl.Contract."""
    def __init__(self):
        self._balance = u256(0)

    @property
    def balance(self) -> u256:
        return self._balance

    @balance.setter
    def balance(self, val: u256):
        self._balance = u256(val)


# Install mock into sys.modules so `from genlayer import *` works
genlayer_module = types.ModuleType("genlayer")
genlayer_module.u256 = u256
genlayer_module.Address = Address
genlayer_module.TreeMap = TreeMap
genlayer_module.DynArray = DynArray
genlayer_module.allow_storage = allow_storage
genlayer_module.UserError = UserError

gl_instance = GenLayerMock()
gl_instance.Contract = ContractBase
genlayer_module.gl = gl_instance

sys.modules["genlayer"] = genlayer_module
