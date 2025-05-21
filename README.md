# Hi there, I'm Brad! 👋

I'm a software developer interested in building useful tools and exploring data.

## 🏨 AAdvantage Hotel Optimizer

One of my current projects is the **AAdvantage Hotel Optimizer**. This Python-based tool helps you find the best hotel deals on AAdvantageHotels.com to maximize your AAdvantage Loyalty Points (LP) earnings.

**Key Features:**

*   **Discover Hotel Deals:** Scrapes AAdvantageHotels.com for hotel stays in a specified city and date range.
*   **Optimize for Loyalty Points:** Identifies a cost-effective itinerary of 1-night stays to help you reach a target AAdvantage LP goal (e.g., for AAdvantage Platinum Pro or Executive Platinum status).
*   **Points-per-Dollar Analysis:** Ranks hotels by their points-per-dollar value, helping you get the most out of your stays.
*   **Command-Line Interface:** Easy to use from your terminal.

**How to Use:**

The script `aa_hotel_optimizer/main.py` can be run from the command line.

```bash
# Example: Find an optimal itinerary to reach 125,000 LP in Phoenix
# (Assumes you have a headers.json file for authenticated requests)
python3 aa_hotel_optimizer/main.py Phoenix --start-date 06/01/2025 --end-date 06/30/2025 --target-lp 125000 --headers-file path/to/your/headers.json

# Get help on command-line arguments
python3 aa_hotel_optimizer/main.py --help
```

**Technical Stack:**

*   Python
*   Libraries: `requests`, `tqdm`, `argparse`

---

Feel free to explore my repositories and connect with me!

*(You can customize this further with your contact information, other projects, skills, and interests!)*
