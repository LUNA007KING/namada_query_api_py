import uuid
import base64
import aiohttp
from typing import Any, Dict, Optional, Union, List, Tuple
from urllib.parse import urljoin
import asyncio
from namada_types.general import ValidatorState, ValidatorMetaData, U64
from namada_types.rust_py import address_parse, commission_pair_parse, proposal_parse, votes_parse, \
    proposal_result_parse


class Result:
    def __init__(self, success: bool, data: Optional[Any] = None, error: Optional[str] = None):
        self.success = success
        self.data = data
        self.error = error


class NamadaProvider:
    def __init__(self, base_url: str, retries: int = 3, backoff_factor: float = 0.3,
                 status_forcelist: Optional[List[int]] = None, timeout: float = 30.0):
        self.base_url = base_url
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.status_forcelist = status_forcelist or [429, 500, 502, 503, 504]
        self.timeout = timeout
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def send_request(self, endpoint: str, http_method: str = "GET", **kwargs) -> Result:
        url = urljoin(self.base_url, endpoint)
        session = await self._get_session()
        for attempt in range(self.retries):
            try:
                async with session.request(http_method, url, **kwargs) as response:
                    response.raise_for_status()
                    json_data = await response.json()
                    return Result(True, json_data)
            except aiohttp.ClientResponseError as e:
                if attempt < self.retries - 1 and e.status in self.status_forcelist:
                    await asyncio.sleep(self.backoff_factor * (2 ** attempt))
                else:
                    return Result(False, error=f"HTTP error: {e.status} {e.message}")
            except aiohttp.ClientError as e:
                if attempt >= self.retries - 1:
                    return Result(False, error=f"Request exception: {str(e)}")

    async def send_json_rpc_request(self, rpc_method: str, params: Optional[dict] = None, **kwargs) -> Result:
        json_id = str(uuid.uuid4())
        data = {"jsonrpc": "2.0", "id": json_id, "method": rpc_method, "params": params or []}
        return await self.send_request("", http_method="POST", json=data, headers={"Content-Type": "application/json"},
                                       **kwargs)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _fetch_abci_query_value(self, params):
        result = await self.send_json_rpc_request("abci_query", params)
        if result.success:
            find_result, value = self._find_key(result.data, 'value')
            if not find_result:
                return Result(False, error="Value not found in the response.")
            if value:
                decoded_value = base64.b64decode(value)
                return Result(True, decoded_value)
            else:
                error_info = result.data.get('result', {}).get('response', {}).get('info', 'Unknown error')
                return Result(False, error=error_info)
        return result

    @staticmethod
    def _find_key(data: Union[Dict, List], target_key: str) -> Tuple[bool, Any]:
        if isinstance(data, dict):
            for key, value in data.items():
                if key == target_key:
                    return True, value
                elif isinstance(value, (dict, list)):
                    found, result = NamadaProvider._find_key(value, target_key)
                    if found:
                        return True, result
        elif isinstance(data, list):
            for item in data:
                found, result = NamadaProvider._find_key(item, target_key)
                if found:
                    return True, result
        return False, None

    async def get_latest_height(self) -> Result:
        result = await self.send_request('status')
        if result.success:
            resp = result.data
            if 'result' in resp:
                found, height = self._find_key(resp, 'latest_block_height')
                found, catching_up = self._find_key(resp, 'catching_up')
                if catching_up:
                    return Result(False, error="Node is still catching up.")
                if height is not None:
                    return Result(True, height)
                else:
                    return Result(False, error="Latest block height not found in response.")
            else:
                return Result(False, error="Unexpected response structure.")
        return Result(False, error="Failed to fetch blockchain status.")

    async def get_consensus_validators(self, height: int) -> Result:
        validators_info = []
        page = 1
        per_page = 100
        while True:
            endpoint = f'validators?height={height}&page={page}&per_page={per_page}'
            result = await self.send_request(endpoint, http_method="GET")
            if not result.success:
                return result
            data = result.data
            validators = data.get('result', {}).get('validators', [])
            if validators:
                validators_info.extend(
                    [(validator['address'], validator['voting_power']) for validator in validators])
                total_validators = int(data['result'].get('total', 0))
                if len(validators_info) >= total_validators:
                    break
                page += 1
            else:
                break
        return Result(True, validators_info)

    async def get_epoch(self) -> Result:
        params = {"path": f"/shell/epoch"}
        result = await self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, U64.parse(result.data))
        return result

    async def get_operator_address_from_tm(self, tm_address: str) -> Result:
        params = {"path": f"/vp/pos/validator_by_tm_addr/{tm_address}"}
        result = await self._fetch_abci_query_value(params)
        if result.success:
            address = address_parse(result.data[1:])
            return Result(True, address)
        return result

    async def get_validator_metadata(self, validator_address: str) -> Result:
        params = {"path": f"/vp/pos/validator/metadata/{validator_address}"}
        result = await self._fetch_abci_query_value(params)
        if result.success:
            data = ValidatorMetaData.parse(result.data[1:])
            metadata = {
                'email': data['email'],
                'description': data['description'],
                'website': data['website'],
                'discord_handle': data['discord_handle'],
                'avatar': data['avatar'],
            }
            return Result(True, metadata)
        return result

    async def get_validator_commission(self, validator_address: str) -> Result:
        params = {"path": f"/vp/pos/validator/commission/{validator_address}"}
        result = await self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, commission_pair_parse(result.data[1:]))
        return result

    async def get_validator_state(self, validator_address: str) -> Result:
        params = {"path": f"/vp/pos/validator/state/{validator_address}"}
        result = await self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, ValidatorState.parse(result.data[1:]).__class__.__name__)
        return result

    async def get_governance_parameters(self) -> Result:
        params = {"path": f"/vp/governance/parameters"}
        result = await self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, result.data)
        return result

    async def get_proposal_detail(self, proposal_id: int, epoch: int) -> Result:
        params = {"path": f"/vp/governance/proposal/{proposal_id}"}
        result = await self._fetch_abci_query_value(params)
        if result.success:
            value = result.data[1:]
            if value:
                return Result(True, proposal_parse(value, epoch))
            else:
                return Result(True, None)
        return result

    async def get_votes_info(self, proposal_id: int) -> Result:
        params = {"path": f"/vp/governance/proposal/{proposal_id}/votes"}
        result = await self._fetch_abci_query_value(params)
        if result.success:
            value = result.data
            if value:
                return Result(True, votes_parse(value))
            else:
                return Result(True, None)
        return result

    async def get_proposal_result(self, proposal_id: int) -> Result:
        params = {"path": f"/vp/governance/stored_proposal_result/{proposal_id}"}
        result = await self._fetch_abci_query_value(params)
        if result.success:
            value = result.data[1:]
            if value:
                return Result(True, proposal_result_parse(value))
            else:
                return Result(True, None)
        return result


# async def main():
#     provider = NamadaProvider("https://namada-testnet-rpc.blackoreo.xyz")
#     latest_height_result = await provider.get_latest_height()
#     if latest_height_result.success:
#         print("Latest height:", latest_height_result.data)
#     else:
#         print("Error fetching latest height:", latest_height_result.error)
#
#     resp = await provider.get_epoch()
#     epoch = resp.data
#     print(epoch)
#
#     resp = await provider.get_proposal_detail(371, epoch)
#     print(resp.data)
#     await provider.close()
#
#
# if __name__ == "__main__":
#     asyncio.run(main())
