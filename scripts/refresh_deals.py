#!/usr/bin/env python3
"""
Daily Salesforce refresh for deal-data.json
Updates: pbr, stage, close date, created date for each deal.
Run via GitHub Actions or manually: python scripts/refresh_deals.py
"""

import json
import os
import sys
from datetime import datetime, timezone

try:
    import requests
    from simple_salesforce import Salesforce
except ImportError:
    print("ERROR: Run 'pip install simple-salesforce requests' first.")
    sys.exit(1)

# ── Auth via OAuth refresh token (works with Okta SSO) ───────────────────────
SF_REFRESH_TOKEN = os.environ['SF_REFRESH_TOKEN']
SF_CLIENT_ID     = os.environ['SF_CLIENT_ID']
SF_INSTANCE_URL  = os.environ['SF_INSTANCE_URL'].rstrip('/')

print("Getting Salesforce access token…")
res = requests.post(f"{SF_INSTANCE_URL}/services/oauth2/token", data={
    'grant_type':    'refresh_token',
    'client_id':     SF_CLIENT_ID,
    'refresh_token': SF_REFRESH_TOKEN,
})
if res.status_code != 200:
    print(f"ERROR: Token refresh failed ({res.status_code}): {res.text}")
    sys.exit(1)

access_token = res.json()['access_token']
sf = Salesforce(session_id=access_token, instance_url=SF_INSTANCE_URL)
print(f"Connected: {SF_INSTANCE_URL}")

# ── Load deal-data.json ───────────────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'deal-data.json')
with open(DATA_FILE) as f:
    data = json.load(f)

# ── Collect Opportunity IDs ───────────────────────────────────────────────────
sf_ids = []
id_to_deal = {}
for deal_id, deal in data['deals'].items():
    sf_info = deal.get('sf', {})
    opp_id = sf_info.get('id')
    if opp_id:
        sf_ids.append(opp_id)
        id_to_deal[opp_id] = deal_id

if not sf_ids:
    print("No Salesforce IDs found in deal-data.json — nothing to refresh.")
    sys.exit(0)

# ── Query Salesforce ──────────────────────────────────────────────────────────
ids_str = "', '".join(sf_ids)
soql = f"""
    SELECT Id, Name, StageName, CloseDate, Projected_Billed_Revenue__c, CreatedDate
    FROM Opportunity
    WHERE Id IN ('{ids_str}')
""".strip()

print(f"Querying {len(sf_ids)} opportunities…")
result = sf.query(soql)
records = result.get('records', [])
print(f"Got {len(records)} records.")

# Stage name passthrough — Shopify Salesforce stages match hub display names
STAGE_MAP = {
    'Pre-Qualified': 'Pre-Qualified',
    'Envision':      'Envision',
    'Solution':      'Solution',
    'Demonstrate':   'Demonstrate',
    'Closed Won':    'Closed Won',
    # Add any Salesforce-specific stage names that differ:
    # 'Proposal/Price Quote': 'Solution',
}

# ── Apply updates ─────────────────────────────────────────────────────────────
updated_count = 0
for rec in records:
    opp_id   = rec['Id']
    deal_id  = id_to_deal.get(opp_id)
    if not deal_id:
        continue

    sf_node = data['deals'][deal_id].setdefault('sf', {})
    sf_node['id'] = opp_id

    # PBR
    pbr = rec.get('Projected_Billed_Revenue__c')
    sf_node['pbr'] = int(pbr) if pbr is not None else 0

    # Stage
    stage_sf = rec.get('StageName', '')
    sf_node['stage'] = STAGE_MAP.get(stage_sf, stage_sf)

    # Close Date — Salesforce returns "YYYY-MM-DD"
    close = rec.get('CloseDate')
    if close:
        sf_node['close'] = close  # keep as ISO YYYY-MM-DD

    # Created Date — Salesforce returns ISO datetime, keep just the date
    created = rec.get('CreatedDate')
    if created:
        sf_node['created'] = created[:10]

    print(f"  {deal_id}: stage={sf_node['stage']}, close={sf_node.get('close')}, pbr={sf_node['pbr']}")
    updated_count += 1

# ── Update timestamp ──────────────────────────────────────────────────────────
data['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
data['version'] = 2

# ── Write back ────────────────────────────────────────────────────────────────
with open(DATA_FILE, 'w') as f:
    json.dump(data, f, indent=2)

print(f"\nDone. {updated_count} deals refreshed. Timestamp: {data['updated']}")
