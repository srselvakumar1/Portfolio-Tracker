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
*   **Icons:** emoji, drawn by the system font

## 💾 Your data, backups and logs
*   **Database:** `~/Library/Application Support/PTracker/portfolio.db` (the installed app). The app never replaces an existing database.
*   **Backups:** an automatic backup is saved once a day (the last 30 are kept), and before every delete, wipe, import or restore, in the `Backups` folder next to the database. Settings → Data Backup & Export has **Back Up Now**, **Restore…** and **Show Backups**.
*   **Log:** problems are written to `~/Library/Logs/PTracker/ptracker.log` (Settings → About → Show Log).

## 🎨 Appearance
Settings → Appearance: **Light**, **Dark** or **Match macOS**, and **Normal / Large / Extra-large** text. Changes apply after a restart (the Restart Now button does it for you).

## 🧪 Tests
```bash
.venv/bin/python -m unittest discover -s tests -v
```

## 📦 Building the app
```bash
.venv/bin/pyinstaller --noconfirm PortfolioTrack.spec
pkgbuild --component ./dist/PTracker.app --install-location /Applications ./PTracker.pkg
```
The installer bundles an empty starter database only — never your own trades.
