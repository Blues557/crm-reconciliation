import requests
import json

BASE_URL = "https://analyst-assessment-production.up.railway.app"

response = requests.get(
    f"{BASE_URL}/api/openapi.json",
    timeout=20
)
response.raise_for_status()
spec = response.json()

for method, path in [
    ("post", "/api/v1/accounts"),
    ("patch", "/api/v1/accounts/{account_id}")
]:
    print("\n" + "=" * 60)
    print(method.upper(), path)
    print("=" * 60)

    operation = spec["paths"][path][method]

    print(json.dumps(operation, indent=2))

print("\n" + "=" * 60)
print("AVAILABLE COMPONENT SCHEMAS")
print("=" * 60)

schemas = spec.get("components", {}).get("schemas", {})
print(list(schemas.keys()))