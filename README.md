# AAdvantage Hotel Optimizer

This project, `aa_hotel_scrape`, provides tools to help you find the best hotel deals on AAdvantageHotels.com and optimize for AAdvantage Loyalty Points (LP) earnings. It includes both a command-line interface (CLI) and an interactive Streamlit web application.

## 🌟 Key Features

**Core Optimizer Engine (Usable via CLI & Streamlit):**

*   **Hotel Deal Discovery:** Scrapes `AAdvantageHotels.com` for hotel stays.
*   **Generalized Location Search:** Can search for hotels in **any city worldwide** by name.
*   **Loyalty Points Optimization:** Identifies cost-effective itineraries of 1-night stays to help reach a target LP goal.
*   **Dynamic Status Bonus Calculation:** Considers your current LP balance and applies AAdvantage status bonuses (20% at 60k LP, 30% at 100k LP) dynamically as an itinerary is built.
*   **AA Credit Card Bonus:** Option to include a 10 miles/$ bonus for stays booked with an AA credit card.
*   **Multiple Optimization Strategies:**
    *   Maximize Points per Dollar (Greedy PPD)
    *   Minimize Cost for Target LP (Greedy Cheapest Stays)
    *   Minimize Cost for Target LP (Dynamic Programming for a more optimal solution)
*   **Iterative Date Expansion:** Can extend search into future dates if the LP target isn't met in the initial window.

**Streamlit Web Application (Interactive UI):**

*   **User-Friendly Interface:** Easy way to access all optimizer features.
*   **Flexible Search Modes:**
    *   **Specific Location(s):** Search one or more user-specified cities.
    *   **Broad Points Optimization:** Search across predefined lists of cities (e.g., "Major US Metros") or enter a custom list of cities to find the best deals globally.
*   **Detailed Points Breakdown:** Results tables clearly show API points, card bonus points, and status bonus points for each stay.
*   **Enhanced Visualizations:**
    *   Distribution of Points per Dollar (Histogram).
    *   Scatter plot of Price vs. Points per Dollar (PPD) to easily identify high-value deals.
*   **Easy Authentication:**
    *   Parse session headers directly from a pasted cURL command.
    *   Manual input for Cookie/XSRF tokens.
    *   Upload session headers via a JSON file.
*   **Customizable Theme:** Features an AAdvantage-inspired color scheme for a familiar look and feel.
*   **Assumptions Page:** Provides transparency on the tool's operational assumptions and simplifications.

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
    (Ensure `requirements.txt` includes `requests`, `tqdm`, `streamlit`, and `pandas`.)

4.  **Session Headers (Optional but Recommended for Best Results):**
    To see personalized offers and ensure full access, provide session headers from an authenticated browser session on AAdvantageHotels.com.
    *   Open your browser's developer tools (usually F12). Go to the Network tab.
    *   Log in to AAdvantageHotels.com and perform a search.
    *   Find a request to the AAdvantageHotels API (e.g., a `searchRequest` or `places` call).
    *   **Easiest Method (Streamlit App):** Right-click the request, choose "Copy" -> "Copy as cURL" (syntax might vary by browser, e.g., "Copy as cURL (bash)" for Chrome). Paste this directly into the "cURL Command" input in the Streamlit app's sidebar.
    *   **Manual Method (CLI or Streamlit):** Copy headers like `cookie`, `x-xsrf-token` into a JSON file (see `headers_example.json` for structure, save yours as `my_headers.json`) or input manually in the Streamlit app.
    *   **Important:** Do not commit your actual headers file to Git if your repository is public. Add it to your `.gitignore` file.

## 🚀 How to Use

### Streamlit Web Application (Recommended for most users)

1.  **Activate your virtual environment.**
2.  **Run the Streamlit app:**
    ```bash
    streamlit run streamlit_app.py
    ```
3.  Open the URL provided by Streamlit (usually `http://localhost:8501`) in your web browser.
4.  Use the sidebar to:
    *   Choose **Search Type**: "Specific Location(s)" or "Broad Points Optimization".
    *   Enter city/cities or select regions.
    *   Set date range, target Loyalty Points, current LP balance, and AA card bonus.
    *   Select an optimization strategy.
    *   Provide authentication details (cURL paste is often easiest).
    *   Click "Search for Hotel Deals".

### Command-Line Interface (CLI)

The main script for CLI usage is `aa_hotel_optimizer/main.py`.

**Command-Line Examples:**

```bash
# Get help on command-line arguments
python3 aa_hotel_optimizer/main.py --help

# Example: Find an optimal itinerary to reach 125,000 LP in Phoenix
# for stays between June 1, 2025, and June 30, 2025, using 'my_headers.json'.
# Note: The CLI currently processes the first city provided if multiple are intended for the backend.
python3 aa_hotel_optimizer/main.py Phoenix --start-date 06/01/2025 --end-date 06/30/2025 --target-lp 125000 --headers-file my_headers.json --current-lp 10000 --aa-card-bonus

# Search without optimization, just list top deals for a shorter period in London
python3 aa_hotel_optimizer/main.py London --start-date 07/10/2025 --end-date 07/12/2025 --headers-file my_headers.json
```

## 💻 Technical Stack

*   **Language:** Python 3
*   **Web UI Framework:** Streamlit
*   **Data Handling:** Pandas
*   **Key Libraries (Backend & CLI):**
    *   `requests`: For making HTTP requests to the AAdvantageHotels API.
    *   `tqdm`: For displaying progress bars during CLI searches.
    *   `argparse`: For parsing command-line arguments.

## ✨ Development Notes

This project was largely "vibe coded" with the assistance of an AI pair programmer! 🤖

---

Feel free to contribute or raise issues!
