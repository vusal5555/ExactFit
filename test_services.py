from agents.research_agent import research_icp

# # Test 1: Original
# result1 = research_icp("SaaS companies hiring SDRs")
# print(f"SaaS + SDRs: Found {result1['total_found']} companies")

# # Test 2: Different industry
# result2 = research_icp("Fintech startups that raised Series A in 2024")
# print(f"Fintech + Funding: Found {result2['total_found']} companies")

# Test 3: Tech stack based
result3 = research_icp("Marketing agencies using HubSpot")
print(f"Agencies + HubSpot: Found {result3['total_found']} companies")
print("Companies:", result3["companies"])
