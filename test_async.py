import asyncio
from namada_api.providers_async import NamadaProvider


async def main():
    provider = NamadaProvider("https://namada-testnet-rpc.blackoreo.xyz")
    latest_height_result = await provider.get_latest_height()
    if latest_height_result.success:
        print("Latest height:", latest_height_result.data)
    else:
        print("Error fetching latest height:", latest_height_result.error)

    resp = await provider.get_epoch()
    epoch = resp.data
    print(epoch)

    resp = await provider.get_proposal_detail(371, epoch)
    print(resp.data)
    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
