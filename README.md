# AAdvantage Hotel Optimizer

This project, `aa_hotel_scrape`, contains a Python-based tool to help you find the best hotel deals on AAdvantageHotels.com and optimize for AAdvantage Loyalty Points (LP) earnings.

## 🌟 Key Features

*   **Discover Hotel Deals:** Scrapes `AAdvantageHotels.com` for hotel stays in a specified city and date range.
*   **Optimize for Loyalty Points:** Identifies a cost-effective itinerary of 1-night stays to help you reach a target AAdvantage LP goal (e.g., for AAdvantage Platinum Pro or Executive Platinum status).
*   **Points-per-Dollar Analysis:** Ranks hotels by their points-per-dollar value, helping you get the most out of your stays.
*   **Command-Line Interface:** Easy to use from your terminal.

## 🛠️ Setup

1.  **Clone the repository (if you haven't already):**
    ```bash
    git clone <repository_url>
    cd aa_hotel_scrape
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
    ```

3.  **Install dependencies:**
    The project uses `uv` for package management if `uv.lock` and `pyproject.toml` are configured for it. Otherwise, use `pip`.
    ```bash
    # If using uv
    uv pip install -r requirements.txt
    # Or, if using pip directly
    pip install -r requirements.txt
    ```
    (Ensure `requirements.txt` is up-to-date with `requests` and `tqdm`.)

4.  **Session Headers (Optional but Recommended):**
    For best results, especially to see personalized offers, you'll need to provide session headers (cookies, tokens) from an authenticated browser session on AAdvantageHotels.com.
    *   Open your browser's developer tools (usually F12).
    *   Go to the Network tab.
    *   Log in to AAdvantageHotels.com and perform a search.
    *   Find a request to the AAdvantageHotels API (e.g., a `searchRequest` or `places` call).
    *   Copy the relevant request headers (especially `cookie`, `authorization`, `x-csrf-token`, etc., if present) into a JSON file. For example, `headers_example.json` shows the structure. Save your actual headers in a file like `my_headers.json`.
    *   **Important:** Do not commit your actual headers file to Git if your repository is public. Add it to your `.gitignore` file.

## 🚀 How to Use

The main script is `aa_hotel_optimizer/main.py`.

**Command-Line Examples:**

```bash
# Get help on command-line arguments
python3 aa_hotel_optimizer/main.py --help

# Example: Find an optimal itinerary to reach 125,000 LP in Phoenix
# for stays between June 1, 2025, and June 30, 2025.
# This example assumes you have your session headers in 'my_headers.json'.
python3 aa_hotel_optimizer/main.py Phoenix --start-date 06/01/2025 --end-date 06/30/2025 --target-lp 125000 --headers-file my_headers.json

# Search without optimization, just list top deals for a shorter period
python3 aa_hotel_optimizer/main.py "Scottsdale" --start-date 07/10/2025 --end-date 07/12/2025 --headers-file my_headers.json
```

## 💻 Technical Stack

*   **Language:** Python 3
*   **Key Libraries:**
    *   `requests`: For making HTTP requests to the AAdvantageHotels API.
    *   `tqdm`: For displaying progress bars during searches.
    *   `argparse`: For parsing command-line arguments.

## ✨ Development Notes

This project was largely "vibe coded" with the assistance of an AI pair programmer! 🤖

---

Feel free to contribute or raise issues!
