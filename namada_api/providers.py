import uuid
import base64
import requests
from typing import Any, Dict, Optional, Union, List, Tuple
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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
                 status_forcelist: Optional[List[int]] = None):
        self.base_url = base_url
        self._session = None
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.status_forcelist = status_forcelist or [429, 500, 502, 503, 504]

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._create_session(self.retries, self.backoff_factor, self.status_forcelist)
        return self._session

    def _create_session(self, retries: int, backoff_factor: float, status_forcelist: List[int]) -> requests.Session:
        retry_strategy = Retry(total=retries, read=retries, connect=retries,
                               backoff_factor=backoff_factor, status_forcelist=status_forcelist)
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def send_request(self, endpoint: str, http_method: str = "GET", **kwargs) -> Result:
        url = urljoin(self.base_url, endpoint)
        try:
            response = self.session.request(http_method, url, **kwargs)
            response.raise_for_status()
            return Result(True, response.json())
        except requests.exceptions.HTTPError as e:
            return Result(False, error=f"HTTP error: {e.response.status_code} {e.response.reason}")
        except requests.exceptions.RequestException as e:
            return Result(False, error=f"Request exception: {str(e)}")

    def send_json_rpc_request(self, rpc_method: str, params: Optional[dict] = None, **kwargs) -> Result:
        json_id = str(uuid.uuid4())
        data = {"jsonrpc": "2.0", "id": json_id, "method": rpc_method, "params": params or []}
        return self.send_request("", http_method="POST", json=data, headers={"Content-Type": "application/json"},
                                 **kwargs)

    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None

    def _fetch_abci_query_value(self, params):
        """Internal method to fetch and decode the value returned by an ABCI query."""
        result = self.send_json_rpc_request("abci_query", params)
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
        """Recursively search for a target key in a nested dictionary or list."""
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

    def get_latest_height(self) -> Result:
        result = self.send_request('status')
        if result.success:
            resp = result.data
            if 'result' in resp:
                found, height = NamadaProvider._find_key(resp, 'latest_block_height')
                found, catching_up = NamadaProvider._find_key(resp, 'catching_up')
                if catching_up:
                    return Result(False, error="Node is still catching up.")
                if height is not None:
                    return Result(True, height)
                else:
                    return Result(False, error="Latest block height not found in response.")
            else:
                return Result(False, error="Unexpected response structure.")
        return Result(False, error="Failed to fetch blockchain status.")

    def get_consensus_validators(self, height: int) -> Result:
        validators_info = []
        page = 1
        per_page = 100
        while True:
            endpoint = f'validators?height={height}&page={page}&per_page={per_page}'
            result = self.send_request(endpoint, http_method="GET")
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

    def get_epoch(self):
        params = {"path": f"/shell/epoch"}
        result = self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, U64.parse(result.data))
        return result

    def get_operator_address_from_tm(self, tm_address: str) -> Result:
        params = {"path": f"/vp/pos/validator_by_tm_addr/{tm_address}"}
        result = self._fetch_abci_query_value(params)
        if result.success:
            address = address_parse(result.data[1:])
            return Result(True, address)
        return result

    def get_validator_metadata(self, validator_address: str) -> Result:
        params = {"path": f"/vp/pos/validator/metadata/{validator_address}"}
        result = self._fetch_abci_query_value(params)
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

    def get_validator_commission(self, validator_address: str) -> Result:
        params = {"path": f"/vp/pos/validator/commission/{validator_address}"}
        result = self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, commission_pair_parse(result.data[1:]))
        return result

    def get_validator_state(self, validator_address: str) -> Result:
        params = {"path": f"/vp/pos/validator/state/{validator_address}"}
        result = self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, ValidatorState.parse(result.data[1:]).__class__.__name__)
        return result

    def get_proposal_detail(self, proposal_id: int, epoch: int) -> Result:
        params = {"path": f"/vp/governance/proposal/{proposal_id}"}
        result = self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, proposal_parse(result.data[1:], epoch))
        return result

    def get_votes_info(self, proposal_id: int) -> Result:
        params = {"path": f"/vp/governance/proposal/{proposal_id}/votes"}
        result = self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, votes_parse(result.data))
        return result

    def get_proposal_result(self, proposal_id: int) -> Result:
        params = {"path": f"/vp/governance/stored_proposal_result/{proposal_id}"}
        result = self._fetch_abci_query_value(params)
        if result.success:
            return Result(True, proposal_result_parse(result.data[1:]))
        return result


