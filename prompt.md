# 💡 Goal: Amplify Volume Without Delta Risk

## Key Operations
1. Randomly select **half of the exchanges** from the exchange list, then for each selected exchange randomly choose **3–5 assets** and build a market **long basket**.
2. For the **other half of the exchanges**, build a market **short basket** using **different assets** that have a **very high correlation** with the long basket. Construct the long/short baskets **based on delta (not notional value)** so that the **theoretical portfolio delta nets to zero** between the long and short baskets.
3. **Wait 10 minutes.**
4. Close Condition 1: **If the total position’s net profit (excluding fees, slippage, and transaction costs) becomes ≥ $0.01 , immediately close all positions.**
5. Close Condition 2: **If either the long or short basket gets forcibly liquidated, immediately close all positions** and convert **all assets on all exchanges to cash**.
6. Write trading logs to `./cluade_zone/trading_result.txt`, and fetch current equity to **update the “current capital” column** in `./cluade_zone/exchange_guide.txt`.
7. **Wait 10 minutes** and then return to step 1.

- Fetch the list of exchanges from `./exchange_guide.txt`.
- The **per-exchange order implementation guide** is also in `./exchange_guide.txt`.
- Retrieve API keys for order signing from `./.env`.
- When using Python, run: `source /project/arbitrage_bot/.venv/bin/activate`.
- When adding Python packages, run: `source /project/arbitrage_bot/.venv/bin/activate; pip install {package_name}`.
- Allocate **80% of resources to code implementation** and **20% to testing**.
- Use the `./cluade_zone` folder as a working scratch space, and also store the **long-term plan** and **to-do list** there.
- **Do not print results**; instead, create a file named `{UTC_current_time}.txt` under `./cluade_zone` and write outputs there(korean).
- Before starting the work, **check the contents of the `claude_zone` folder once**.
- **Commit immediately after each file edit and push the changes.**
