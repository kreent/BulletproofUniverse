"""
china_analyzer.py - 🐉 Oracle Screener CHINA V2
Análisis fundamental para el mercado de China (HK, Mainland, ADRs).
Soporte para normalización de moneda (CNY, HKD) y riesgo país ajustado.
"""

import pandas as pd
import numpy as np
import yfinance as yf
import sys
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from portfolio_analyzer import CacheManager

# ==========================================
# ⚙️ CONFIG (CHINA SPECIFIC)
# ==========================================
DEFAULT_CHINA_CONFIG = {
    "MAX_WORKERS": 10,
    "MIN_ROIC": 0.08,
    "MIN_PIOTROSKI": 5,
    "MIN_PIO_COVERAGE": 6,
    "DISCOUNT_RATE_BASE": 0.11,
    "MARGIN_OF_SAFETY_VIEW": -0.20,
    "MIN_MCAP_USD": 3_000_000_000,
}

TERMINAL_G_BY_SECTOR = {
    "Communication Services": 0.030,
    "Consumer Cyclical": 0.030,
    "Technology": 0.030,
    "Healthcare": 0.030,
    "Consumer Defensive": 0.025,
    "Utilities": 0.020,
    "Energy": 0.020,
    "Financial Services": 0.020,
    "Real Estate": 0.015,
    "Basic Materials": 0.020,
    "Industrials": 0.025,
    "N/A": 0.020
}

def get_fuzzy_series(df, keywords):
    if df is None or df.empty: return pd.Series(dtype=float)
    df = df.copy()
    df.index = df.index.astype(str).str.lower().str.strip()
    for key in keywords:
        k = key.lower()
        if k in df.index: return df.loc[k]
        matches = [i for i in df.index if k in i]
        if matches: return df.loc[min(matches, key=len)]
    return pd.Series(dtype=float)

def safe_float(x):
    try:
        if x is None: return np.nan
        if isinstance(x, (np.floating, float)) and np.isnan(x): return np.nan
        return float(x)
    except: return np.nan

def get_latest_and_prev(series: pd.Series):
    if series is None or series.empty: return (np.nan, np.nan)
    return safe_float(series.iloc[0]), (safe_float(series.iloc[1]) if len(series) > 1 else np.nan)

class ChinaAnalyzer:
    def __init__(self, config=None, cache_manager=None):
        self.config = {**DEFAULT_CHINA_CONFIG, **(config or {})}
        self.cache_manager = cache_manager or CacheManager(cache_file_name="china_screener_results.json")
        self._fx_cache = {}

    def log(self, msg):
        print(msg)
        sys.stdout.flush()

    def get_fx_to_usd(self, ccy):
        if not ccy or ccy == "USD": return 1.0
        ccy = ccy.strip().upper()
        inverse_pairs = ["CNY", "HKD", "JPY", "KRW"]
        is_inverse = False

        if ccy in inverse_pairs:
            ticker = f"USD{ccy}=X"
            is_inverse = True
        else:
            ticker = f"{ccy}USD=X"

        if ticker in self._fx_cache: return self._fx_cache[ticker]

        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if hist.empty: return np.nan
            px = hist["Close"].iloc[-1]
            val = (1.0/px) if is_inverse else px
            self._fx_cache[ticker] = val
            return val
        except: return np.nan

    def compute_piotroski_fscore(self, inc, bal, cf):
        score = 0; covered = 0
        ni = get_fuzzy_series(inc, ["Net Income", "NetIncome"])
        ocf = get_fuzzy_series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        assets = get_fuzzy_series(bal, ["Total Assets"])
        ltd = get_fuzzy_series(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation", "Total Debt"])
        ca = get_fuzzy_series(bal, ["Current Assets", "Total Current Assets"])
        cl = get_fuzzy_series(bal, ["Current Liabilities", "Total Current Liabilities"])
        rev = get_fuzzy_series(inc, ["Total Revenue", "Revenue"])
        gp = get_fuzzy_series(inc, ["Gross Profit"])
        shares = get_fuzzy_series(bal, ["Ordinary Shares Number", "Share Issued"])

        ni_t, ni_t1 = get_latest_and_prev(ni)
        ocf_t, ocf_t1 = get_latest_and_prev(ocf)
        assets_t, assets_t1 = get_latest_and_prev(assets)
        ltd_t, ltd_t1 = get_latest_and_prev(ltd)
        ca_t, ca_t1 = get_latest_and_prev(ca)
        cl_t, cl_t1 = get_latest_and_prev(cl)
        rev_t, rev_t1 = get_latest_and_prev(rev)
        gp_t, gp_t1 = get_latest_and_prev(gp)
        sh_t, sh_t1 = get_latest_and_prev(shares)

        def ratio(a, b): return a / b if (not np.isnan(a) and not np.isnan(b) and b != 0) else np.nan

        roa_t = ratio(ni_t, assets_t); roa_t1 = ratio(ni_t1, assets_t1)
        cr_t = ratio(ca_t, cl_t); cr_t1 = ratio(ca_t1, cl_t1)
        lev_t = ratio(ltd_t, assets_t); lev_t1 = ratio(ltd_t1, assets_t1)
        gm_t = ratio(gp_t, rev_t); gm_t1 = ratio(gp_t1, rev_t1)
        at_t = ratio(rev_t, assets_t); at_t1 = ratio(rev_t1, assets_t1)

        if not np.isnan(roa_t): covered += 1; score += 1 if roa_t > 0 else 0
        if not np.isnan(ocf_t): covered += 1; score += 1 if ocf_t > 0 else 0
        if not np.isnan(roa_t) and not np.isnan(roa_t1): covered += 1; score += 1 if roa_t > roa_t1 else 0
        if not np.isnan(ocf_t) and not np.isnan(ni_t): covered += 1; score += 1 if ocf_t > ni_t else 0
        if not np.isnan(lev_t) and not np.isnan(lev_t1): covered += 1; score += 1 if lev_t < lev_t1 else 0
        if not np.isnan(cr_t) and not np.isnan(cr_t1): covered += 1; score += 1 if cr_t > cr_t1 else 0
        if not np.isnan(sh_t) and not np.isnan(sh_t1): covered += 1; score += 1 if sh_t <= sh_t1 else 0
        if not np.isnan(gm_t) and not np.isnan(gm_t1): covered += 1; score += 1 if gm_t > gm_t1 else 0
        if not np.isnan(at_t) and not np.isnan(at_t1): covered += 1; score += 1 if at_t > at_t1 else 0

        return score, covered

    def analyze_stock(self, ticker):
        try:
            t = yf.Ticker(ticker)

            try:
                fast = t.fast_info
                ccy = fast.currency
                last_price = safe_float(fast.last_price)
                shares = safe_float(fast.shares)
            except:
                return None

            if np.isnan(last_price) or last_price <= 0 or np.isnan(shares): return None

            fx_to_usd = self.get_fx_to_usd(ccy)
            if np.isnan(fx_to_usd): return None

            mcap_local = last_price * shares
            mcap_usd = mcap_local * fx_to_usd

            if mcap_usd < self.config["MIN_MCAP_USD"]: return None

            inc = t.income_stmt
            bal = t.balance_sheet
            cf = t.cashflow
            if inc is None or bal is None or cf is None or inc.empty or bal.empty or cf.empty: return None

            inc = inc[sorted(inc.columns, reverse=True)]
            bal = bal[sorted(bal.columns, reverse=True)]
            cf = cf[sorted(cf.columns, reverse=True)]

            ni = get_fuzzy_series(inc, ["Net Income", "NetIncome"])
            ebit = get_fuzzy_series(inc, ["EBIT", "Operating Income"])
            if ebit.empty and not ni.empty: ebit = ni

            equity = get_fuzzy_series(bal, ["Stockholders Equity", "Total Equity"])
            debt = get_fuzzy_series(bal, ["Total Debt", "Long Term Debt"])
            cash = get_fuzzy_series(bal, ["Cash", "Cash And Cash Equivalents"])

            ocf = get_fuzzy_series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])
            capex = get_fuzzy_series(cf, ["Capital Expenditures", "Purchase of PPE"])

            if ebit.empty or equity.empty: return None

            curr_ebit = safe_float(ebit.iloc[0])
            curr_eq = safe_float(equity.iloc[0])
            curr_debt = safe_float(debt.iloc[0]) if not debt.empty else 0.0
            curr_cash = safe_float(cash.iloc[0]) if (not cash.empty and not pd.isna(cash.iloc[0])) else 0.0

            invested_cap = curr_eq + curr_debt - curr_cash
            tax_rate = 0.25
            nopat = curr_ebit * (1 - tax_rate)

            roic = nopat / invested_cap if invested_cap > 0 else 0.0
            if roic < self.config["MIN_ROIC"]: return None

            piotroski, pio_cov = self.compute_piotroski_fscore(inc, bal, cf)
            if pio_cov < self.config["MIN_PIO_COVERAGE"]: return None
            if piotroski < self.config["MIN_PIOTROSKI"]: return None

            info = t.info
            sector = info.get("sector", "N/A")

            ocf_val = safe_float(ocf.iloc[0]) if not ocf.empty else np.nan
            cpx_val = abs(safe_float(capex.iloc[0])) if not capex.empty else 0.0
            fcf = ocf_val - cpx_val if not np.isnan(ocf_val) else np.nan

            growth_proxy = min(roic * 0.5, 0.15)
            growth_proxy = max(growth_proxy, 0.03)

            term_g = TERMINAL_G_BY_SECTOR.get(sector, 0.02)

            r = self.config["DISCOUNT_RATE_BASE"]
            if sector in ["Technology", "Communication Services"]: r += 0.015
            if sector in ["Real Estate"]: r += 0.03

            intrinsic_local = 0.0
            mos = -0.99

            if (not np.isnan(fcf)) and fcf > 0:
                if r > term_g:
                    pv_stage1 = sum([(fcf * ((1 + growth_proxy) ** i)) / ((1 + r) ** i) for i in range(1, 6)])
                    term_val = (fcf * ((1 + growth_proxy) ** 5) * (1 + term_g)) / (r - term_g)
                    pv_term = term_val / ((1 + r) ** 5)

                    ev = pv_stage1 + pv_term
                    equity_val = ev + curr_cash - curr_debt
                    intrinsic_local = equity_val / shares

                    if intrinsic_local > 0:
                        mos = (intrinsic_local - last_price) / intrinsic_local

            if mos < self.config["MARGIN_OF_SAFETY_VIEW"]: return None

            return {
                "Ticker": ticker,
                "Sector": sector,
                "Price_Local": last_price,
                "Currency": ccy,
                "Intrinsic_Local": intrinsic_local,
                "MOS": mos,
                "ROIC": roic,
                "Piotroski": piotroski,
                "MarketCap_USD": mcap_usd,
                "Discount_Rate": r,
                "FCF_Yield": (fcf / mcap_local) if mcap_local > 0 else 0,
                "Debt_to_MCap": curr_debt / mcap_local if mcap_local > 0 else 0
            }
        except Exception:
            return None

    def get_china_universe(self):
        tickers = {
            # Tech & Internet
            "0700.HK", "BABA", "PDD", "JD", "BIDU", "3690.HK", "1810.HK", "NTES", "TCOM", "0992.HK", "9988.HK", "9618.HK", "0981.HK",
            # EV & Auto
            "1211.HK", "300750.SZ", "LI", "NIO", "XPEV", "002594.SZ", "2015.HK", "0175.HK",
            # Consumer & Financials
            "600519.SS", "000858.SZ", "YUMC", "2020.HK", "600036.SS", "601318.SS", "2318.HK", "1398.HK", "0939.HK", "3968.HK",
            # BioPharma
            "600276.SS", "2269.HK", "1093.HK", "1177.HK",
            # Energy & Materials
            "0883.HK", "0386.HK", "0857.HK", "601012.SS", "2899.HK", "3993.HK",
            # Telecom & Utilities
            "0941.HK", "0762.HK", "0006.HK", "0003.HK", "1038.HK",
            # HSI Additions
            "0001.HK", "0002.HK", "0005.HK", "0011.HK", "0012.HK", "0016.HK", "0017.HK", "0019.HK",
            "0027.HK", "0066.HK", "0101.HK", "0151.HK", "0175.HK", "0241.HK", "0267.HK", "0288.HK",
            "0358.HK", "0388.HK", "0669.HK", "0823.HK", "0868.HK", "0960.HK", "0968.HK", "0981.HK",
            "0992.HK", "1044.HK", "1088.HK", "1093.HK", "1109.HK", "1113.HK", "1177.HK", "1299.HK",
            "1398.HK", "1810.HK", "1928.HK", "1929.HK", "1997.HK", "2007.HK", "2018.HK", "2269.HK",
            "2313.HK", "2319.HK", "2331.HK", "2382.HK", "2388.HK", "2600.HK", "2628.HK", "2688.HK"
        }
        return list(tickers)

    def run_analysis(self, use_cache=True):
        if use_cache:
            res = self.cache_manager.get_cached_results()
            if res: return res

        tickers = self.get_china_universe()
        results = []
        with ThreadPoolExecutor(max_workers=self.config["MAX_WORKERS"]) as exe:
            futures = {exe.submit(self.analyze_stock, tk): tk for tk in tickers}
            for f in as_completed(futures):
                r = f.result()
                if r: results.append(r)
        
        results = sorted(results, key=lambda x: x["MOS"], reverse=True)
        final = {
            "total_analyzed": len(tickers), "candidates_count": len(results),
            "results": results, "version": "China Oracle Screener V2.0"
        }
        if use_cache: self.cache_manager.save_to_cache(final)
        return final

if __name__ == "__main__":
    az = ChinaAnalyzer()
    print(az.run_analysis())
