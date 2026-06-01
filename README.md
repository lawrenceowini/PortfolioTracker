# Portfolio Tracker & Dashboard Generator

A comprehensive Python-based portfolio management tool that generates automated Excel dashboards and PDF reports for tracking investment portfolios. The system supports multiple client portfolios with live NSE price updates, risk analysis, dividend tracking, and email notifications.

## Features

### Core Functionality

- **Live NSE Price Integration**: Automatically fetches current market prices for Kenyan stocks via web scraping
- **Multi-Portfolio Support**: Process multiple client portfolios in a single run
- **Excel Dashboard Generation**: Creates detailed Excel workbooks with:
  - Asset allocation visualization
  - Sector allocation analysis
  - Risk management monitoring
  - Transaction history
  - Dividend yield analysis
  - Performance history tracking
  - NSE price data with styling

### Reporting & Analysis

- **PDF Reports**: Generate professional PDF summaries including:
  - 6-month portfolio performance trend with line graph
  - Risk violations and concentration alerts
  - Customized styling matching existing files
- **Risk Management**:
  - Dynamic asset concentration rules (single-asset cap)
  - Sector weight limits (20% default)
  - Risk exclusions for cash and fixed income assets
  - Automated rebalancing suggestions
- **Performance Tracking**:
  - Monthly, quarterly, and yearly return calculations
  - Historical portfolio value snapshots
  - Dividend yield summaries

### Automation

- **Email Notifications**: Option to email reports to stakeholders for each portfolio
- **Automated Backups**: Creates timestamped backup of input files before processing
- **Error Handling**: Graceful degradation with informative warnings for missing dependencies

## Project Structure

```
PortfolioTracker/
├── update_portfolio.py          # Main script
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── clients/                     # Input folder (portfolio Excel files)
│   └── Portfolio_Tracker_Kenya.xlsx
├── reports/                     # Output folder (dashboards & PDFs)
│   ├── Portfolio_Tracker_Kenya_Dashboard_Output.xlsx
│   └── Portfolio_Tracker_Kenya_Report.pdf
└── backup_*.xlsx                # Automatic backups
```

## Installation

### Prerequisites

- Python 3.7 or higher
- pip (Python package manager)

### Setup

1. **Clone/Download the Repository**

   ```bash
   cd PortfolioTracker
   ```

2. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Verify Installation**
   ```bash
   python -m py_compile update_portfolio.py
   ```

## Usage

### Quick Start

1. **Place Portfolio Files**
   - Add your portfolio Excel file(s) to the `clients/` folder
   - Expected sheet: "Holdings" with columns: Asset, Sector, Shares, Buy Price, Current Price

2. **Run the Script**

   ```bash
   python update_portfolio.py
   ```

3. **Follow Prompts**
   - The script will process each portfolio
   - When prompted, enter an email address to receive the PDF report (or press Enter to skip)
   - Reports are generated in the `reports/` folder

### Input File Format

Your portfolio Excel file should contain:

- **Holdings sheet**: Core portfolio data
  - Asset (stock name)
  - Sector (Banking, Energy, etc.)
  - Shares (quantity)
  - Buy Price (KES)
  - Current Price (formula-based or manual)

- **Dividend Tracking sheet** (optional): Dividend data
  - Asset, Dividend per Share, Shares, Total Dividend

### Output Files

**Excel Dashboard** (`Portfolio_Tracker_Kenya_Dashboard_Output.xlsx`):

- Dashboard1: Summary, asset allocation, sector allocation, risk analysis
- Holdings: Full holdings table with latest prices
- NSE_Prices: Live market data
- Transactions: Transaction history
- Performance History: Monthly/quarterly/yearly returns
- Dividends: Dividend yield analysis (if data provided)
- Portfolio_State: Current portfolio state (hidden)

**PDF Report** (`Portfolio_Tracker_Kenya_Report.pdf`):

- 6-month performance trend with line graph
- Risk violation summary (asset & sector concentrations)
- Current portfolio value snapshot

## Configuration

### Styling Constants (in `update_portfolio.py`)

- `SECTOR_WEIGHT_LIMIT`: Maximum allowed sector allocation (default: 20%)
- `SINGLE_ASSET_WEIGHT_LIMIT`: Maximum allowed single asset allocation (default: 10%)
- `SECTOR_RISK_EXCLUSIONS`: Sectors excluded from concentration rules (Cash, Fixed Income)
- `MONTHS_TO_DISPLAY`: Months for performance history (default: 6)

### Email Configuration

The script supports SMTP email delivery of generated PDF reports using environment variables.
You can configure values directly in your shell or by placing a `.env` file in the repository root.

Supported variables:

- `EMAIL_SMTP_SERVER` (default: `smtp.gmail.com`)
- `EMAIL_SMTP_PORT` (default: `587`)
- `EMAIL_SMTP_USERNAME`
- `EMAIL_SMTP_PASSWORD`
- `EMAIL_FROM` (defaults to `EMAIL_SMTP_USERNAME`)
- `EMAIL_USE_TLS` (default: `True`)
- `EMAIL_USE_SSL` (default: `False`)

Example `.env` file contents:

```dotenv
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=you@example.com
EMAIL_SMTP_PASSWORD=yourpassword
EMAIL_FROM=you@example.com
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
```

Then run:

```bash
python update_portfolio.py
```

### Color Scheme

The tool uses a cohesive color palette:

- Dark Olive: `#3B4436`
- Cream: `#F1E9CB`
- Text Dark: `#2F332E`
- Warm Beige: `#E6DFD3`

## Supported Features

### Stock Tickers

The system includes mappings for Kenyan NSE stocks:

- Co-op Bank (COOP)
- Equity Bank (EQTY)
- KCB Bank (KCB)
- NCBA (NCBA)
- Safaricom (SCOM)
- Jubilee Insurance (JUB)
- CIC Insurance (CIC)
- Britam Holdings (BRIT)
- KenGen (KEGN)
- Kenya Power (KPLC)
- Total Energies (TOTL)

Plus support for ETFs and manual price entry for non-NSE assets.

## Troubleshooting

### Missing reportlab Error

If you see "Warning: reportlab not installed":

```bash
pip install reportlab
```

### Email Sending Issues

The script now supports SMTP email delivery for PDF reports. If the email fails, verify that your SMTP settings are configured correctly in environment variables.

Common checks:

- `EMAIL_SMTP_SERVER` and `EMAIL_SMTP_PORT` are correct for your provider
- `EMAIL_SMTP_USERNAME` and `EMAIL_SMTP_PASSWORD` are set
- `EMAIL_FROM` is a valid sender address
- Use an app password if your email provider requires it (for Gmail/Outlook)

### NSE Price Fetch Failures

- Some stocks may not have live prices available (marked as "NSE live market data unavailable")
- Manually enter prices in the Excel file or use the Current Price column

## Performance Notes

- First run: ~5-10 seconds per portfolio (includes NSE price fetching)
- Subsequent runs: ~2-5 seconds (faster with cached prices)
- PDF generation: ~2-3 seconds per portfolio
- Multiple portfolios are processed sequentially

## Future Enhancements

- Email automation with SMTP configuration
- Multi-threading for faster multi-portfolio processing
- Historical price tracking and trend analysis
- Custom rebalancing recommendations
- Mobile app integration
- API endpoints for real-time data

## License

Internal use only

## Support

For issues or questions, review the script output and check the generated Excel files for data validation.

---

**Version**: 1.0  
**Last Updated**: June 2026  
**Author**: Portfolio Management System
