import requests, time
from typing import Union, List, Any
from web3.types import RPCEndpoint, RPCResponse
import genlayer_py as gl
from genlayer_py.provider.provider import GenLayerProvider
from genlayer_py.exceptions import GenLayerError

def custom_make_request(self, method: Union[RPCEndpoint, str], params: List[Any]) -> RPCResponse:
    payload = {
        'jsonrpc': '2.0',
        'id': int(time.time() * 1000),
        'method': method,
        'params': params,
    }
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    try:
        response = requests.post(self.url, json=payload, headers=headers, timeout=30)
    except requests.exceptions.RequestException as err:
        raise GenLayerError(f'Request to {self.url} failed: {str(err)}') from err
    try:
        resp = response.json()
    except ValueError as err:
        raise GenLayerError(f'{method} returned invalid JSON: {err}') from err
    self._raise_on_error(resp, method)
    return resp

GenLayerProvider.make_request = custom_make_request

with open('contracts/autonomous_vulnerability_bounty.py', 'r', encoding='utf-8') as f:
    contract_code = f.read()

account = gl.create_account()
client = gl.create_client(chain=gl.studionet, account=account)
print(f"Deployer Account: {account.address}", flush=True)

tx_fund = client.fund_account(account.address, 10**18)
print(f"Funded deployer with 1 GEN (tx: {tx_fund.hex()})", flush=True)

args = [
    'uniswap/v4-core',
    'https://raw.githubusercontent.com/uniswap/v4-core/v1.0.0/advisories/GHSA-1234.txt',
    2592000
]

print("Submitting deploy_contract transaction...", flush=True)
tx_id = client.deploy_contract(code=contract_code, args=args, leader_only=False)
print(f"Deployment Tx ID: {tx_id}", flush=True)

print("Awaiting consensus finalization...", flush=True)
receipt = client.wait_for_transaction_receipt(tx_id)
print(f"Status: {receipt.get('status_name')} (code: {receipt.get('status')})", flush=True)
print(f"Result: {receipt.get('result_name')} (code: {receipt.get('result')})", flush=True)

deployed_address = receipt.get('recipient') or receipt.get('to_address')
print(f"Deployed Contract Address: {deployed_address}", flush=True)
print(f"GenLayer Studio Explorer URL: https://explorer-studio.genlayer.com/address/{deployed_address}", flush=True)
print(f"Transaction Explorer URL: https://explorer-studio.genlayer.com/transactions/{tx_id}", flush=True)
