"""
risk_metrics.py — Phase 2: Risk-Adjusted Return Metrics
========================================================
Computes professional risk metrics from portfolio value history:
  - Sharpe Ratio
  - Sortino Ratio
  - Annualised Volatility
  - Maximum Drawdown
  - Calmar Ratio
  - Value at Risk (VaR 95%)
  - Beta vs NSE 20 (if benchmark data available)

All functions take a pandas DataFrame of portfolio history and return
either a scalar or a structured DataFrame suitable for display.
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple

# Kenya 91-day T-bill rate used as risk-free rate (approximate annual %)
# Update this periodically — CBK publishes it at https://www.centralbank.go.ke
RISK_FREE_RATE_ANNUAL = 0.1550   # 15.50% as of mid-2025

TRADING_DAYS_PER_YEAR = 252
MONTHS_PER_YEAR       = 12


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_periodic_returns(history_df: pd.DataFrame, freq: str = "ME") -> pd.Series:
    """
    Convert a portfolio history DataFrame (Date, Portfolio Value)
    into a series of period-over-period percentage returns.

    freq: pandas resample frequency — 'ME' monthly, 'W' weekly, 'D' daily
    """
    df = history_df.copy()
    df["Date"]            = pd.to_datetime(df["Date"], errors="coerce")
    df["Portfolio Value"] = pd.to_numeric(df["Portfolio Value"], errors="coerce")
    df = df.dropna(subset=["Date", "Portfolio Value"])
    df = df.set_index("Date").sort_index()

    resampled = df["Portfolio Value"].resample(freq).last().dropna()
    returns   = resampled.pct_change().dropna()
    return returns


def _annualise_factor(freq: str) -> float:
    """Return the factor to annualise a per-period return/std."""
    factors = {"D": TRADING_DAYS_PER_YEAR, "W": 52, "ME": MONTHS_PER_YEAR, "M": MONTHS_PER_YEAR}
    return factors.get(freq, MONTHS_PER_YEAR)


# ── Core metrics ───────────────────────────────────────────────────────────────

def annualised_return(history_df: pd.DataFrame, freq: str = "ME") -> Optional[float]:
    """Annualised arithmetic mean return (%)."""
    rets = _to_periodic_returns(history_df, freq)
    if len(rets) < 2:
        return None
    factor = _annualise_factor(freq)
    return float(rets.mean() * factor * 100)


def annualised_volatility(history_df: pd.DataFrame, freq: str = "ME") -> Optional[float]:
    """Annualised standard deviation of returns (%)."""
    rets = _to_periodic_returns(history_df, freq)
    if len(rets) < 2:
        return None
    factor = _annualise_factor(freq)
    return float(rets.std() * np.sqrt(factor) * 100)


def sharpe_ratio(history_df: pd.DataFrame, freq: str = "ME") -> Optional[float]:
    """
    Sharpe Ratio = (annualised return - risk-free rate) / annualised volatility.
    Uses Kenya 91-day T-bill as risk-free rate.
    """
    ann_ret = annualised_return(history_df, freq)
    ann_vol = annualised_volatility(history_df, freq)
    if ann_ret is None or ann_vol is None or ann_vol == 0:
        return None
    return round((ann_ret / 100 - RISK_FREE_RATE_ANNUAL) / (ann_vol / 100), 4)


def sortino_ratio(history_df: pd.DataFrame, freq: str = "ME") -> Optional[float]:
    """
    Sortino Ratio = (annualised return - risk-free rate) / downside deviation.
    Only penalises downside volatility, unlike Sharpe which penalises all volatility.
    """
    rets = _to_periodic_returns(history_df, freq)
    if len(rets) < 2:
        return None
    factor      = _annualise_factor(freq)
    ann_ret     = float(rets.mean() * factor)
    rf_periodic = RISK_FREE_RATE_ANNUAL / factor
    downside    = rets[rets < rf_periodic]
    if len(downside) == 0:
        return None   # no negative periods — undefined (infinitely good)
    downside_std = float(downside.std() * np.sqrt(factor))
    if downside_std == 0:
        return None
    return round((ann_ret - RISK_FREE_RATE_ANNUAL) / downside_std, 4)


def maximum_drawdown(history_df: pd.DataFrame) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Maximum Drawdown = largest peak-to-trough decline in portfolio value.
    Returns (drawdown_pct, peak_date_str, trough_date_str).
    """
    df = history_df.copy()
    df["Date"]            = pd.to_datetime(df["Date"], errors="coerce")
    df["Portfolio Value"] = pd.to_numeric(df["Portfolio Value"], errors="coerce")
    df = df.dropna(subset=["Date", "Portfolio Value"]).sort_values("Date").reset_index(drop=True)

    if len(df) < 2:
        return None, None, None

    values     = df["Portfolio Value"].values
    dates      = df["Date"].dt.strftime("%Y-%m-%d").values
    peak_idx   = 0
    max_dd     = 0.0
    dd_peak    = dates[0]
    dd_trough  = dates[0]

    for i in range(1, len(values)):
        if values[i] > values[peak_idx]:
            peak_idx = i
        dd = (values[i] - values[peak_idx]) / values[peak_idx] * 100
        if dd < max_dd:
            max_dd    = dd
            dd_peak   = dates[peak_idx]
            dd_trough = dates[i]

    return round(max_dd, 2), dd_peak, dd_trough


def calmar_ratio(history_df: pd.DataFrame, freq: str = "ME") -> Optional[float]:
    """
    Calmar Ratio = annualised return / |max drawdown|.
    Higher is better. Measures return per unit of drawdown risk.
    """
    ann_ret     = annualised_return(history_df, freq)
    max_dd, _, _= maximum_drawdown(history_df)
    if ann_ret is None or max_dd is None or max_dd == 0:
        return None
    return round(ann_ret / abs(max_dd), 4)


def value_at_risk(history_df: pd.DataFrame, confidence: float = 0.95, freq: str = "ME") -> Optional[float]:
    """
    Historical VaR at given confidence level.
    e.g. VaR 95% = the loss not exceeded in 95% of periods.
    Returns the loss as a positive % number (so 5.2 means "you could lose 5.2% in a bad period").
    """
    rets = _to_periodic_returns(history_df, freq)
    if len(rets) < 5:
        return None
    var = float(np.percentile(rets, (1 - confidence) * 100))
    return round(abs(var) * 100, 2)


def beta(
    portfolio_history: pd.DataFrame,
    benchmark_history: pd.DataFrame,
    freq: str = "ME",
) -> Optional[float]:
    """
    Beta = covariance(portfolio, benchmark) / variance(benchmark).
    Measures sensitivity to market movements.
    Beta > 1: more volatile than market. Beta < 1: less volatile.
    """
    p_rets = _to_periodic_returns(portfolio_history, freq)
    b_rets = _to_periodic_returns(benchmark_history, freq)

    # Align on common dates
    combined = pd.DataFrame({"p": p_rets, "b": b_rets}).dropna()
    if len(combined) < 3:
        return None

    cov = np.cov(combined["p"], combined["b"])
    var_b = cov[1, 1]
    if var_b == 0:
        return None
    return round(cov[0, 1] / var_b, 4)


def rolling_sharpe(history_df: pd.DataFrame, window: int = 6, freq: str = "ME") -> pd.DataFrame:
    """
    Rolling Sharpe Ratio over a sliding window of periods.
    Returns a DataFrame with Date and Rolling_Sharpe columns.
    """
    rets = _to_periodic_returns(history_df, freq)
    if len(rets) < window + 1:
        return pd.DataFrame(columns=["Date", "Rolling_Sharpe"])

    factor   = _annualise_factor(freq)
    rf_daily = RISK_FREE_RATE_ANNUAL / factor
    excess   = rets - rf_daily

    roll_mean = excess.rolling(window).mean()
    roll_std  = rets.rolling(window).std()

    sharpe_series = (roll_mean / roll_std * np.sqrt(factor)).dropna()
    result = sharpe_series.reset_index()
    result.columns = ["Date", "Rolling_Sharpe"]
    result["Rolling_Sharpe"] = result["Rolling_Sharpe"].round(4)
    return result


# ── Summary table ──────────────────────────────────────────────────────────────

def build_risk_metrics_table(
    history_df: pd.DataFrame,
    benchmark_history: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Build a clean summary DataFrame of all risk metrics for display.
    """
    if history_df.empty:
        return pd.DataFrame(columns=["Metric", "Value", "Interpretation"])

    ann_ret  = annualised_return(history_df)
    ann_vol  = annualised_volatility(history_df)
    sharpe   = sharpe_ratio(history_df)
    sortino  = sortino_ratio(history_df)
    max_dd, dd_peak, dd_trough = maximum_drawdown(history_df)
    calmar   = calmar_ratio(history_df)
    var95    = value_at_risk(history_df)
    beta_val = beta(history_df, benchmark_history) if benchmark_history is not None and not benchmark_history.empty else None

    def fmt(val, suffix="", decimals=2):
        if val is None:
            return "Insufficient data"
        return f"{val:.{decimals}f}{suffix}"

    def interpret_sharpe(s):
        if s is None: return "—"
        if s >= 2:    return "Excellent"
        if s >= 1:    return "Good"
        if s >= 0:    return "Acceptable"
        return "Poor (below risk-free rate)"

    def interpret_sortino(s):
        if s is None: return "—"
        if s >= 2:    return "Excellent downside protection"
        if s >= 1:    return "Good downside protection"
        if s >= 0:    return "Acceptable"
        return "Poor"

    def interpret_dd(d):
        if d is None: return "—"
        if d >= -5:   return "Minimal drawdown"
        if d >= -15:  return "Moderate drawdown"
        if d >= -30:  return "Significant drawdown"
        return "Severe drawdown"

    def interpret_beta(b):
        if b is None: return "—"
        if b > 1.2:   return "More volatile than market"
        if b > 0.8:   return "Moves in line with market"
        if b > 0:     return "Less volatile than market"
        return "Inverse to market"

    rows = [
        {
            "Metric"        : "Annualised Return",
            "Value"         : fmt(ann_ret, "%"),
            "Interpretation": "Total return if this pace held for a full year",
        },
        {
            "Metric"        : "Annualised Volatility",
            "Value"         : fmt(ann_vol, "%"),
            "Interpretation": "How much the portfolio value swings year-to-year",
        },
        {
            "Metric"        : f"Sharpe Ratio (rf={RISK_FREE_RATE_ANNUAL*100:.1f}%)",
            "Value"         : fmt(sharpe, "", 4),
            "Interpretation": interpret_sharpe(sharpe),
        },
        {
            "Metric"        : "Sortino Ratio",
            "Value"         : fmt(sortino, "", 4),
            "Interpretation": interpret_sortino(sortino),
        },
        {
            "Metric"        : "Maximum Drawdown",
            "Value"         : fmt(max_dd, "%") + (f"  ({dd_peak} → {dd_trough})" if dd_peak else ""),
            "Interpretation": interpret_dd(max_dd),
        },
        {
            "Metric"        : "Calmar Ratio",
            "Value"         : fmt(calmar, "", 4),
            "Interpretation": "Return per unit of drawdown risk (higher = better)",
        },
        {
            "Metric"        : "Value at Risk (95%)",
            "Value"         : fmt(var95, "% per period"),
            "Interpretation": "Expected maximum loss in 95% of periods",
        },
        {
            "Metric"        : "Beta vs NSE 20",
            "Value"         : fmt(beta_val, "", 4),
            "Interpretation": interpret_beta(beta_val),
        },
        {
            "Metric"        : "Risk-Free Rate Used",
            "Value"         : f"{RISK_FREE_RATE_ANNUAL*100:.2f}% p.a.",
            "Interpretation": "Kenya 91-day T-bill rate (CBK)",
        },
    ]
    return pd.DataFrame(rows)
