from namada_api.providers import NamadaProvider


if __name__ == "__main__":
    BASE_URL = "https://namada-testnet-rpc.blackoreo.xyz"
    provider = NamadaProvider(base_url=BASE_URL)

    result = provider.get_operator_address_from_tm('11BEA6434F204C2F7BE6CB7CF845C44C0FD3FBD2')
    print(result.data)

    result = provider.get_validator_metadata('tnam1qyvaqhs0vlfzlfhccxua89s8zmu7xq90xqsa9uua')
    print(result.data)

    result = provider.get_validator_commission('tnam1qyvaqhs0vlfzlfhccxua89s8zmu7xq90xqsa9uua')
    print(result.data)

    result = provider.get_validator_state('tnam1qyvaqhs0vlfzlfhccxua89s8zmu7xq90xqsa9uua')
    print(result.data)

    epoch = provider.get_epoch().data
    print(epoch)

    proposal_id = 368
    result = provider.get_proposal_detail(proposal_id, 42)
    print(result.data)

    result = provider.get_votes_info(300)
    print(result.data)
