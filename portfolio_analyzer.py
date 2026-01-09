"""
portfolio_analyzer.py - Oracle Screener V7.2 (EXACTO del Colab)
Código que FUNCIONA en Colab - sin modificaciones
"""

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm.auto import tqdm


# ==========================================
# FUNCIONES GLOBALES (del Colab)
# ==========================================
def get_fuzzy_series(df, keywords):
    if df is None or df.empty:
        return pd.Series(dtype=float)

    df = df.copy()
    df.index = df.index.astype(str).str.lower().str.strip()

    for key in keywords:
        k = key.lower()
        if k in df.index:
            return df.loc[k]
        matches = [i for i in df.index if k in i]
        if matches:
            return df.loc[min(matches, key=len)]

    return pd.Series(dtype=float)


def safe_float(x):
    try:
        if x is None:
            return np.nan
        if isinstance(x, (np.floating, float)) and np.isnan(x):
            return np.nan
        return float(x)
    except:
        return np.nan


def get_latest_and_prev(series: pd.Series):
    if series is None or series.empty:
        return (np.nan, np.nan)
    a = safe_float(series.iloc[0])
    b = safe_float(series.iloc[1]) if len(series) > 1 else np.nan
    return a, b


def compute_piotroski_fscore(inc, bal, cf):
    """
    Piotroski F-Score real (0-9).
    Retorna: (score, coverage) donde coverage = #señales evaluadas.
    """
    score = 0
    covered = 0

    # Series necesarias
    ni = get_fuzzy_series(inc, ["Net Income", "NetIncome"])
    ocf = get_fuzzy_series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])

    assets = get_fuzzy_series(bal, ["Total Assets"])
    # deuda ideal: long term, si no total
    ltd = get_fuzzy_series(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"])
    if ltd.empty:
        ltd = get_fuzzy_series(bal, ["Total Debt"])

    current_assets = get_fuzzy_series(bal, ["Current Assets", "Total Current Assets"])
    current_liab = get_fuzzy_series(bal, ["Current Liabilities", "Total Current Liabilities"])

    revenue = get_fuzzy_series(inc, ["Total Revenue", "Revenue"])
    gross_profit = get_fuzzy_series(inc, ["Gross Profit"])

    shares = get_fuzzy_series(bal, ["Ordinary Shares Number", "Share Issued"])

    # Valores t y t-1
    ni_t, ni_t1 = get_latest_and_prev(ni)
    ocf_t, ocf_t1 = get_latest_and_prev(ocf)
    assets_t, assets_t1 = get_latest_and_prev(assets)
    ltd_t, ltd_t1 = get_latest_and_prev(ltd)
    ca_t, ca_t1 = get_latest_and_prev(current_assets)
    cl_t, cl_t1 = get_latest_and_prev(current_liab)
    rev_t, rev_t1 = get_latest_and_prev(revenue)
    gp_t, gp_t1 = get_latest_and_prev(gross_profit)
    sh_t, sh_t1 = get_latest_and_prev(shares)

    def ratio(a, b):
        return a / b if (not np.isnan(a) and not np.isnan(b) and b != 0) else np.nan

    # Ratios
    roa_t = ratio(ni_t, assets_t)
    roa_t1 = ratio(ni_t1, assets_t1)

    cr_t = ratio(ca_t, cl_t)
    cr_t1 = ratio(ca_t1, cl_t1)

    lev_t = ratio(ltd_t, assets_t)
    lev_t1 = ratio(ltd_t1, assets_t1)

    gm_t = ratio(gp_t, rev_t)
    gm_t1 = ratio(gp_t1, rev_t1)

    at_t = ratio(rev_t, assets_t)
    at_t1 = ratio(rev_t1, assets_t1)

    # 1) ROA > 0
    if not np.isnan(roa_t):
        covered += 1
        score += 1 if roa_t > 0 else 0

    # 2) CFO > 0
    if not np.isnan(ocf_t):
        covered += 1
        score += 1 if ocf_t > 0 else 0

    # 3) ΔROA > 0
    if not np.isnan(roa_t) and not np.isnan(roa_t1):
        covered += 1
        score += 1 if roa_t > roa_t1 else 0

    # 4) Accrual: CFO > NI
    if not np.isnan(ocf_t) and not np.isnan(ni_t):
        covered += 1
        score += 1 if ocf_t > ni_t else 0

    # 5) ΔLeverage: lev baja
    if not np.isnan(lev_t) and not np.isnan(lev_t1):
        covered += 1
        score += 1 if lev_t < lev_t1 else 0

    # 6) ΔLiquidity: current ratio mejora
    if not np.isnan(cr_t) and not np.isnan(cr_t1):
        covered += 1
        score += 1 if cr_t > cr_t1 else 0

    # 7) No dilution: shares no suben
    if not np.isnan(sh_t) and not np.isnan(sh_t1):
        covered += 1
        score += 1 if sh_t <= sh_t1 else 0

    # 8) ΔGross margin: GM mejora
    if not np.isnan(gm_t) and not np.isnan(gm_t1):
        covered += 1
        score += 1 if gm_t > gm_t1 else 0

    # 9) ΔAsset turnover: AT mejora
    if not np.isnan(at_t) and not np.isnan(at_t1):
        covered += 1
        score += 1 if at_t > at_t1 else 0

    return score, covered


def analyze_stock_v72(ticker: str, CONFIG, TERMINAL_G_BY_SECTOR):
    """
    FUNCIÓN EXACTA DEL COLAB - Sin cambios
    """
    try:
        t = yf.Ticker(ticker)

        # Fast filter
        try:
            fast = t.fast_info
            market_cap = safe_float(getattr(fast, "market_cap", np.nan))
            if np.isnan(market_cap) or market_cap < 5_000_000_000:
                return None
            price = safe_float(getattr(fast, "last_price", np.nan))
            shares = safe_float(getattr(fast, "shares", np.nan))
            if np.isnan(price) or price <= 0 or np.isnan(shares) or shares <= 0:
                return None
        except:
            return None

        inc = t.income_stmt
        bal = t.balance_sheet
        cf  = t.cashflow
        if inc is None or bal is None or cf is None or inc.empty or bal.empty or cf.empty:
            return None

        # Orden cronológico (más reciente primero)
        inc = inc[sorted(inc.columns, reverse=True)]
        bal = bal[sorted(bal.columns, reverse=True)]
        cf  = cf[sorted(cf.columns, reverse=True)]

        # --- extracción fuzzy ---
        ni = get_fuzzy_series(inc, ["Net Income", "NetIncome"])
        ebit = get_fuzzy_series(inc, ["EBIT", "Operating Income"])
        ocf = get_fuzzy_series(cf,  ["Operating Cash Flow", "Total Cash From Operating Activities"])

        capex = get_fuzzy_series(cf, [
            "Capital Expenditures",
            "Purchase of PPE",
            "Investments in Property Plant and Equipment"
        ])

        equity = get_fuzzy_series(bal, ["Stockholders Equity", "Total Equity"])

        # Deuda robusta
        debt = get_fuzzy_series(bal, [
            "Total Debt",
            "Long Term Debt",
            "Long Term Debt And Capital Lease Obligation",
            "Short Long Term Debt",
            "Short Term Debt"
        ])

        # Cash robusto
        cash = get_fuzzy_series(bal, [
            "Cash",
            "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Short Term Investments"
        ])

        if ni.empty or ocf.empty or equity.empty:
            return None

        # --- valores actuales ---
        curr_ebit = safe_float(ebit.iloc[0]) if (not ebit.empty and not pd.isna(ebit.iloc[0])) else safe_float(ni.iloc[0])
        curr_eq   = safe_float(equity.iloc[0]) if not pd.isna(equity.iloc[0]) else 0.0
        curr_debt = safe_float(debt.iloc[0]) if (not debt.empty and not pd.isna(debt.iloc[0])) else 0.0
        curr_cash = safe_float(cash.iloc[0]) if (not cash.empty and not pd.isna(cash.iloc[0])) else 0.0

        invested_cap = curr_eq + curr_debt - curr_cash
        roic = (curr_ebit * 0.79) / invested_cap if invested_cap > 0 else 0.0
        if roic < CONFIG["MIN_ROIC"]:
            return None

        # ✅ Piotroski REAL (0-9) + coverage
        piotroski, pio_cov = compute_piotroski_fscore(inc, bal, cf)

        # Si coverage es bajo, no confiamos
        if pio_cov < CONFIG["MIN_PIO_COVERAGE"]:
            return None

        if piotroski < CONFIG["MIN_PIOTROSKI"]:
            return None

        sector = t.info.get("sector", "N/A")

        # --- FCF ---
        ocf_val = safe_float(ocf.iloc[0]) if not pd.isna(ocf.iloc[0]) else np.nan
        cpx_val = abs(safe_float(capex.iloc[0])) if (not capex.empty and not pd.isna(capex.iloc[0])) else 0.0
        fcf = ocf_val - cpx_val if not np.isnan(ocf_val) else np.nan

        # --- Growth proxy ---
        growth_proxy = min(roic * 0.5, 0.14)
        growth_proxy = max(growth_proxy, 0.03)

        # Terminal g por sector
        terminal_g = TERMINAL_G_BY_SECTOR.get(sector, TERMINAL_G_BY_SECTOR["N/A"])

        # --- DCF ---
        intrinsic = 0.0
        mos = -0.99
        tv_weight = np.nan

        if (not np.isnan(fcf)) and fcf > 0:
            r = CONFIG["DISCOUNT_RATE"]

            pv_stage1 = 0.0
            for i in range(1, 6):
                fcf_i = fcf * ((1 + growth_proxy) ** i)
                pv_stage1 += fcf_i / ((1 + r) ** i)

            if r <= terminal_g:
                return None

            terminal_fcf = fcf * ((1 + growth_proxy) ** 5)
            tv = (terminal_fcf * (1 + terminal_g)) / (r - terminal_g)
            pv_tv = tv / ((1 + r) ** 5)

            ev = pv_stage1 + pv_tv
            equity_val = ev + curr_cash - curr_debt
            intrinsic = equity_val / shares

            if intrinsic > 0:
                mos = (intrinsic - price) / intrinsic
                tv_weight = pv_tv / ev if ev > 0 else np.nan

        # filtro salida
        if mos < CONFIG["MARGIN_OF_SAFETY_VIEW"] and piotroski < 7:
            return None

        # Retornar en formato API (adaptado para endpoint)
        return {
            'Ticker': ticker,
            'Price': round(price, 2),
            'Sector': sector,
            'ROIC': round(roic, 4),
            'Piotroski': int(piotroski),
            'Growth_Est': round(growth_proxy, 4),
            'Intrinsic': round(intrinsic, 2),
            'MOS': round(mos, 4),
            'FCF': round(fcf, 2) if not np.isnan(fcf) else None,
            'OCF': round(ocf_val, 2) if not np.isnan(ocf_val) else None,
            'Debt': round(curr_debt, 2),
            'Cash': round(curr_cash, 2),
            'MarketCap': round(market_cap, 2),
            'Weight': round(tv_weight, 4) if not np.isnan(tv_weight) else None
        }

    except Exception:
        return None


# ==========================================
# WRAPPER CLASS PARA COMPATIBILIDAD CON API
# ==========================================
class WarrenScreener:
    """
    Wrapper que usa las funciones del Colab
    """
    
    def __init__(self, config=None):
        self.config = config or {
            'MAX_WORKERS': 12,
            'MIN_ROIC': 0.08,
            'MIN_PIOTROSKI': 6,
            'MIN_PIO_COVERAGE': 7,
            'DISCOUNT_RATE': 0.09,
            'MARGIN_OF_SAFETY_VIEW': -0.20
        }
        
        self.TERMINAL_G_BY_SECTOR = {
            "Communication Services": 0.015,
            "Utilities": 0.015,
            "Consumer Defensive": 0.020,
            "Real Estate": 0.020,
            "Energy": 0.020,
            "Basic Materials": 0.020,
            "Industrials": 0.020,
            "Technology": 0.025,
            "Healthcare": 0.022,
            "Consumer Cyclical": 0.022,
            "Financial Services": 0.020,
            "N/A": 0.020
        }
        
        self.universe = []
        self.results = []
        
    def log(self, msg):
        print(msg)
        sys.stdout.flush()
    
    def get_bulletproof_universe(self):
        """Genera universo desde GitHub"""
        tickers = set()
        self.log("🌍 Generando Universo...")

        try:
            url_sp500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
            df = pd.read_csv(url_sp500)
            tickers.update(df["Symbol"].tolist())
            self.log(f"   -> S&P 500 cargado desde GitHub ({len(tickers)})")
        except:
            self.log("   ⚠️ Fallo GitHub S&P 500.")

        try:
            url_ndx = "https://raw.githubusercontent.com/nasdaq-100/nasdaq-100-symbols/master/nasdaq-100-symbols.csv"
            r = requests.get(url_ndx, timeout=15)
            lines = r.text.split("\n")
            nasdaq_ticks = [x.split(",")[0].strip() for x in lines if x and "Symbol" not in x]
            tickers.update(nasdaq_ticks)
            self.log(f"   -> Nasdaq cargado ({len(nasdaq_ticks)})")
        except:
            self.log("   ⚠️ Fallo GitHub Nasdaq.")

        BACKUP_LIST = [
            'AAPL','MSFT','GOOGL','AMZN','NVDA','META','TSLA','BRK-B','LLY','V',
            'TSM','UNH','AVGO','JPM','NVO','WMT','XOM','MA','JNJ','PG',
            'HD','MRK','COST','ABBV','ORCL','ASML','CVX','ADBE','AMD','KO',
            'PEP','CRM','BAC','ACN','CSCO','NFLX','MCD','LIN','AZN','NKE',
            'DIS','TMUS','ABT','DHR','WFC','INTC','INTU','QCOM','CMCSA','TXN',
            'VZ','UPS','PM','NEE','RTX','MS','HON','AMGN','UNP','PFE',
            'LOW','SPGI','CAT','IBM','AMAT','DE','GS','GE','LMT','PLD',
            'BLK','SYK','T','ISRG','BKNG','ELV','MDT','TJX','ADI','NOW',
            'MMC','CVS','ADP','VRTX','LRCX','UBER','REGN','PYPL','ZTS','CI'
        ]

        if len(tickers) < 50:
            self.log("⚠️ Fallaron descargas externas. Usando Lista de Respaldo Manual.")
            tickers.update(BACKUP_LIST)

        final_list = list(set([t.replace(".", "-") for t in tickers]))
        self.universe = final_list[:500]
        self.log(f"✅ Universo final: {len(self.universe)} tickers")
        return self.universe

    def analyze_ticker(self, ticker):
        """Wrapper para la función del Colab"""
        return analyze_stock_v72(ticker, self.config, self.TERMINAL_G_BY_SECTOR)

    def run_parallel_analysis(self):
        """Análisis paralelo usando función del Colab"""
        self.log("\n" + "="*60)
        self.log("🔍 Iniciando Análisis Paralelo")
        self.log("="*60)
        self.log(f"Universo: {len(self.universe)} tickers")
        self.log(f"Workers: {self.config['MAX_WORKERS']}")
        self.log(f"Filtros: ROIC>={self.config['MIN_ROIC']:.0%}, Piotroski>={self.config['MIN_PIOTROSKI']}, Coverage>={self.config['MIN_PIO_COVERAGE']}")
        self.log("="*60 + "\n")
        
        results = []
        
        with ThreadPoolExecutor(max_workers=self.config['MAX_WORKERS']) as executor:
            futures = {executor.submit(self.analyze_ticker, ticker): ticker 
                      for ticker in self.universe}
            
            with tqdm(total=len(futures), desc="Analizando", unit="ticker") as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        results.append(result)
                    pbar.update(1)
        
        self.results = results
        self.log(f"\n✅ Análisis completado: {len(results)} candidatos encontrados")
        return results

    def categorize_results(self):
        """Categoriza resultados en 3 zonas"""
        if not self.results:
            return {
                'buy_zone': [],
                'fair_zone': [],
                'watch_zone': []
            }
        
        df = pd.DataFrame(self.results)
        
        buy_zone = df[df['MOS'] > 0.10].sort_values('MOS', ascending=False)
        fair_zone = df[(df['MOS'] > 0) & (df['MOS'] <= 0.10)].sort_values('MOS', ascending=False)
        watch_zone = df[df['MOS'] <= 0].sort_values('MOS', ascending=False)
        
        self.log("\n" + "="*60)
        self.log("📊 CLASIFICACIÓN DE RESULTADOS")
        self.log("="*60)
        self.log(f"🟢 Zona de Compra (MOS > 10%): {len(buy_zone)}")
        self.log(f"🟡 Valor Justo (MOS 0-10%): {len(fair_zone)}")
        self.log(f"🔴 Watchlist (MOS < 0%): {len(watch_zone)}")
        self.log("="*60)
        
        return {
            'buy_zone': buy_zone.to_dict('records'),
            'fair_zone': fair_zone.to_dict('records'),
            'watch_zone': watch_zone.to_dict('records')
        }

    def analyze(self):
        """Pipeline completo"""
        start_time = datetime.now()
        
        self.get_bulletproof_universe()
        self.run_parallel_analysis()
        categorized = self.categorize_results()
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        df_all = pd.DataFrame(self.results) if self.results else pd.DataFrame()
        top_30 = df_all.nlargest(30, 'MOS').to_dict('records') if not df_all.empty else []
        
        return {
            'total_analyzed': len(self.universe),
            'candidates_count': len(self.results),
            'buy_candidates': len(categorized['buy_zone']),
            'fair_value': len(categorized['fair_zone']),
            'watchlist': len(categorized['watch_zone']),
            'execution_time_seconds': round(execution_time, 2),
            'generated_at': datetime.now().isoformat(),
            'config': self.config,
            'results': self.results,
            'top_30': top_30,
            'buy_zone': categorized['buy_zone'],
            'fair_zone': categorized['fair_zone'],
            'watch_zone': categorized['watch_zone']
        }


def analyze_portfolio(config=None):
    """Función helper"""
    screener = WarrenScreener(config)
    return screener.analyze()


if __name__ == "__main__":
    print("Oracle Screener V7.2 - EXACTO del Colab")
    results = analyze_portfolio()
    print(f"Candidatos: {results['candidates_count']}")