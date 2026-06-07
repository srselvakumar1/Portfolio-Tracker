# PTracker - Portfolio Tracker

**PTracker** is a modern, professional desktop application built with Python and Tkinter, designed for investors who want to track their stock portfolio with precision, efficiency, and style.

![PTracker Screenshot](assets/app_screenshot.png)

## ✨ Key Features

### 📊 Intelligent Dashboard
**Real-Time Overview** - Get an instant snapshot of your total portfolio value, daily gains/losses, and overall performance at a glance.

**Visual Insights** - Beautifully designed donut charts break down your asset allocation by type (Stocks, Gold, Crypto, etc.) and individual securities, helping you understand where your money is invested.

### ✍️ Advanced Trade Entry
**Dual-Mode Entry** - Seamlessly switch between **Quantity Mode** (for regular shares) and **Lot Mode** (optimized for Futures and Options) with automatic multiplier calculation.

**Intelligent Price Feeds** - Enter the **Previous Close** and the app automatically calculates the current market price based on your configuration (e.g., `Current Price = Last Close + 0.50`).

**Trade Details** - Accurately track your trades with fields for Buy/Sell, Order Type (Market/Limit), and Execution Date.

### 📈 Transaction History
**Chronological Ledger** - View a comprehensive, sortable list of all your transactions.

**Edit & Delete** - Maintain data accuracy by easily editing or removing entries as needed.

**Smart Navigation** - Fast entry of new trades directly from the history view via a dedicated "+ Buy" or "+ Sell" button linked to the selected security.

### 💼 Holdings Management
**Unified Holdings View** - See all your current investments in one organized table.

**Real-Time Pricing** - Track the current value of your holdings based on live market data.

**Profits & Losses** - Monitor your gains and losses for each individual holding.

### 🛠️ System & Preferences
**User Profiles** - Save and switch between different user profiles to manage multiple portfolios (e.g., Personal, Family, Trading).

**Custom Settings** - Configure your default brokerage fees, trading hours, and pricing preferences to ensure accurate calculations.

**Currency Support** - Built-in support for USD, INR, and EUR.

## 🚀 Getting Started

### Prerequisites
*   **Python 3.8+**
*   **pip** (Python package installer)

### Installation
1.  **Clone the repository:**
    ```bash
    git clone https://github.com/srselvakumar1/Portfolio-Tracker.git
    cd Portfolio-Tracker
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

### Usage
Launch the application from your terminal:
```bash
python main.py
```

## 🎨 Tech Stack
*   **Language:** Python 3.x
*   **UI Framework:** Tkinter (Custom Modern Theme)
*   **Database:** SQLite (via `model/database.py`)
*   **Data Handling:** Pandas
*   **Icons:** Font Awesome via `customtkinter`

All three of those adjustments are done! If you interact with the app now, you'll see:

Refresh Time Visibility: I changed the background color of the refresh time label (and its surrounding container/button) to a deep teal (#0D9488) so it flawlessly blends into the right side of the new gradient header banner instead of looking out of place.

Instant Sync Status: The sidebar no longer hangs on "Syncing..." for 3 seconds. It now fetches the database status immediately upon opening the app (100ms), and I also added an invisible polling loop so it auto-updates every 30 seconds to stay fresh.

Faster KPI Rolling: I significantly sped up the KPI number animation. The count-up duration has been slashed by more than half (down to 400ms), resulting in a quick, snappy roll that feels premium without taking too long to settle.

Side Menu Values Not Loaded: When the sidebar was collapsed/expanded, the custom ModernButton widget was calling its redraw function to update the layout, but it was missing the command to explicitly update the canvas text item itself—so the text was left blank! I updated the button's internal _redraw method to correctly push the text updates to the canvas.

--------

I like these  4

#1 — Animated KPI counters: This is the single biggest "wow" moment. Seeing numbers roll up from zero is mesmerizing and gives the app a fintech-grade feel.
#2 — Gradient header banner: Transforms the dashboard from "business app" to "premium dashboard" in one change.
#3 — Pulsing live dot: A tiny detail that makes the app feel alive and real-time.
7	Color-coded P&L background tint on KPI cards	

token - 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