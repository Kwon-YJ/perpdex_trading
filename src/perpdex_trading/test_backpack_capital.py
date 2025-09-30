import base64
import hashlib
import hmac
import json
import time
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
import os
from dotenv import load_dotenv
load_dotenv()

# Replace with your actual API Key and Secret
API_KEY = os.getenv("BACKPACK_PUBLIC_KEY")
API_SECRET = os.getenv("BACKPACK_PRIVATE_KEY")

BASE_URL = "https://api.backpack.exchange"

def get_backpack_signature(instruction, private_key_bytes, api_key_b64, timestamp, window=5000):
    # Construct the signing string
    # For GET /api/v1/capital, there are no query parameters or request body, so the signing string is simple.
    # The instruction type for Get balances is 'balanceQuery'
    signing_string = f"instruction={instruction}&timestamp={timestamp}&window={window}"

    # Sign the message
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    signature = private_key.sign(signing_string.encode('utf-8'))
    return base64.b64encode(signature).decode('utf-8')

def get_balances():
    # Derive private key bytes from base64 encoded API_SECRET
    private_key_bytes = base64.b64decode(API_SECRET)

    # Derive public key bytes from private key for X-API-Key header
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    api_key_b64 = base64.b64encode(public_key_bytes).decode('utf-8')

    timestamp = int(time.time() * 1000)
    instruction = "balanceQuery"
    window = 5000

    signature = get_backpack_signature(instruction, private_key_bytes, api_key_b64, timestamp, window)

    headers = {
        "X-API-Key": api_key_b64,
        "X-Signature": signature,
        "X-Timestamp": str(timestamp),
        "X-Window": str(window),
        "Content-Type": "application/json; charset=utf-8"
    }

    url = f"{BASE_URL}/api/v1/capital"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an exception for HTTP errors
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching balances: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status code: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        return None

if __name__ == "__main__":
    print("Fetching Backpack Exchange balances...")
    balances = get_balances()
    if balances:
        print("Balances:")
        print(json.dumps(balances, indent=4))
    else:
        print("Failed to retrieve balances.")
