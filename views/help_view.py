"""Help page: one scrollable, read-only text with colourful sections.

The whole guide is a single tk.Text widget. Tags give each section its own
coloured heading band, bold coloured key words, striped tables (tab stops) and
bulleted lists. One widget instead of ~470 labels and frames makes the page
open at once, and every section is always open (no expand/collapse).

To change the guide, edit SECTIONS below. Blocks:
    ("p", text)                  paragraph; **words** become bold, in the section colour
    ("sub", text)                small heading inside a section
    ("bullets", [text, ...])     bulleted list
    ("table", header, rows)      table; the LAST column may be long (it wraps)
    ("formula", text)            formula line on a tinted band
    ("note", text)               small italic remark
"""

import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from views.base_view import BaseView
from ui.ui_theme import ModernStyle
from views.tax_report_view import MenuPill
from model.applog import log

_KW = re.compile(r"(\*\*.+?\*\*)")

# ── The guide ────────────────────────────────────────────────────────────────
INTRO = (
    "**PTracker** keeps your trades and works out your holdings, profit and loss, XIRR and "
    "capital-gains tax, with live prices. Every section of this guide is always open: scroll "
    "down, use **Jump to a section** at the top right, or click a name below."
)

SECTIONS = [
    ("shortcuts", "⌨️  Keyboard shortcuts and handy tricks", "blue", [
        ("p", "Hold **Option** (the **Alt** key) and press a number to open one of the first "
              "nine pages in the sidebar:"),
        ("table", ["Keys", "Opens"], [
            ["Option + 1", "Dashboard"],
            ["Option + 2", "My Holdings"],
            ["Option + 3", "Trade Entry"],
            ["Option + 4", "Trade History"],
            ["Option + 5", "Tax Report"],
            ["Option + 6", "P&L Report"],
            ["Option + 7", "Watchlist"],
            ["Option + 8", "Valuation"],
            ["Option + 9", "Financial News"],
        ]),
        ("note", "Settings and Help have no shortcut: click them in the sidebar."),
        ("bullets", [
            "**Hide or quit**: the red close button (or **⌘W**) hides PTracker; click its Dock icon to bring "
            "it back. **⌘Q** or the **⏻** button in the sidebar quits.",
            "**What a column means**: rest the pointer on a column heading for a short explanation.",
            "**Pick a date**: click the 📅 button next to a date box. **Today** picks today; **✕ Close**, "
            "**Esc** or a click outside closes the calendar without changing the date.",
            "**Sort a table**: click a column heading; click it again to reverse the order.",
            "**Copy from a table**: right-click (or Control-click) a row and choose **Copy Selected "
            "Row** or **Copy All Rows**, then paste into Excel or Numbers.",
            "**Copy from this page**: drag over the text and press **⌘C**.",
        ]),
    ]),

    ("screens", "🧭  The screens", "purple", [
        ("table", ["Screen", "What it is for"], [
            ["**Dashboard**", "A summary of the whole portfolio: key numbers, best and worst performers, insights and "
                              "watchlist alerts. Double-click a card or a row for details; double-click a watchlist "
                              "alert to buy or sell. Grey alert rows are stocks you are watching, not alerts."],
            ["**My Holdings**", "What you own now, per broker. Double-click a row to see the trades behind it."],
            ["**Trade Entry**", "Add a trade by hand, or import many at once from a CSV file (see Bulk import)."],
            ["**Trade History**", "Search and filter every trade. Double-click a trade to edit it; select several to delete them together."],
            ["**Tax Report**", "Realised capital gains for a financial year (see Tax Report below)."],
            ["**P&L Report**", "Invested, current value, profit and loss and XIRR for each broker, with a chart and a PDF."],
            ["**Watchlist**", "Shares you are watching, with fundamental and technical numbers."],
            ["**Valuation**", "Fair value, buy price, target and signal for any symbol, from the shared rules."],
            ["**Financial News**", "Market news headlines."],
            ["**Settings**", "Brokers, appearance, backups, the data cache, and deleting data."],
        ]),
    ]),

    ("tax", "🧾  Tax Report", "green", [
        ("p", "The Tax Report lists the **capital gains you have realised** by selling shares, for one "
              "**financial year** (1 April to 31 March) or for **All Time**. Choose **All**, **INR** or "
              "**JPY** at the top right, and the year next to it."),
        ("sub", "The four cards"),
        ("bullets", [
            "**Short-term gains**: INR sales of shares held **12 months or less**.",
            "**Long-term gains**: INR sales of shares held **more than 12 months**.",
            "**Not split (JPY)**: Japanese sales. Japan taxes listed-share gains at **one flat rate** "
            "(20.315%), so they are not split into short and long term.",
            "**Net realised gains**: every row added up. This is **before** the ₹1.25 lakh long-term "
            "exemption and before losses are set off, so it is not the amount you pay tax on.",
        ]),
        ("sub", "The table"),
        ("p", "Each row is **one matched piece of a sale**. If one sale used shares from three different "
              "buys, you see three rows, each with its own buy date, days held and term. Gains are green "
              "with ▲, losses red with ▼."),
        ("sub", "How the matching works (FIFO: first in, first out)"),
        ("table", ["Step", "What happens"], [
            ["**1**", "Buys are queued oldest first, **separately for each broker, symbol and currency**. "
                      "A sale is never matched with shares bought at another broker."],
            ["**2**", "Each sale uses up the **oldest shares first**."],
            ["**3**", "Days held = sell date − buy date. For INR, **more than 12 months** is long-term."],
            ["**4**", "Gain = sale value − cost − its share of the buy fee − its share of the sell fee. Fees "
                      "are shared out by the number of shares, so **each fee is counted exactly once**, "
                      "even when one buy is sold in several parts."],
        ]),
        ("sub", "Indian tax rates for listed shares (sales from 23 July 2024)"),
        ("table", ["Type", "Held for", "Tax rate"], [
            ["**Short-term (STCG)**", "12 months or less", "**20%**"],
            ["**Long-term (LTCG)**", "more than 12 months", "**12.5%** on long-term gains above **₹1.25 lakh** in a year"],
        ]),
        ("note", "Plus surcharge and 4% cess. These rates are for listed shares and equity mutual funds on "
                 "which STT is paid (Sections 111A and 112A). Sales before 23 July 2024 used the old rates: "
                 "15% short-term, and 10% long-term above ₹1 lakh."),
        ("sub", "Messages you may see"),
        ("bullets", [
            "**No buy found** (amber rows, listed first): a sale with no earlier buy at the same broker, or "
            "more shares sold than bought. It is **not counted** in the totals. Usually the buy was entered "
            "under another broker, or is missing.",
            "**Bad data** (amber rows): a trade whose date or numbers could not be read, for example a date "
            "written 15/01/2024. It is left out; correct it in **Trade History** (pick the date with 📅, or type it like 15 Jan 2024).",
            "**Red message**: the report could not be worked out at all. The cards then show — rather than "
            "an older year's figures.",
            "**All currencies**: JPY amounts are converted to ₹ at **today's exchange rate**, because past "
            "rates are not stored. Choose **INR** or **JPY** for exact figures in each currency.",
            "**JPY and the tax year**: Japan's tax year is January to December, but the year picker uses "
            "India's April to March year.",
        ]),
        ("sub", "Tax-harvesting ideas"),
        ("table", ["Situation", "Idea", "Why it helps"], [
            ["A holding is at a loss", "Sell before 31 March", "Short-term losses reduce short- or long-term gains; long-term losses reduce long-term gains only."],
            ["Exemption not used up", "Book long-term gains up to ₹1.25 lakh", "No tax on that part, and buying back raises your cost for later."],
            ["Shares almost 12 months old", "Wait until they pass 12 months", "12.5% long-term tax instead of 20% short-term."],
        ]),
        ("sub", "Please note"),
        ("bullets", [
            "This report is a **guide, not tax advice**. Check the figures with your CA before filing "
            "(Schedule CG of your income-tax return).",
            "Shares bought **before 1 February 2018**: the law lets you use the higher of your cost and the "
            "price on 31 January 2018 (grandfathering). PTracker uses your actual buy price.",
            "The ₹1.25 lakh exemption is for listed equity shares and equity mutual funds (Section 112A).",
            "My Holdings and the P&L Report work out realised P&L from your **average buy price**, without "
            "fees, so their realised figures can differ a little from this report.",
        ]),
    ]),

    ("pnl", "📊  P&L Report", "amber", [
        ("p", "The P&L Report shows, **for each broker**, how much you invested, what it is worth now, and "
              "your profit or loss. Choose **All**, **INR** or **JPY** at the top right."),
        ("bullets", [
            "**Cards**: Total Invested, Current Value, Overall P&L, Overall XIRR and Overall CAGR. With "
            "**All**, the cards are in ₹ and JPY amounts are converted at today's exchange rate (the line "
            "under the cards shows the rate).",
            "**Table**: one row per broker, grouped by currency, with a TOTAL row. **Unrealised** P&L is on "
            "shares you still hold; **Realised** P&L is on shares you have sold. The Loss columns add up "
            "only the holdings that are, or were sold, at a loss.",
            "**Chart**: invested (blue) against current value (**green** when above what you invested, "
            "**red** when below). Point at a bar to see its amount.",
            "**Save PDF**: saves a printable report with the summary, the chart and every broker's holdings. "
            "It is made in the background; the line under the cards says when it is saved.",
        ]),
    ]),

    ("import", "📥  Bulk import (CSV files)", "teal", [
        ("p", "On **Trade Entry** you can import a CSV file, for example one exported from your broker. "
              "Use these columns:"),
        ("table", ["Column", "Needed?", "Also accepted", "Notes"], [
            ["**date**", "Yes", "trade_date", "**YYYY-MM-DD** (2024-03-25) or **DD-MM-YYYY** (25-03-2024)"],
            ["**symbol**", "Yes", "–", "Ticker, for example RELIANCE.NS"],
            ["**type**", "Yes", "trade_type", "BUY or SELL (capitals or not)"],
            ["**qty**", "Yes", "quantity", "Number of shares, more than 0"],
            ["**price**", "Yes", "–", "₹, $ and commas are removed for you"],
            ["**trade_id**", "No", "–", "Stops the same row being imported twice"],
            ["**broker**", "No", "–", "If missing, the broker chosen on screen is used"],
        ]),
        ("bullets", [
            "**Rejected rows are listed with the reason** (for example a bad date or a missing price); "
            "all the other rows are imported.",
            "Headings such as 'Trade Date' or 'Quantity' are recognised automatically.",
            "A **backup** is saved before every import, so you can undo it with **Restore…** in Settings.",
        ]),
    ]),

    ("backups", "💾  Backups", "purple", [
        ("p", "Find these in **Settings → Data Backup & Export**."),
        ("bullets", [
            "**Automatic backup**: one copy every **5 days** when PTracker starts; the last **5** are kept.",
            "**Safety backup**: a copy is also saved **before every delete, wipe, import or restore**; the last **5** are kept.",
            "**Back Up Now**: makes a copy straight away. These are never deleted automatically.",
            "**Restore…**: go back to a backup. Your current data is saved first, so a restore can be "
            "undone too.",
            "**Show Backups**: opens the folder with the backup files in Finder.",
            "**Delete All Data** (Danger Zone): wipes trades, market data and holdings (brokers are kept). "
            "You must **type DELETE** to confirm, and a backup is saved first.",
        ]),
    ]),

    ("appearance", "🎨  Appearance", "blue", [
        ("p", "In **Settings → Appearance** choose:"),
        ("bullets", [
            "**Theme**: Light, Dark, or **Match macOS** (follows your Mac's light or dark setting).",
            "**Text size**: Small, Normal, Large or Extra large.",
            "Changes apply **after you restart** PTracker.",
        ]),
    ]),

    ("formulas", "🧮  Formulas and worked examples", "green", [
        ("sub", "Average buy price"),
        ("formula", "Average buy price = cost of the shares you still hold ÷ number of shares held"),
        ("note", "Fees are not included here; they are counted in XIRR and in the Tax Report."),
        ("sub", "Unrealised P&L (shares you still hold)"),
        ("formula", "Unrealised P&L = (current price − average buy price) × shares held"),
        ("table", ["Date", "Type", "Qty", "Price", "Current", "Unrealised P&L"], [
            ["2023-01-01", "BUY", "10", "₹100", "₹120", "**+₹200**"],
            ["2023-01-05", "BUY", "5", "₹110", "₹120", "**+₹50**"],
            ["Total", "–", "15", "₹103.33 average", "₹120", "**+₹250**"],
        ]),
        ("sub", "Realised P&L (shares you have sold)"),
        ("formula", "Realised P&L = (sell price − average buy price) × shares sold"),
        ("table", ["Date", "Action", "Qty", "Price", "Average cost", "Realised"], [
            ["2023-01-01", "BUY", "10", "₹100", "–", "–"],
            ["2023-02-01", "SELL", "5", "₹150", "₹100", "**+₹250**"],
            ["Left", "–", "5", "–", "₹100", "–"],
        ]),
        ("sub", "CAGR (compound annual growth rate)"),
        ("formula", "CAGR = (ending value ÷ starting value) ^ (1 ÷ years) − 1"),
        ("table", ["Year", "Invested", "Value", "Total return", "CAGR"], [
            ["Start", "₹10,000", "₹10,000", "–", "–"],
            ["Year 1", "₹10,000", "₹11,500", "15%", "**15.0%**"],
            ["Year 3", "₹10,000", "₹15,000", "50%", "**14.47%**"],
        ]),
        ("sub", "XIRR"),
        ("p", "Your **yearly return** worked out from the date and amount of every buy and sale (fees "
              "included) plus today's value, like a bank's annual interest rate. Money added later counts "
              "for less time, which CAGR cannot show."),
        ("sub", "Where each number is worked out"),
        ("table", ["Number", "Worked out per", "Why"], [
            ["Running quantity", "trade", "Changes with each trade"],
            ["Cost", "trade", "Builds up trade by trade"],
            ["Realised P&L", "trade", "Only happens on a SELL"],
            ["Fees", "trade", "Stored with each trade"],
            ["Cash flows", "trade", "Collected for XIRR"],
            ["Average price", "holding", "From the final totals"],
            ["Unrealised P&L", "holding", "Uses today's price"],
            ["Running P&L", "holding", "Realised plus unrealised"],
            ["XIRR / CAGR", "holding", "Uses the whole cash-flow history"],
        ]),
    ]),

    ("fees", "💸  Trade fees (Indian shares, NSE delivery)", "amber", [
        ("p", "Charges for a delivery trade on NSE, checked in April 2026. The sample columns are for a "
              "**₹1,00,000** trade."),
        ("table", ["Charge", "BUY", "SELL", "Rate"], [
            ["**Brokerage**", "₹1.00", "₹1.00", "Flat ₹1 per order (Zerodha charges ₹0 for delivery)"],
            ["**STT**", "₹100.00", "₹100.00", "0.1% of the trade value, on both sides"],
            ["**Exchange charge**", "₹2.97", "₹2.97", "₹2.97 per lakh (0.00297%, NSE cash market)"],
            ["**SEBI fee**", "₹0.10", "₹0.10", "₹10 per crore (0.0001%)"],
            ["**Stamp duty**", "₹15.00", "–", "0.015%, on BUY only"],
            ["**DP charge**", "–", "₹15.34", "₹13 + 18% GST, on SELL only"],
            ["**GST**", "₹0.73", "₹0.73", "18% of brokerage + exchange charge + SEBI fee"],
            ["**Total**", "**₹119.80**", "**₹120.14**", "IPFT (₹0.01 per crore) is too small to include"],
        ]),
        ("formula", "BUY total = brokerage + STT + exchange charge + SEBI fee + stamp duty + GST"),
        ("formula", "SELL total = brokerage + STT + exchange charge + SEBI fee + DP charge + GST"),
    ]),

    ("valuations", "⚖️  Valuations and action signals", "teal", [
        ("p", "Holdings, Watchlist, Valuation and the Dashboard all use **one set of rules** with the same "
              "company figures, so their signals agree. The rules are a formula, not advice. The assumptions "
              "behind them (required return, growth limits, margins) are in **Settings → Valuation Assumptions**, "
              "and every decision shows the ones it used."),
        ("sub", "Fair value"),
        ("p", "The **fair value** is the middle (median) of the methods that apply, shown with its low–high range:"),
        ("bullets", [
            "**Earnings model**: EPS grows for 5 years (the lowest of 3-year EPS growth, 3-year revenue growth + 2% "
            "and a cap: **15%** India, **8%** Japan), then slows to long-run growth (**5%** India, **1.5%** Japan) by "
            "year 10. Only the profit that needn't be reinvested counts (EPS × (1 − growth ÷ ROE)), discounted at the "
            "required return (**12%** India, **7.5%** Japan). EPS that swings a lot is averaged over 3 years.",
            "**Own P/E history**: the stock's median P/E at its last few year ends × EPS.",
            "**Banks and credit companies**: a fair price-to-book = (ROE − long-run growth) ÷ "
            "(required return − long-run growth), × book value per share.",
            "A **reverse check** shows what growth today's price assumes.",
        ]),
        ("table", ["Confidence", "When"], [
            ["**High**", "Two or more methods agree within 25%, and EPS was positive in each of the last 3 years"],
            ["**Medium**", "One method, or methods agree within 50%"],
            ["**Low**", "Methods disagree by more than 50%: no signal"],
        ]),
        ("sub", "Signals"),
        ("table", ["Signal", "When", "Holdings / Watchlist"], [
            ["**BUY**", "Price at or below the buy price: fair value less **25%** (High confidence) or **35%** "
                        "(Medium), and the quality check passes", "Accumulate / Accumulate or Strong Buy"],
            ["**HOLD**", "Between the buy price and the reduce level", "Hold / Wait / Watch"],
            ["**REDUCE**", "Price more than **20%** above fair value", "Reduce / Avoid"],
            ["**SELL**", "Bad news only: 12-month EPS at or below zero, fair value cut by more than 25% in the "
                         "last 30 days, or the quality check newly failed (90 days)", "Sell / Avoid"],
            ["**No signal**", "No figures yet, price older than 5 days, figures older than 120 days, "
                              "or Low confidence", "No signal / No Data"],
        ]),
        ("bullets", [
            "**Quality check** (pass/fail): ROE at least 12% (Japan 8%), EPS positive in each of the last 3 years, "
            "free cash flow positive, debt to equity below 1; at most one may fail. Banks and credit companies: "
            "ROE at least 12% (Japan 7%) and EPS positive for 3 years. A failed check means no BUY.",
            "**Target** = the fair value, over 2–3 years. **Upside %** = fair value ÷ price − 1; negative when "
            "the price is above the fair value. Holdings shows both as columns.",
            "**No flip-flopping**: next to the buy price or the reduce level, a signal changes only once the price "
            "is **3%** past it.",
            "The Watchlist's older **Quality scorecard** (P/E, ROE, margins, RSI…) is still shown in its pop-up, "
            "as information only.",
            "Yearly figures are fetched at most once a week per company; latest figures with every price refresh.",
        ]),
    ]),

    ("watchlist", "👁  Watchlist benchmarks", "green", [
        ("p", "The Watchlist shows fundamental and technical numbers for each symbol. These rules of thumb "
              "help you judge them."),
        ("sub", "Value"),
        ("table", ["Number", "Look for", "What it means"], [
            ["**P/E ratio**", "Compare with the industry", "Price ÷ earnings: cheap or expensive? A very low P/E can be a value trap."],
            ["**PEG ratio**", "Below 1 (best) or 2", "P/E ÷ growth: is the P/E justified by the company's growth?"],
            ["**EPS**", "Double digits (> 10)", "The profit for each share."],
            ["**Debt to equity**", "Below 1", "Borrowing ÷ shareholders' money: is the company over-borrowed?"],
            ["**Book value**", "Compare with the price", "Net assets per share: roughly what is left if the company closed."],
            ["**Fair value**", "Above the market price", "From the shared rules (see Valuations); blank for loss-making stocks."],
        ]),
        ("sub", "Profitability"),
        ("table", ["Number", "Look for", "What it means"], [
            ["**ROE**", "Double digits", "Return on equity: how well shareholders' money earns a profit."],
            ["**ROCE**", "Double digits", "Return on capital employed: profit on all the money used (equity + debt)."],
            ["**OPM**", "Above 10–15%", "Operating profit margin: what is left of sales after running costs."],
            ["**Free cash flow**", "Positive", "Cash left after all expenses and investment."],
            ["**Inventory days**", "Lower is better", "Days it takes to turn stock into sales."],
        ]),
        ("sub", "Growth, owners and price trend"),
        ("table", ["Number", "Look for", "What it means"], [
            ["**Sales growth**", "Double digits", "Revenue growth, year on year and quarter on quarter."],
            ["**Profit growth**", "Double digits", "Net profit growth; ideally at least as fast as sales."],
            ["**Promoter holding**", "High and steady", "The share of the company owned by its founders."],
            ["**Pledged shares**", "Zero", "Founders' shares given as security for loans."],
            ["**FII / DII holding**", "Rising or steady", "Ownership by foreign and Indian institutions (funds)."],
            ["**Order book**", "Large", "Orders still to be delivered: a guide to future sales."],
            ["**50 and 200 DMA**", "Price above them", "Moving averages: is the share in a long-term uptrend?"],
            ["**RSI**", "30 low / 70 high", "Relative strength: is the share oversold or overbought?"],
            ["**Volume**", "Rising", "Shows that a price move has real buying or selling behind it."],
        ]),
    ]),

    ("market", "📡  Prices and market data", "purple", [
        ("bullets", [
            "Prices come from **Yahoo Finance** (yfinance). Indian symbols end in **.NS** (NSE) or "
            "**.BO** (BSE); Japanese ones in **.T** (Tokyo), for example 7203.T.",
            "Prices refresh **in the background**, so the window stays responsive. The sidebar shows when "
            "they were last updated.",
            "PTracker is for your own records: check important figures against your broker's statements.",
        ]),
    ]),
]


def _palette() -> dict:
    """Section colour name -> (text colour, soft tint), from the active theme."""
    return {
        "blue": (ModernStyle.TEXT_ACCENT, ModernStyle.ACCENT_PRIMARY_PALE),
        "purple": (ModernStyle.TEXT_PURPLE, ModernStyle.ACCENT_PURPLE_PALE),
        "teal": (ModernStyle.INFO, ModernStyle.INFO_PALE),
        "green": (ModernStyle.SUCCESS, ModernStyle.SUCCESS_PALE),
        "amber": (ModernStyle.WARNING, ModernStyle.WARNING_PALE),
        "red": (ModernStyle.ERROR, ModernStyle.ERROR_PALE),
    }


def _plain(title: str) -> str:
    """Section title without its leading emoji (for menus and links)."""
    return title.split("  ", 1)[-1] if "  " in title else title


class HelpView(BaseView):
    """Help and documentation: one read-only, word-wrapped, scrollable text."""

    def build(self):
        self._titles = {_plain(title): sid for sid, title, _c, _b in SECTIONS}

        def _build_right(parent):
            MenuPill(parent, values=list(self._titles), text="Jump to a section",
                     command=lambda title: self.jump_to(self._titles[title])).pack(side="left")

        self.add_gradient_header(
            self,
            "❓ Help & Guide",
            "How PTracker works and what each screen shows.",
            right_widget_func=_build_right,
        )

        card = tk.Frame(self, bg=ModernStyle.BG_SECONDARY, highlightthickness=1,
                        highlightbackground=ModernStyle.BORDER_COLOR)
        card.pack(fill="both", expand=True, padx=20, pady=(10, 16))

        self.text = tk.Text(
            card, wrap="word", bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY,
            font=ModernStyle.FONT_BODY, relief="flat", borderwidth=0, highlightthickness=0,
            padx=26, pady=14, spacing2=3, cursor="arrow", insertwidth=0,
            selectbackground=ModernStyle.ACCENT_PRIMARY, selectforeground=ModernStyle.TEXT_ON_ACCENT,
            inactiveselectbackground=ModernStyle.ACCENT_PRIMARY_PALE,
        )
        vsb = ttk.Scrollbar(card, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        # Mouse-wheel and trackpad scrolling come with tk.Text itself.

        self._configure_tags()
        self._fill()
        self.text.configure(state="disabled")    # read-only (text can still be selected and copied)

    # ── styles ───────────────────────────────────────────────────────────────
    def _configure_tags(self):
        t = self.text
        self._font_body = tkfont.Font(font=ModernStyle.FONT_BODY)
        self._font_bold = tkfont.Font(font=ModernStyle.FONT_BODY_BOLD)

        # Base tags first: tags configured later win where they overlap.
        t.tag_configure("p", lmargin1=4, lmargin2=4, spacing3=10)
        t.tag_configure("intro", font=ModernStyle.FONT_BODY, lmargin1=4, lmargin2=4, spacing3=8)
        t.tag_configure("gap", font=ModernStyle.FONT_SMALL, spacing1=6)
        t.tag_configure("h", font=ModernStyle.FONT_SECTION_LABEL, lmargin1=14, lmargin2=14,
                        spacing1=7, spacing3=7)
        t.tag_configure("sub", font=ModernStyle.FONT_HEADING, lmargin1=4, lmargin2=4, spacing1=10, spacing3=5)
        bullet_x = self._font_body.measure("•") + 22
        t.tag_configure("bullet", lmargin1=12, lmargin2=12 + bullet_x, tabs=(12 + bullet_x,), spacing3=5)
        t.tag_configure("formula", font=ModernStyle.FONT_BODY_BOLD, foreground=ModernStyle.TEXT_PURPLE,
                        background=ModernStyle.BG_TERTIARY, lmargin1=16, lmargin2=16,
                        lmargincolor=ModernStyle.BG_TERTIARY, spacing1=5, spacing3=5)
        t.tag_configure("note", font=ModernStyle.FONT_ITALIC_MD, foreground=ModernStyle.TEXT_SECONDARY,
                        lmargin1=4, lmargin2=4, spacing1=4, spacing3=10)
        t.tag_configure("td", spacing1=4, spacing3=4)
        t.tag_configure("odd", background=ModernStyle.BG_TERTIARY, lmargincolor=ModernStyle.BG_TERTIARY)
        t.tag_configure("th", font=ModernStyle.FONT_TABLE_BOLD, foreground=ModernStyle.TABLE_HEADER_FG,
                        background=ModernStyle.TABLE_HEADER_BG, lmargincolor=ModernStyle.TABLE_HEADER_BG,
                        spacing1=5, spacing3=5)
        t.tag_configure("tbl_end", font=ModernStyle.FONT_SMALL, spacing3=4)

        # Section colours: heading band, plain colour, and bold key words
        for name, (fg, tint) in _palette().items():
            t.tag_configure(f"h_{name}", foreground=fg, background=tint, lmargincolor=tint)
            t.tag_configure(f"c_{name}", foreground=fg)
        for name, (fg, _tint) in _palette().items():
            t.tag_configure(f"kw_{name}", foreground=fg, font=ModernStyle.FONT_BODY_BOLD)
            t.tag_configure(f"link_{name}", foreground=fg, font=ModernStyle.FONT_BODY_BOLD, underline=True)

    # ── content ──────────────────────────────────────────────────────────────
    def _fill(self):
        t = self.text
        segs = []

        def add(s, *tags):
            segs.extend((s, tags))

        def rich(s, base, colour):
            for part in _KW.split(s):
                if part.startswith("**") and part.endswith("**") and len(part) > 4:
                    add(part[2:-2], *base, f"kw_{colour}")
                elif part:
                    add(part, *base)

        rich(INTRO + "\n", ("intro",), "blue")
        add("Contents:  ", "intro", "kw_blue")
        for i, (sid, title, colour, _blocks) in enumerate(SECTIONS):
            tag = f"goto_{sid}"
            add(_plain(title), "intro", f"link_{colour}", tag)
            if i < len(SECTIONS) - 1:
                add("   ·   ", "intro")
            t.tag_bind(tag, "<Button-1>", lambda _e, s=sid: self.jump_to(s))
            t.tag_bind(tag, "<Enter>", lambda _e: t.configure(cursor="hand2"))
            t.tag_bind(tag, "<Leave>", lambda _e: t.configure(cursor="arrow"))
        add("\n", "intro")
        t.insert("end", *segs)

        for sid, title, colour, blocks in SECTIONS:
            segs = []
            add("\n", "gap")
            t.insert("end", *segs)
            t.mark_set(f"sec_{sid}", "end-1c")
            t.mark_gravity(f"sec_{sid}", "left")
            segs = []
            add(title + "\n", "h", f"h_{colour}")
            for block in blocks:
                kind = block[0]
                if kind == "p":
                    rich(block[1] + "\n", ("p",), colour)
                elif kind == "sub":
                    add(block[1] + "\n", "sub", f"c_{colour}")
                elif kind == "note":
                    add(block[1] + "\n", "note")
                elif kind == "formula":
                    add(block[1] + "\n", "formula")
                elif kind == "bullets":
                    for item in block[1]:
                        add("•\t", "bullet", f"kw_{colour}")
                        rich(item + "\n", ("bullet",), colour)
                    add("\n", "tbl_end")
                elif kind == "table":
                    self._table(add, rich, block[1], block[2], colour)
            t.insert("end", *segs)

    def _table(self, add, rich, header, rows, colour):
        """Striped table using tab stops; the last column wraps under itself."""
        n = len(header)
        lm = 12
        tabs, x = [], lm
        for c in range(n - 1):
            cells = [_KW.sub(lambda m: m.group(0)[2:-2], str(r[c])) for r in rows]
            width = max([self._font_bold.measure(header[c])] + [self._font_bold.measure(s) for s in cells])
            x += width + 30
            tabs.append(x)
        tag = f"tbl_{id(rows)}"
        self.text.tag_configure(tag, tabs=tuple(tabs), lmargin1=lm, lmargin2=tabs[-1] if tabs else lm, rmargin=12)
        self.text.tag_lower(tag)     # colours and fonts of the other tags win
        add("\t".join(header) + "\n", tag, "th")
        for i, row in enumerate(rows):
            base = (tag, "td") + (("odd",) if i % 2 else ())
            for c, cell in enumerate(row):
                rich(str(cell) + ("\t" if c < n - 1 else "\n"), base, colour)
        add("\n", "tbl_end")

    # ── navigation ───────────────────────────────────────────────────────────
    def jump_to(self, section_id: str) -> None:
        """Scroll so the section's heading is at the top."""
        t = self.text
        try:
            y = t.count("1.0", f"sec_{section_id}", "update", "ypixels", return_ints=True) or 0
            total = t.count("1.0", "end", "ypixels", return_ints=True) or 1
            t.yview_moveto(max(0.0, (y - 4) / total))
        except tk.TclError:
            log.exception("Help: could not jump to %s", section_id)
            t.see(f"sec_{section_id}")
