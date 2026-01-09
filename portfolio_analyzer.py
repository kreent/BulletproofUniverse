"""
portfolio_analyzer.py - Oracle Screener V7.2
Análisis DCF 2-Stage + ROIC + Piotroski Real (0-9)
"""

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm.auto import tqdm


class WarrenScreener:
    """
    Oracle Screener V7.2 - DCF con Piotroski Real + Columnas de Riesgo
    """
    
    def __init__(self, config=None):
        """
        Args:
            config: Dict con configuración del screener
        """
        self.config = config or {
            'MAX_WORKERS': 12,
            'MIN_ROIC': 0.08,
            'MIN_PIOTROSKI': 6,        # 6 = ok, 7 = fuerte, 8+ excelente
            'MIN_PIO_COVERAGE': 7,     # mínimo señales evaluadas (de 9)
            'DISCOUNT_RATE': 0.09,
            'MARGIN_OF_SAFETY_VIEW': -0.20
        }
        
        # Terminal growth por sector (evita inflar bond proxies)
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
        """Helper para logging"""
        print(msg)
        sys.stdout.flush()
    
    # ==========================================
    # 1. UNIVERSO
    # ==========================================
    def get_bulletproof_universe(self):
        """Genera universo robusto de tickers desde múltiples fuentes"""
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

    # ==========================================
    # 2. FUZZY SERIES
    # ==========================================
    def get_fuzzy_series(self, df, keywords):
        """Búsqueda fuzzy de series en dataframes financieros"""
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

    def safe_float(self, x):
        """Conversión segura a float"""
        try:
            if x is None:
                return np.nan
            if isinstance(x, (np.floating, float)) and np.isnan(x):
                return np.nan
            return float(x)
        except:
            return np.nan

    def get_latest_and_prev(self, series: pd.Series):
        """Obtiene valor actual y anterior de una serie"""
        if series is None or series.empty:
            return (np.nan, np.nan)
        a = self.safe_float(series.iloc[0])
        b = self.safe_float(series.iloc[1]) if len(series) > 1 else np.nan
        return a, b

    # ==========================================
    # 3. REAL PIOTROSKI (0–9) + COVERAGE
    # ==========================================
    def compute_piotroski_fscore(self, inc, bal, cf):
        """
        Piotroski F-Score real (0-9).
        Retorna: (score, coverage) donde coverage = #señales evaluadas.
        """
        score = 0
        covered = 0

        # Series necesarias
        ni = self.get_fuzzy_series(inc, ["Net Income", "NetIncome"])
        ocf = self.get_fuzzy_series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])

        assets = self.get_fuzzy_series(bal, ["Total Assets"])
        # deuda ideal: long term, si no total
        ltd = self.get_fuzzy_series(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"])
        if ltd.empty:
            ltd = self.get_fuzzy_series(bal, ["Total Debt"])

        current_assets = self.get_fuzzy_series(bal, ["Current Assets", "Total Current Assets"])
        current_liab = self.get_fuzzy_series(bal, ["Current Liabilities", "Total Current Liabilities"])

        revenue = self.get_fuzzy_series(inc, ["Total Revenue", "Revenue"])
        gross_profit = self.get_fuzzy_series(inc, ["Gross Profit"])

        shares = self.get_fuzzy_series(bal, ["Ordinary Shares Number", "Share Issued"])

        # Valores t y t-1
        ni_t, ni_t1 = self.get_latest_and_prev(ni)
        ocf_t, ocf_t1 = self.get_latest_and_prev(ocf)
        assets_t, assets_t1 = self.get_latest_and_prev(assets)
        ltd_t, ltd_t1 = self.get_latest_and_prev(ltd)
        ca_t, ca_t1 = self.get_latest_and_prev(current_assets)
        cl_t, cl_t1 = self.get_latest_and_prev(current_liab)
        rev_t, rev_t1 = self.get_latest_and_prev(revenue)
        gp_t, gp_t1 = self.get_latest_and_prev(gross_profit)
        sh_t, sh_t1 = self.get_latest_and_prev(shares)

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

    # ==========================================
    # 4. ANALYZE STOCK (V7.2)
    # ==========================================
    def analyze_ticker(self, ticker: str):
        """Análisis completo de un ticker usando Oracle Screener V7.2"""
        try:
            t = yf.Ticker(ticker)

            # Fast filter - market cap más permisivo
            try:
                fast = t.fast_info
                market_cap = self.safe_float(getattr(fast, "market_cap", np.nan))
                
                # Reducir a 1B para tener más candidatos
                if np.isnan(market_cap) or market_cap < 1_000_000_000:
                    return None
                    
                price = self.safe_float(getattr(fast, "last_price", np.nan))
                shares = self.safe_float(getattr(fast, "shares", np.nan))
                if np.isnan(price) or price <= 0 or np.isnan(shares) or shares <= 0:
                    return None
            except Exception as e:
                # Si fast_info falla, intentar con info
                try:
                    info = t.info
                    market_cap = self.safe_float(info.get("marketCap", np.nan))
                    if np.isnan(market_cap) or market_cap < 1_000_000_000:
                        return None
                    price = self.safe_float(info.get("currentPrice", info.get("regularMarketPrice", np.nan)))
                    shares = self.safe_float(info.get("sharesOutstanding", np.nan))
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
            ni = self.get_fuzzy_series(inc, ["Net Income", "NetIncome"])
            ebit = self.get_fuzzy_series(inc, ["EBIT", "Operating Income"])
            ocf = self.get_fuzzy_series(cf,  ["Operating Cash Flow", "Total Cash From Operating Activities"])

            capex = self.get_fuzzy_series(cf, [
                "Capital Expenditures",
                "Purchase of PPE",
                "Investments in Property Plant and Equipment"
            ])

            equity = self.get_fuzzy_series(bal, ["Stockholders Equity", "Total Equity"])

            # Deuda robusta
            debt = self.get_fuzzy_series(bal, [
                "Total Debt",
                "Long Term Debt",
                "Long Term Debt And Capital Lease Obligation",
                "Short Long Term Debt",
                "Short Term Debt"
            ])

            # Cash robusto
            cash = self.get_fuzzy_series(bal, [
                "Cash",
                "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments"
            ])

            if ni.empty or ocf.empty or equity.empty:
                return None

            # --- valores actuales ---
            curr_ebit = self.safe_float(ebit.iloc[0]) if (not ebit.empty and not pd.isna(ebit.iloc[0])) else self.safe_float(ni.iloc[0])
            curr_eq   = self.safe_float(equity.iloc[0]) if not pd.isna(equity.iloc[0]) else 0.0
            curr_debt = self.safe_float(debt.iloc[0]) if (not debt.empty and not pd.isna(debt.iloc[0])) else 0.0
            curr_cash = self.safe_float(cash.iloc[0]) if (not cash.empty and not pd.isna(cash.iloc[0])) else 0.0

            invested_cap = curr_eq + curr_debt - curr_cash
            roic = (curr_ebit * 0.79) / invested_cap if invested_cap > 0 else 0.0
            if roic < self.config["MIN_ROIC"]:
                return None

            # ✅ Piotroski REAL (0-9) + coverage
            piotroski, pio_cov = self.compute_piotroski_fscore(inc, bal, cf)

            # Si coverage es bajo, no confiamos
            if pio_cov < self.config["MIN_PIO_COVERAGE"]:
                return None

            if piotroski < self.config["MIN_PIOTROSKI"]:
                return None

            sector = t.info.get("sector", "N/A")

            # --- FCF ---
            ocf_val = self.safe_float(ocf.iloc[0]) if not pd.isna(ocf.iloc[0]) else np.nan
            cpx_val = abs(self.safe_float(capex.iloc[0])) if (not capex.empty and not pd.isna(capex.iloc[0])) else 0.0
            fcf = ocf_val - cpx_val if not np.isnan(ocf_val) else np.nan

            # --- Growth proxy ---
            growth_proxy = min(roic * 0.5, 0.14)
            growth_proxy = max(growth_proxy, 0.03)

            # Terminal g por sector
            terminal_g = self.TERMINAL_G_BY_SECTOR.get(sector, self.TERMINAL_G_BY_SECTOR["N/A"])

            # --- DCF ---
            intrinsic = 0.0
            mos = -0.99
            tv_weight = np.nan

            if (not np.isnan(fcf)) and fcf > 0:
                r = self.config["DISCOUNT_RATE"]

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
            if mos < self.config["MARGIN_OF_SAFETY_VIEW"] and piotroski < 7:
                return None

            return {
                'Ticker': ticker,
                'Price': round(price, 2),
                'Intrinsic': round(intrinsic, 2),
                'MOS': round(mos, 4),
                'ROIC': round(roic, 4),
                'Piotroski': int(piotroski),
                'Growth_Est': round(growth_proxy, 4),
                'Sector': sector,
                'FCF': round(fcf, 2) if not np.isnan(fcf) else None,
                'OCF': round(ocf_val, 2) if not np.isnan(ocf_val) else None,
                'Debt': round(curr_debt, 2),
                'Cash': round(curr_cash, 2),
                'MarketCap': round(market_cap, 2),
                'Weight': round(tv_weight, 4) if not np.isnan(tv_weight) else None
            }

        except Exception:
            return None

    def run_parallel_analysis(self):
        """Ejecuta análisis paralelo sobre todo el universo"""
        self.log("\n" + "="*60)
        self.log("🔍 Iniciando Análisis Paralelo")
        self.log("="*60)
        self.log(f"Universo: {len(self.universe)} tickers")
        self.log(f"Workers: {self.config['MAX_WORKERS']}")
        self.log(f"Filtros: ROIC>={self.config['MIN_ROIC']:.0%}, Piotroski>={self.config['MIN_PIOTROSKI']}, Coverage>={self.config['MIN_PIO_COVERAGE']}")
        self.log("="*60 + "\n")
        
        results = []
        analyzed_count = 0
        error_count = 0
        
        with ThreadPoolExecutor(max_workers=self.config['MAX_WORKERS']) as executor:
            futures = {executor.submit(self.analyze_ticker, ticker): ticker 
                      for ticker in self.universe}
            
            with tqdm(total=len(futures), desc="Analizando", unit="ticker") as pbar:
                for future in as_completed(futures):
                    analyzed_count += 1
                    try:
                        result = future.result()
                        if result:
                            results.append(result)
                            # Log cada resultado encontrado
                            if len(results) <= 5:  # Solo los primeros 5 para no saturar
                                self.log(f"  ✅ {result['Ticker']}: MOS={result['MOS']:.1%}, Piotroski={result['Piotroski']}")
                    except Exception as e:
                        error_count += 1
                        if error_count <= 3:  # Solo los primeros 3 errores
                            ticker = futures[future]
                            self.log(f"  ❌ Error en {ticker}: {str(e)[:100]}")
                    pbar.update(1)
        
        self.results = results
        self.log(f"\n📊 Estadísticas:")
        self.log(f"   Total analizado: {analyzed_count}")
        self.log(f"   Candidatos encontrados: {len(results)}")
        self.log(f"   Errores: {error_count}")
        self.log(f"   Tasa de éxito: {len(results)/analyzed_count*100:.1f}%" if analyzed_count > 0 else "   Tasa de éxito: 0%")
        
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
        """Pipeline completo de análisis"""
        start_time = datetime.now()
        
        # 1. Generar universo
        self.get_bulletproof_universe()
        
        # 2. Análisis paralelo
        self.run_parallel_analysis()
        
        # 3. Categorizar
        categorized = self.categorize_results()
        
        # 4. Estadísticas
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Top 30 por MOS
        df_all = pd.DataFrame(self.results) if self.results else pd.DataFrame()
        top_30 = df_all.nlargest(30, 'MOS').to_dict('records') if not df_all.empty else []
        
        result = {
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
        
        return result


# Función helper para uso directo
def analyze_portfolio(config=None):
    """
    Función de conveniencia para análisis completo
    
    Args:
        config: Dict opcional con configuración personalizada
        
    Returns:
        Dict con resultados completos del análisis
    """
    screener = WarrenScreener(config)
    return screener.analyze()


# Para uso standalone
if __name__ == "__main__":
    print("Oracle Screener V7.2 - Portfolio Analyzer")
    print("Uso:")
    print("  from portfolio_analyzer import analyze_portfolio")
    print("  results = analyze_portfolio()")
    print("\nEjecutando análisis de ejemplo...")
    
    results = analyze_portfolio()
    
    print(f"\n{'='*60}")
    print("RESUMEN DE RESULTADOS")
    print(f"{'='*60}")
    print(f"Total analizado: {results['total_analyzed']}")
    print(f"Candidatos encontrados: {results['candidates_count']}")
    print(f"🟢 Zona de compra: {results['buy_candidates']}")
    print(f"🟡 Valor justo: {results['fair_value']}")
    print(f"🔴 Watchlist: {results['watchlist']}")
    print(f"⏱️  Tiempo: {results['execution_time_seconds']}s")
    print(f"{'='*60}")
