import asyncio, os, lighter
async def main():
    l1 = "0x020978F1CcbD9E256D6c6daCfC637400Bd65BD0B"
    c = lighter.ApiClient()
    a = lighter.AccountApi(c)
    data = await a.accounts_by_l1_address(l1_address=l1)
    # 메인 계정
    print("MAIN ACCOUNT_INDEX:", data.sub_accounts[0].index)
    # 전체 나열
    for s in data.sub_accounts:
        print("index:", s.index, "addr:", s.l1_address, "name:", getattr(s, "name", None))
    await c.close()
asyncio.run(main())
