"""
uk_analyzer.py - 🏛️ UK Oracle Screener 
Análisis fundamental para el mercado de Reino Unido (LSE)
Soporte para GBp (pence), universos FTSE 100/250 y análisis histórico.
"""

import pandas as pd
import numpy as np
import yfinance as yf
import sys
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from portfolio_analyzer import CacheManager

def safe_float(x):
    """Convierte a float de forma segura"""
    try:
        if x is None: return np.nan
        if isinstance(x, (np.floating, float)) and np.isnan(x): return np.nan
        return float(x)
    except: return np.nan

def get_latest_and_prev(series: pd.Series):
    """Obtiene valor actual y anterior de una serie"""
    if series is None or series.empty: return (np.nan, np.nan)
    a = safe_float(series.iloc[0])
    b = safe_float(series.iloc[1]) if len(series) > 1 else np.nan
    return a, b

def get_fuzzy_series(df, keywords):
    """Búsqueda fuzzy de campos en DataFrames financieros"""
    if df is None or df.empty: return pd.Series(dtype=float)
    df = df.copy()
    df.index = df.index.astype(str).str.lower().str.strip()
    for key in keywords:
        k = key.lower()
        if k in df.index: return df.loc[k]
        matches = [i for i in df.index if k in i]
        if matches: return df.loc[min(matches, key=len)]
    return pd.Series(dtype=float)

def sector_bucket(sector: str) -> str:
    """Clasifica sector en bucket"""
    defensive = {"Consumer Defensive", "Utilities", "Healthcare"}
    cyclical = {"Consumer Cyclical", "Industrials", "Basic Materials", "Energy", "Real Estate"}
    growth = {"Technology", "Communication Services"}
    if sector in defensive: return "DEFENSIVE"
    if sector in cyclical: return "CYCLICAL"
    if sector in growth: return "GROWTH"
    return "OTHER"

def cap_growth_proxy_by_bucket(g: float, bucket: str) -> float:
    """
    Cap growth proxy by bucket to avoid implausible defensives in UK.
    """
    if np.isnan(g):
        return g
    if bucket == "DEFENSIVE":
        return min(g, 0.10)
    if bucket == "CYCLICAL":
        return min(g, 0.12)
    return g

# ==========================================
# ⚙️ CONFIG (UK calibrated)
# ==========================================
DEFAULT_UK_CONFIG = {
    "MAX_WORKERS": 12,
    "MIN_ROIC": 0.08,
    "MIN_PIOTROSKI": 6,
    "MIN_PIO_COVERAGE": 7,
    "DISCOUNT_RATE_BASE": 0.09,
    "MARGIN_OF_SAFETY_VIEW": -0.20,
    "AS_OF_DATE": "2025-02-01",  # Fixed date to match reference script
    "LOOKBACK_DAYS_PRICE": 12,
    "MIN_MCAP_USD": 5_000_000_000,  # 5B to match reference script
    "FX_LOOKBACK_DAYS": 20,
    "ALLOW_SHARES_LEAKAGE_FALLBACK": False,
    "NEG_MOS_REQUIRE_TVW_MAX": 0.80,
    "NEG_MOS_REQUIRE_FCFY_MIN": 0.045,
    "EXCLUDE_FINANCIALS": True,
    "EXCLUDE_REAL_ESTATE": False,
}

TERMINAL_G_BY_SECTOR = {
    "Communication Services": 0.015, "Utilities": 0.015, "Consumer Defensive": 0.020,
    "Real Estate": 0.020, "Energy": 0.020, "Basic Materials": 0.020,
    "Industrials": 0.020, "Technology": 0.025, "Healthcare": 0.022,
    "Consumer Cyclical": 0.022, "Financial Services": 0.020, "N/A": 0.020
}

_FX_CACHE = {}

class UKAnalyzer:
    def __init__(self, config=None, cache_manager=None):
        self.config = {**DEFAULT_UK_CONFIG, **(config or {})}
        self.cache_manager = cache_manager or CacheManager(cache_file_name="uk_screener_results.json")
        
    def log(self, msg):
        print(msg)
        sys.stdout.flush()

    # --- UK/As-Of Helpers ---
    def last_close_on_or_before(self, t: yf.Ticker, as_of: pd.Timestamp, lookback_days: int = 10):
        """Returns (close, date_used). Uses last business day <= as_of."""
        try:
            start = (as_of - pd.Timedelta(days=lookback_days)).date()
            end = (as_of + pd.Timedelta(days=1)).date()
            hist = t.history(start=str(start), end=str(end), auto_adjust=False)
            if hist is None or hist.empty or "Close" not in hist.columns:
                return (np.nan, None)
            hist = hist.dropna(subset=["Close"])
            if hist.empty:
                return (np.nan, None)
            
            # Normalize timezone
            idx = hist.index
            try:
                idx = idx.tz_localize(None)
            except Exception:
                pass
            
            hist = hist.copy()
            hist.index = idx
            hist = hist[hist.index <= as_of]
            if hist.empty:
                return (np.nan, None)
            
            close = safe_float(hist["Close"].iloc[-1])
            dt_used = hist.index[-1]
            return (close, dt_used)
        except Exception:
            return (np.nan, None)

    def filter_fs_asof(self, df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
        if df is None or df.empty: return df
        cols = []
        for c in df.columns:
            try: tc = pd.Timestamp(c)
            except: tc = pd.to_datetime(str(c), errors="coerce")
            if pd.notna(tc) and tc <= as_of: cols.append(c)
        if not cols: return df.iloc[:, 0:0]
        cols_sorted = sorted(cols, key=lambda x: pd.Timestamp(x), reverse=True)
        return df[cols_sorted]

    def get_shares_asof(self, inc: pd.DataFrame, bal: pd.DataFrame = None):
        """Try multiple sources for shares: income stmt -> balance sheet"""
        # Try income statement first (average shares)
        sh = get_fuzzy_series(inc, [
            "Basic Average Shares",
            "Diluted Average Shares",
            "Average Shares",
            "Weighted Average Shares"
        ])
        if not sh.empty:
            val = safe_float(sh.iloc[0])
            if not np.isnan(val) and val > 0:
                return (val, "income_stmt")
        
        # Fallback to balance sheet
        if bal is not None:
            sh_bal = get_fuzzy_series(bal, ["Ordinary Shares Number", "Share Issued"])
            if not sh_bal.empty:
                val = safe_float(sh_bal.iloc[0])
                if not np.isnan(val) and val > 0:
                    return (val, "balance_sheet")
        
        return (np.nan, "not_found")

    def get_fx_to_usd_asof(self, ccy: str, as_of: pd.Timestamp):
        if ccy == "USD": return (1.0, as_of)
        fx_ccy = "GBP" if ccy == "GBp" else ccy
        key = (fx_ccy, str(as_of.date()))
        if key in _FX_CACHE: return _FX_CACHE[key]
        try:
            fx = yf.Ticker(f"{fx_ccy}USD=X")
            fx_px, fx_dt = self.last_close_on_or_before(fx, as_of, lookback_days=self.config["FX_LOOKBACK_DAYS"])
            _FX_CACHE[key] = (fx_px, fx_dt)
            return (fx_px, fx_dt)
        except: return (np.nan, None)

    def normalize_uk_price(self, price: float, currency: str):
        if np.isnan(price) or price <= 0: return (price, currency, 1.0)
        if currency == "GBp": return (price / 100.0, "GBP", 0.01)
        return (price, currency, 1.0)

    def discount_rate_for_bucket(self, bucket: str) -> float:
        base = self.config["DISCOUNT_RATE_BASE"]
        if bucket == "DEFENSIVE": return max(0.075, base - 0.005)
        if bucket == "GROWTH": return min(0.11, base + 0.01)
        if bucket == "CYCLICAL": return min(0.11, base + 0.005)
        return base

    def get_uk_universe_ftse(self):
        tickers = []
        self.log("🇬🇧 Generando Universo UK: FTSE 100 + FTSE 250...")

        def extract_wiki_tickers(url: str):
            out = []
            parsers = ['lxml', 'html5lib', 'html.parser']
            
            for parser in parsers:
                try:
                    self.log(f"      Trying parser: {parser}")
                    tables = pd.read_html(url, flavor=parser)
                    for df in tables:
                        if "Ticker" in df.columns:
                            col = df["Ticker"].astype(str).str.strip()
                            col = col[col.notna() & (col != "nan") & (col != "")]
                            out = col.tolist()
                            self.log(f"      ✅ Success with {parser}: {len(out)} tickers")
                            return out
                    self.log(f"      No 'Ticker' column found with {parser}")
                except Exception as e:
                    self.log(f"      {parser} failed: {type(e).__name__}: {str(e)[:100]}")
                    continue
            
            self.log(f"   ❌ All parsers failed for {url}")
            return []

        try:
            ftse100 = extract_wiki_tickers("https://en.wikipedia.org/wiki/FTSE_100_Index")
            self.log(f"   -> FTSE 100 cargado ({len(ftse100)})")
        except Exception as e:
            ftse100 = []
            self.log(f"   ⚠️ Fallo FTSE 100: {type(e).__name__}: {str(e)[:200]}")

        try:
            ftse250 = extract_wiki_tickers("https://en.wikipedia.org/wiki/FTSE_250_Index")
            self.log(f"   -> FTSE 250 cargado ({len(ftse250)})")
        except Exception as e:
            ftse250 = []
            self.log(f"   ⚠️ Fallo FTSE 250: {type(e).__name__}: {str(e)[:200]}")

        raw = list(dict.fromkeys(ftse100 + ftse250))
        self.log(f"   📊 Total únicos extraídos: {len(raw)}")

        BACKUP_UK = [
            "AZN","SHEL","HSBA","ULVR","BP","BATS","GSK","RIO","GLEN","DGE",
            "REL","NG","LSEG","BARC","PRU","VOD","AAL","STAN","EXPN","III",
            "WTB","SMIN","ABDN","HLMA","IMB","SSE","CNA","LAND","BNZL","CPG"
        ]
        if len(raw) < 80:
            self.log("⚠️ Universo muy pequeño. Usando respaldo UK adicional.")
            raw = list(dict.fromkeys(raw + BACKUP_UK))

        tickers = []
        for t in raw:
            t = str(t).strip()
            if not t:
                continue
            t = t.rstrip(".")
            t = t.replace(".", "-")
            tickers.append(f"{t}.L")

        tickers = list(dict.fromkeys(tickers))
        return tickers[:700]

    def compute_piotroski_fscore(self, inc, bal, cf):
        score = 0; covered = 0
        ni = get_fuzzy_series(inc, ["Net Income", "NetIncome"])
        ocf = get_fuzzy_series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        assets = get_fuzzy_series(bal, ["Total Assets"])

        ltd = get_fuzzy_series(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"])
        if ltd.empty:
            ltd = get_fuzzy_series(bal, ["Total Debt"])

        ca = get_fuzzy_series(bal, ["Current Assets", "Total Current Assets"])
        cl = get_fuzzy_series(bal, ["Current Liabilities", "Total Current Liabilities"])
        rev = get_fuzzy_series(inc, ["Total Revenue", "Revenue"])
        gp = get_fuzzy_series(inc, ["Gross Profit"])
        sh = get_fuzzy_series(bal, ["Ordinary Shares Number", "Share Issued"])

        ni_t, ni_t1 = get_latest_and_prev(ni)
        ocf_t, ocf_t1 = get_latest_and_prev(ocf)
        as_t, as_t1 = get_latest_and_prev(assets)
        ltd_t, ltd_t1 = get_latest_and_prev(ltd)
        ca_t, ca_t1 = get_latest_and_prev(ca)
        cl_t, cl_t1 = get_latest_and_prev(cl)
        rv_t, rv_t1 = get_latest_and_prev(rev)
        gp_t, gp_t1 = get_latest_and_prev(gp)
        sh_t, sh_t1 = get_latest_and_prev(sh)

        def ratio(a, b): return a / b if (not np.isnan(a) and not np.isnan(b) and b != 0) else np.nan

        roa_t = ratio(ni_t, as_t); roa_t1 = ratio(ni_t1, as_t1)
        cr_t = ratio(ca_t, cl_t); cr_t1 = ratio(ca_t1, cl_t1)
        lv_t = ratio(ltd_t, as_t); lv_t1 = ratio(ltd_t1, as_t1)
        gm_t = ratio(gp_t, rv_t); gm_t1 = ratio(gp_t1, rv_t1)
        at_t = ratio(rv_t, as_t); at_t1 = ratio(at_t1 if 'at_t1' in locals() else np.nan, as_t1) # Fixed reference from Colab
        at_t1 = ratio(rv_t1, as_t1) # Corrected assignment

        # Recalculate based on Colab logic exactly
        if not np.isnan(roa_t):
            covered += 1
            score += 1 if roa_t > 0 else 0
        if not np.isnan(ocf_t):
            covered += 1
            score += 1 if ocf_t > 0 else 0
        if not np.isnan(roa_t) and not np.isnan(roa_t1):
            covered += 1
            score += 1 if roa_t > roa_t1 else 0
        if not np.isnan(ocf_t) and not np.isnan(ni_t):
            covered += 1
            score += 1 if ocf_t > ni_t else 0
        if not np.isnan(lv_t) and not np.isnan(lv_t1):
            covered += 1
            score += 1 if lv_t < lv_t1 else 0
        if not np.isnan(cr_t) and not np.isnan(cr_t1):
            covered += 1
            score += 1 if cr_t > cr_t1 else 0
        if not np.isnan(sh_t) and not np.isnan(sh_t1):
            covered += 1
            score += 1 if sh_t <= sh_t1 else 0
        if not np.isnan(gm_t) and not np.isnan(gm_t1):
            covered += 1
            score += 1 if gm_t > gm_t1 else 0
        if not np.isnan(at_t) and not np.isnan(at_t1):
            covered += 1
            score += 1 if at_t > at_t1 else 0
        
        return score, covered

    def analyze_stock(self, ticker, as_of_date):
        try:
            as_of = pd.Timestamp(as_of_date)
            t = yf.Ticker(ticker)
            
            # --- Price as-of with date tracking ---
            raw_px, px_dt = self.last_close_on_or_before(t, as_of, self.config["LOOKBACK_DAYS_PRICE"])
            if np.isnan(raw_px):
                return None

            # --- currency (for GBp fix) ---
            currency = None
            try:
                fi = t.fast_info
                currency = getattr(fi, "currency", None)
            except Exception:
                currency = None
            if not currency:
                try:
                    currency = t.info.get("currency", None)
                except Exception:
                    currency = None

            price, ccy_norm, _ = self.normalize_uk_price(raw_px, currency or "N/A")
            if np.isnan(price) or price <= 0:
                return None
            
            # --- Financials as-of ---
            inc = self.filter_fs_asof(t.income_stmt, as_of)
            bal = self.filter_fs_asof(t.balance_sheet, as_of)
            cf = self.filter_fs_asof(t.cashflow, as_of)
            
            if inc is None or bal is None or cf is None or inc.empty or bal.empty or cf.empty:
                return None

            # sector early (for exclusions + bucket + r)
            try:
                sector = t.info.get("sector", "N/A")
            except Exception:
                sector = "N/A"

            if self.config["EXCLUDE_FINANCIALS"] and sector == "Financial Services":
                return None
            if self.config["EXCLUDE_REAL_ESTATE"] and sector == "Real Estate":
                return None
            
            bucket = sector_bucket(sector)
            
            # --- shares as-of (avoid leakage) ---
            shares_val, shares_source = self.get_shares_asof(inc, bal)
            shares = shares_val
            
            if (np.isnan(shares) or shares <= 0) and self.config["ALLOW_SHARES_LEAKAGE_FALLBACK"]:
                try:
                    fast = t.fast_info
                    shares = safe_float(getattr(fast, "shares", np.nan))
                    shares_source = "fast_info(leakage)"
                except Exception:
                    shares = np.nan

            if np.isnan(shares) or shares <= 0:
                return None
            
            # --- Market cap and FX ---
            mcap_local = price * shares
            if np.isnan(mcap_local) or mcap_local <= 0:
                return None

            fx, fx_dt = self.get_fx_to_usd_asof(ccy_norm if ccy_norm != "N/A" else "GBP", as_of)
            mcap_usd = mcap_local * fx if not np.isnan(fx) else np.nan
            
            if np.isnan(mcap_usd) or mcap_usd < self.config["MIN_MCAP_USD"]:
                return None

            # --- fuzzy pulls ---
            ni_s = get_fuzzy_series(inc, ["Net Income", "NetIncome"])
            ebit_s = get_fuzzy_series(inc, ["EBIT", "Operating Income"])
            ocf_s = get_fuzzy_series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])
            capex_s = get_fuzzy_series(cf, [
                "Capital Expenditures",
                "Purchase of PPE",
                "Investments in Property Plant and Equipment"
            ])
            equity_s = get_fuzzy_series(bal, ["Stockholders Equity", "Total Equity"])
            debt_s = get_fuzzy_series(bal, [
                "Total Debt",
                "Long Term Debt",
                "Long Term Debt And Capital Lease Obligation",
                "Short Long Term Debt",
                "Short Term Debt"
            ])
            cash_s = get_fuzzy_series(bal, [
                "Cash",
                "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments"
            ])

            if ni_s.empty or ocf_s.empty or equity_s.empty:
                return None

            # --- as-of values ---
            c_ebit = safe_float(ebit_s.iloc[0]) if (not ebit_s.empty and not pd.isna(ebit_s.iloc[0])) else safe_float(ni_s.iloc[0])
            c_eq = safe_float(equity_s.iloc[0]) if not pd.isna(equity_s.iloc[0]) else 0.0
            c_debt = safe_float(debt_s.iloc[0]) if (not debt_s.empty and not pd.isna(debt_s.iloc[0])) else 0.0
            c_cash = safe_float(cash_s.iloc[0]) if (not cash_s.empty and not pd.isna(cash_s.iloc[0])) else 0.0
            
            inv_cap = c_eq + c_debt - c_cash
            roic = (c_ebit * 0.79) / inv_cap if inv_cap > 0 else 0.0
            
            if roic < self.config["MIN_ROIC"]:
                return None

            # --- Piotroski ---
            pio, pio_cov = self.compute_piotroski_fscore(inc, bal, cf)
            if pio_cov < self.config["MIN_PIO_COVERAGE"]:
                return None
            if pio < self.config["MIN_PIOTROSKI"]:
                return None

            # --- FCF ---
            ocf_val = safe_float(ocf_s.iloc[0]) if not pd.isna(ocf_s.iloc[0]) else np.nan
            cpx_val = abs(safe_float(capex_s.iloc[0])) if (not capex_s.empty and not pd.isna(capex_s.iloc[0])) else 0.0
            fcf = ocf_val - cpx_val if not np.isnan(ocf_val) else np.nan
            
            # --- DCF ---
            r = self.discount_rate_for_bucket(bucket)
            
            # Growth proxy with bucket-specific caps
            growth_proxy = min(roic * 0.5, 0.14)
            growth_proxy = max(growth_proxy, 0.03)
            growth_proxy = cap_growth_proxy_by_bucket(growth_proxy, bucket)
            
            term_g = TERMINAL_G_BY_SECTOR.get(sector, TERMINAL_G_BY_SECTOR["N/A"])
            intrinsic = 0.0
            mos = -0.99
            tvw = np.nan
            
            if (not np.isnan(fcf)) and fcf > 0:
                if r <= term_g:
                    return None

                pv1 = sum([(fcf * (1+growth_proxy)**i) / (1+r)**i for i in range(1, 6)])
                terminal_fcf = fcf * (1+growth_proxy)**5
                tv = (terminal_fcf * (1+term_g)) / (r - term_g)
                pv_tv = tv / (1+r)**5
                ev = pv1 + pv_tv
                intrinsic = (ev + c_cash - c_debt) / shares
                if intrinsic > 0:
                    mos = (intrinsic - price) / intrinsic
                    tvw = pv_tv / ev if ev > 0 else np.nan

            # --- Risk metrics ---
            debt_to_mcap = (c_debt / mcap_local) if mcap_local > 0 else np.nan
            fcf_yield = (fcf / mcap_local) if (mcap_local > 0 and not np.isnan(fcf)) else np.nan

            # --- MOS Negative Guardrails (avoid expensive bond-proxies) ---
            if mos < 0:
                if (not np.isnan(tvw)) and (tvw > self.config["NEG_MOS_REQUIRE_TVW_MAX"]):
                    return None
                if (np.isnan(fcf_yield)) or (fcf_yield < self.config["NEG_MOS_REQUIRE_FCFY_MIN"]):
                    return None

            # --- Final filter ---
            if mos < self.config["MARGIN_OF_SAFETY_VIEW"] and pio < 7:
                return None

            # --- Comprehensive output ---
            return {
                "Ticker": ticker,
                "AsOf": str(as_of.date()),
                "PxDateUsed": str(px_dt.date()) if px_dt is not None else None,
                
                "Currency": ccy_norm,
                "Price_Local": price,
                "Sector": sector,
                "Bucket": bucket,
                "Discount_Rate": r,
                
                "ROIC": roic,
                "Piotroski": pio,
                "Piotroski_Coverage": pio_cov,
                
                "Growth_Est": growth_proxy,
                "Terminal_g": term_g,
                
                "Intrinsic_Local": intrinsic,
                "MOS": mos,
                
                "FCF_Local": fcf,
                "OCF_Local": ocf_val,
                "Capex_Local": cpx_val,
                "Debt_Local": c_debt,
                "Cash_Local": c_cash,
                "Equity_Local": c_eq,
                "InvestedCap_Local": inv_cap,
                
                "Shares": shares,
                "Shares_Source": shares_source,
                
                "MarketCap_Local": mcap_local,
                "FX_to_USD": fx if not np.isnan(fx) else None,
                "FX_DateUsed": str(fx_dt.date()) if fx_dt is not None else None,
                "MarketCap_USD": mcap_usd,
                
                "Debt_to_MCap": debt_to_mcap if not np.isnan(debt_to_mcap) else None,
                "FCF_Yield": fcf_yield if not np.isnan(fcf_yield) else None,
                "DCF_TV_Weight": tvw if not np.isnan(tvw) else None
            }
        except Exception as e:
            return None

    def run_analysis(self, as_of_date=None, use_cache=True):
        as_of = as_of_date or self.config["AS_OF_DATE"]
        if use_cache:
            res = self.cache_manager.get_cached_results()
            if res and res.get("AsOf") == as_of: return res

        tickers = self.get_uk_universe_ftse()
        results = []
        with ThreadPoolExecutor(max_workers=self.config["MAX_WORKERS"]) as exe:
            futures = {exe.submit(self.analyze_stock, tk, as_of): tk for tk in tickers}
            for f in as_completed(futures):
                r = f.result()
                if r: results.append(r)
        
        results = sorted(results, key=lambda x: x["MOS"], reverse=True)
        final = {
            "total_analyzed": len(tickers), "candidates_count": len(results),
            "results": results, "AsOf": as_of, "version": "UK Oracle Screener V1.2 (Enhanced Output)"
        }
        if use_cache: self.cache_manager.save_to_cache(final)
        return final

if __name__ == "__main__":
    az = UKAnalyzer()
    print(az.run_analysis())
