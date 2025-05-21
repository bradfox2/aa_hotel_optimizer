# Predefined lists of cities for broad geographic searches

MAJOR_US_METROS = [
    "New York City",
    "Los Angeles",
    "Chicago",
    "Houston",
    "Phoenix",
    "Philadelphia",
    "San Antonio",
    "San Diego",
    "Dallas",
    "San Jose",
    "Austin",
    "Jacksonville",
    "Fort Worth",
    "Columbus",
    "Charlotte",
    "San Francisco",
    "Indianapolis",
    "Seattle",
    "Denver",
    "Washington D.C.",
    "Boston",
    "Nashville",
    "Las Vegas",
    "Portland",
    "Atlanta",
    "Miami",
    # Add more or refine as needed
]

# In the future, other lists can be added here:
# EUROPEAN_CAPITALS = ["London", "Paris", "Berlin", "Madrid", "Rome"]
# ASIAN_HUBS = ["Tokyo", "Singapore", "Hong Kong", "Seoul", "Bangkok"]

PREDEFINED_CITY_LISTS = {
    "Major US Metros": MAJOR_US_METROS,
    # "European Capitals": EUROPEAN_CAPITALS,
    # "Asian Hubs": ASIAN_HUBS,
}

if __name__ == '__main__':
    # For basic testing or inspection of the lists
    print(f"Number of Major US Metros: {len(MAJOR_US_METROS)}")
    for city in MAJOR_US_METROS:
        print(city)
    
    print(f"\nAvailable predefined lists: {list(PREDEFINED_CITY_LISTS.keys())}")
