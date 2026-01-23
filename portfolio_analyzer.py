"""
portfolio_analyzer.py - Oracle Screener V7.2 (FINAL)
Análisis DCF Audit + Risk Columns + REAL Piotroski (0-9)
Motor principal de análisis con caché en Cloud Storage
"""

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import sys
import time
import json
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Silencio de logs ruidosos
import logging
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ==========================================
# ⚙️ CONFIGURACIÓN ORACLE SCREENER V7.2
# ==========================================
DEFAULT_CONFIG = {
    'MAX_WORKERS': 12,
    'MIN_ROIC': 0.08,           # 8% mínimo
    
    # ✅ Piotroski REAL (0-9)
    'MIN_PIOTROSKI': 6,         # 6 = ok, 7 = fuerte, 8+ excelente
    'MIN_PIO_COVERAGE': 7,      # mínimo señales evaluadas (de 9)
    
    # WACC CONFIG (Dinámico)
    'RISK_FREE_RATE': 0.042,      # Tasa bono 10 años aprox
    'EQUITY_RISK_PREMIUM': 0.05,  # Prima de riesgo mercado
    'MIN_WACC': 0.07,             # Piso para el WACC
    'MAX_WACC': 0.15,             # Techo para el WACC (para no castigar demasiado high beta)
    
    'MARGIN_OF_SAFETY_VIEW': -0.20  # Watchlist hasta -20%
}

# Terminal growth por sector (evita inflar bond proxies)
TERMINAL_G_BY_SECTOR = {
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

# Cache configuration
DEFAULT_CACHE_TTL_HOURS = 24
DEFAULT_CACHE_FILE_NAME = "screener_results.json"


def log(msg):
    """Helper para logging con flush inmediato"""
    print(msg)
    sys.stdout.flush()


def safe_float(x):
    """Convierte a float de forma segura"""
    try:
        if x is None:
            return np.nan
        if isinstance(x, (np.floating, float)) and np.isnan(x):
            return np.nan
        return float(x)
    except:
        return np.nan


def get_latest_and_prev(series: pd.Series):
    """Obtiene valor actual y anterior de una serie"""
    if series is None or series.empty:
        return (np.nan, np.nan)
    a = safe_float(series.iloc[0])
    b = safe_float(series.iloc[1]) if len(series) > 1 else np.nan
    return a, b


class CacheManager:
    """
    Gestiona el caché en Google Cloud Storage
    """
    
    def __init__(self, bucket_name=None, cache_file_name=None, cache_ttl_hours=None):
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET_NAME", "warren-screener-cache")
        self.cache_file_name = cache_file_name or DEFAULT_CACHE_FILE_NAME
        self.cache_ttl_hours = cache_ttl_hours or DEFAULT_CACHE_TTL_HOURS
        
        self.storage_client = None
        self.bucket = None
        self.gcs_available = False
        
        self._init_storage()
    
    def _init_storage(self):
        """Inicializa conexión a Cloud Storage"""
        try:
            from google.cloud import storage
            self.storage_client = storage.Client()
            self.bucket = self.storage_client.bucket(self.bucket_name)
            self.gcs_available = True
            log(f"✓ Cloud Storage conectado al bucket: {self.bucket_name}")
        except Exception as e:
            log(f"⚠ Cloud Storage no disponible: {e}")
            self.gcs_available = False
    
    def get_cached_results(self):
        """Intenta obtener resultados del caché en Cloud Storage"""
        if not self.gcs_available:
            log("⚠ Cloud Storage no disponible, ejecutando sin caché")
            return None
        
        try:
            blob = self.bucket.blob(self.cache_file_name)
            
            if not blob.exists():
                log("⚠ No hay datos en caché, ejecutando análisis completo")
                return None
            
            cache_content = blob.download_as_string()
            data = json.loads(cache_content)
            
            if "results" not in data or "cached_at" not in data:
                log("⚠ Caché corrupto, regenerando datos...")
                blob.delete()
                return None
            
            cache_time = datetime.fromisoformat(data.get("cached_at", ""))
            time_diff = datetime.now() - cache_time
            
            if time_diff < timedelta(hours=self.cache_ttl_hours):
                hours_ago = round(time_diff.total_seconds() / 3600, 1)
                log(f"✓ Usando datos del caché (generados hace {hours_ago} horas)")
                return data["results"]
            else:
                log(f"⚠ Caché expirado (más de {self.cache_ttl_hours}h), regenerando datos...")
                blob.delete()
                return None
                
        except Exception as e:
            log(f"⚠ Error leyendo caché: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_full_cached_data(self):
        """
        Obtiene el objeto completo del caché (no solo results)
        Usado por /refine para tener acceso a todos los datos del análisis
        """
        if not self.gcs_available:
            return None
        
        try:
            blob = self.bucket.blob(self.cache_file_name)
            
            if not blob.exists():
                return None
            
            cache_content = blob.download_as_string()
            data = json.loads(cache_content)
            
            if "results" not in data or "cached_at" not in data:
                blob.delete()
                return None
            
            cache_time = datetime.fromisoformat(data.get("cached_at", ""))
            time_diff = datetime.now() - cache_time
            
            if time_diff < timedelta(hours=self.cache_ttl_hours):
                return data["results"]
            else:
                blob.delete()
                return None
                
        except Exception as e:
            return None
    
    def save_to_cache(self, results):
        """Guarda resultados en Cloud Storage"""
        if not self.gcs_available:
            log("⚠ Cloud Storage no disponible, no se guardará caché")
            return False
        
        try:
            cache_data = {
                "results": results,
                "cached_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(hours=self.cache_ttl_hours)).isoformat()
            }
            
            blob = self.bucket.blob(self.cache_file_name)
            json_string = json.dumps(cache_data, default=str, allow_nan=False)
            json_string = json_string.replace('NaN', 'null').replace('Infinity', 'null').replace('-Infinity', 'null')
            
            blob.upload_from_string(json_string, content_type='application/json')
            log(f"✓ Resultados guardados en caché por {self.cache_ttl_hours} horas")
            return True
            
        except Exception as e:
            log(f"⚠ Error guardando en caché: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_cache_status(self):
        """Obtiene el estado actual del caché"""
        if not self.gcs_available:
            return {
                "cache_enabled": False,
                "message": "Cloud Storage not available"
            }
        
        try:
            blob = self.bucket.blob(self.cache_file_name)
            
            if not blob.exists():
                return {
                    "cache_enabled": True,
                    "cache_exists": False,
                    "message": "No cached data available"
                }
            
            cache_content = blob.download_as_string()
            data = json.loads(cache_content)
            
            cache_time = datetime.fromisoformat(data.get("cached_at", ""))
            expires_at = datetime.fromisoformat(data.get("expires_at", ""))
            time_remaining = expires_at - datetime.now()
            
            is_expired = time_remaining.total_seconds() <= 0
            
            return {
                "cache_enabled": True,
                "cache_exists": True,
                "is_expired": is_expired,
                "cached_at": cache_time.isoformat(),
                "expires_at": expires_at.isoformat(),
                "time_remaining_hours": round(time_remaining.total_seconds() / 3600, 2),
                "results_count": data["results"].get("total_analyzed", 0),
                "candidates_count": data["results"].get("candidates_count", 0),
                "file_size_kb": round(blob.size / 1024, 2)
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def clear_cache(self):
        """Limpia el caché manualmente"""
        if not self.gcs_available:
            return {"status": "Cloud Storage not available"}
        
        try:
            blob = self.bucket.blob(self.cache_file_name)
            if blob.exists():
                blob.delete()
                log("🗑️ Caché limpiado manualmente")
                return {
                    "status": "success",
                    "message": "Cache cleared successfully"
                }
            else:
                return {
                    "status": "success",
                    "message": "No cache to clear"
                }
        except Exception as e:
            log(f"❌ Error limpiando caché: {str(e)}")
            return {"error": str(e)}


class PortfolioAnalyzer:
    """
    Oracle Screener V7.2 - Motor principal de análisis de acciones
    Implementa DCF Audit + Risk Columns + REAL Piotroski (0-9)
    """
    
    def __init__(self, config=None, cache_manager=None):
        """
        Args:
            config: Dict con configuración personalizada
            cache_manager: Instancia de CacheManager (opcional)
        """
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.cache_manager = cache_manager or CacheManager()
        self.results = []
        
    def get_bulletproof_universe(self):
        """Genera universo de tickers desde múltiples fuentes"""
        tickers = set()
        log("🌍 Generando Universo...")

        # Intento 1: GitHub S&P 500
        try:
            url_sp500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
            df = pd.read_csv(url_sp500)
            tickers.update(df["Symbol"].tolist())
            log(f"   -> S&P 500 cargado desde GitHub ({len(tickers)})")
        except:
            log("   ⚠️ Fallo GitHub S&P 500.")

        # Intento 2: Nasdaq 100
        try:
            url_ndx = "https://raw.githubusercontent.com/nasdaq-100/nasdaq-100-symbols/master/nasdaq-100-symbols.csv"
            r = requests.get(url_ndx, timeout=15)
            lines = r.text.split("\n")
            nasdaq_ticks = [x.split(",")[0].strip() for x in lines if x and "Symbol" not in x]
            tickers.update(nasdaq_ticks)
            log(f"   -> Nasdaq cargado ({len(nasdaq_ticks)})")
        except:
            log("   ⚠️ Fallo GitHub Nasdaq.")

        # Lista de respaldo manual (Ampliada)
        BACKUP_LIST = [
            'AAPL','MSFT','GOOGL','AMZN','NVDA','META','TSLA','BRK-B','LLY','V','TSM',
            'UNH','JPM','JNJ','PG','HD','MA','CVX','ABBV','MRK','KO','PEP','COST','AVGO',
            'MCD','WMT','CSCO','BAC','ACN','ADBE','LIN','DIS','NKE','TXN','AMD','PM','NEST',
            'ORCL','UPS','WFC','QCOM','INTC','HON','LOW','IBM','CAT','UNP','SBUX','GS',
            'MS','DE','BLK','BA','MMM','GE','RTX','AMGN','AMT','NOW','SPGI','INTU','ISRG',
            'PLD','SYK','ZTS','ADP','GILD','MDLZ','T','TJX','CVS','LMT','AXP','ADI','MMC',
            'CB','VRTX','UBER','REGN','CI','C','MO','SO','DUK','D','USB','PNC','TGT','ITW',
            'BDX','CL','ETN','SLB','EOG','COP','OXY','PXD','MPC','PSX','VLO','KMI','WMB',
            'TRGP','OKE','CTRA','DVN','FANG','HAL','BKR','HES','APA','MRO','OVV','EQT',
            'CHK','AR','SWN','RRC','MTDR','PDCE','CIVI','CNX','CRK','MGY','SM','CPE',
            'LPI','TALO','WLL','OAS','SBOW','ESTE','BATL','REI','AMPY','GDP','LPG','DORL',
            'NGL','USAC','CEQP','ET','EPD','PAA','MMP','NS','SHLX','HMLP','KNOP','TNK',
            'STNG','INSW','ASC','EURN','FRO','DHT','NAT','TNP','SFL','GSL','DAC','ZIM',
            'MATX','GNK','EGLE','SBLK','DSX','GRIN','PANL','SB','NM','NMM','CMRE','GASS',
            'GLBS','SHIP','TOPS','PXS','ESEA','EDRY','BDI','DRY','DS','SYF','WRB','PGR',
            'CINF','DVA','OMC','COR','MTCH','EG','MET','ALL','HIG','PFG','TRV','VZ',
            'CMCSA','KMB','GL','AMP','AIZ','BIIB','CLX','MOH','HSY','IPG','GDDY','LULU',
            'AZO','PYPL','SNA','FFIV','DECK','JKHY','EXPE','APTV','MAS','FDS','AJG',
            'MKTX','LDOS','RMD','CDW','CPB','CAH','BBY','PHM','LVS','DELL','HSIC','CHD',
            'WYNN','LKQ','YUM','CBOE','TROW','GD','NWSA','LII','PSA','CRM','VST','NWS',
            'GEN','ZBRA','OTIS','WSM','PPG','KVUE','MNST','ALGN','ROST','CTAS','DPZ',
            'WAB','PNR','RSG','AME','ECL','CHTR','NCLH','EBAY','SHW','SBAC','KR','COIN',
            'NDAQ','PKG','STE','TMO','GOOG','IQV','EMR','SPG','FICO','CMI','DOV','PODD',
            'IDXX','HWM','STX','TPL','RCL'
        ]

        if len(tickers) < 50:
            log(f"   ⚠️ Fallaron descargas externas. Usando Lista de Respaldo Manual ({len(BACKUP_LIST)} tickers).")
            tickers.update(BACKUP_LIST)

        final_list = list(set([t.replace(".", "-") for t in tickers]))
        final_count = min(600, len(final_list))
        log(f"   ✅ Total final: {final_count} tickers para analizar")
        return final_list[:600]
    
    @staticmethod
    def get_fuzzy_series(df, keywords):
        """Búsqueda fuzzy de campos en DataFrames financieros"""
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
    
    def compute_piotroski_fscore(self, inc, bal, cf):
        """
        Piotroski F-Score REAL (0-9) + Coverage
        Retorna: (score, coverage) donde coverage = #señales evaluadas
        """
        score = 0
        covered = 0
        
        # Series necesarias
        ni = self.get_fuzzy_series(inc, ["Net Income", "NetIncome"])
        ocf = self.get_fuzzy_series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        
        assets = self.get_fuzzy_series(bal, ["Total Assets"])
        
        # Deuda ideal: long term, si no total
        ltd = self.get_fuzzy_series(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"])
        if ltd.empty:
            ltd = self.get_fuzzy_series(bal, ["Total Debt"])
        
        current_assets = self.get_fuzzy_series(bal, ["Current Assets", "Total Current Assets"])
        current_liab = self.get_fuzzy_series(bal, ["Current Liabilities", "Total Current Liabilities"])
        
        revenue = self.get_fuzzy_series(inc, ["Total Revenue", "Revenue"])
        gross_profit = self.get_fuzzy_series(inc, ["Gross Profit"])
        
        shares = self.get_fuzzy_series(bal, ["Ordinary Shares Number", "Share Issued"])
        
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
    
    def analyze_stock(self, ticker):
        """
        Analiza una acción individual con Oracle Screener V7.2
        DCF Audit + Risk Columns + REAL Piotroski (0-9)
        """
        try:
            t = yf.Ticker(ticker)

            # Fast filter
            try:
                fast = t.fast_info
                market_cap = safe_float(getattr(fast, "market_cap", np.nan))
                if np.isnan(market_cap) or market_cap < 2_000_000_000: # Mid-cap filter
                    return None
                price = safe_float(getattr(fast, "last_price", np.nan))
                shares = safe_float(getattr(fast, "shares", np.nan))
                if np.isnan(price) or price <= 0 or np.isnan(shares) or shares <= 0:
                    return None
            except:
                return None

            inc = t.income_stmt
            bal = t.balance_sheet
            cf = t.cashflow
            
            if inc is None or bal is None or cf is None or inc.empty or bal.empty or cf.empty:
                return None

            # Orden cronológico (más reciente primero)
            inc = inc[sorted(inc.columns, reverse=True)]
            bal = bal[sorted(bal.columns, reverse=True)]
            cf = cf[sorted(cf.columns, reverse=True)]

            # --- Extracción fuzzy ---
            ni = self.get_fuzzy_series(inc, ["Net Income", "NetIncome"])
            ebit = self.get_fuzzy_series(inc, ["EBIT", "Operating Income"])
            ocf = self.get_fuzzy_series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])

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

            # --- Valores actuales ---
            curr_ebit = safe_float(ebit.iloc[0]) if (not ebit.empty and not pd.isna(ebit.iloc[0])) else safe_float(ni.iloc[0])
            curr_eq = safe_float(equity.iloc[0]) if not pd.isna(equity.iloc[0]) else 0.0
            curr_debt = safe_float(debt.iloc[0]) if (not debt.empty and not pd.isna(debt.iloc[0])) else 0.0
            curr_cash = safe_float(cash.iloc[0]) if (not cash.empty and not pd.isna(cash.iloc[0])) else 0.0

            invested_cap = curr_eq + curr_debt - curr_cash
            roic = (curr_ebit * 0.79) / invested_cap if invested_cap > 0 else 0.0
            
            if roic < self.config['MIN_ROIC']:
                return None

            # ✅ Piotroski REAL (0-9) + coverage
            piotroski, pio_cov = self.compute_piotroski_fscore(inc, bal, cf)

            # Si coverage es bajo, no confiamos
            if pio_cov < self.config['MIN_PIO_COVERAGE']:
                return None

            if piotroski < self.config['MIN_PIOTROSKI']:
                return None

            # Sector y Beta
            try:
                info = t.info
                sector = info.get("sector", "N/A")
                beta = safe_float(info.get("beta", 1.0))
                if np.isnan(beta): beta = 1.0
            except:
                sector = "N/A"
                beta = 1.0

            # WACC Dinámico (CAPM approx)
            wacc = self.config['RISK_FREE_RATE'] + (beta * self.config['EQUITY_RISK_PREMIUM'])
            wacc = max(self.config['MIN_WACC'], min(wacc, self.config['MAX_WACC']))

            # --- FCF ---
            ocf_val = safe_float(ocf.iloc[0]) if not pd.isna(ocf.iloc[0]) else np.nan
            cpx_val = abs(safe_float(capex.iloc[0])) if (not capex.empty and not pd.isna(capex.iloc[0])) else 0.0
            fcf = ocf_val - cpx_val if not np.isnan(ocf_val) else np.nan

            # --- Growth proxy ---
            growth_est = min(roic * 0.5, 0.14)
            growth_est = max(growth_est, 0.03)

            # Terminal g por sector
            terminal_g = TERMINAL_G_BY_SECTOR.get(sector, TERMINAL_G_BY_SECTOR["N/A"])

            # --- DCF 2-Stage ---
            intrinsic = 0.0
            mos = -0.99
            tv_weight = np.nan

            if (not np.isnan(fcf)) and fcf > 0:
                r = wacc

                # Stage 1: 5 años de crecimiento
                pv_stage1 = 0.0
                for i in range(1, 6):
                    fcf_i = fcf * ((1 + growth_est) ** i)
                    pv_stage1 += fcf_i / ((1 + r) ** i)

                # Validar que discount_rate > terminal_g
                if r <= terminal_g:
                    return None

                # Stage 2: Terminal value
                terminal_fcf = fcf * ((1 + growth_est) ** 5)
                tv = (terminal_fcf * (1 + terminal_g)) / (r - terminal_g)
                pv_tv = tv / ((1 + r) ** 5)

                ev = pv_stage1 + pv_tv
                equity_val = ev + curr_cash - curr_debt
                intrinsic = equity_val / shares

                if intrinsic > 0:
                    mos = (intrinsic - price) / intrinsic
                    tv_weight = pv_tv / ev if ev > 0 else np.nan

            # Filtro de salida
            if mos < self.config['MARGIN_OF_SAFETY_VIEW'] and piotroski < 7:
                return None

            # --- Risk Columns ---
            debt_to_mcap = (curr_debt / market_cap) if (market_cap > 0) else np.nan
            fcf_yield = (fcf / market_cap) if (market_cap > 0 and not np.isnan(fcf)) else np.nan

            return {
                'Ticker': ticker,
                'Price': round(price, 2),
                'Intrinsic': round(intrinsic, 2),
                'MOS': round(mos, 4),
                'ROIC': round(roic, 4),
                'Piotroski': int(piotroski),
                'Piotroski_Coverage': int(pio_cov),
                'Growth_Est': round(growth_est, 4),
                'Terminal_g': round(terminal_g, 4),
                'WACC': round(wacc, 4),
                'Sector': sector,
                # Nuevas columnas
                'FCF': round(fcf, 2) if not np.isnan(fcf) else None,
                'OCF': round(ocf_val, 2) if not np.isnan(ocf_val) else None,
                'Debt': round(curr_debt, 2),
                'Cash': round(curr_cash, 2),
                'MarketCap': round(market_cap, 2),
                'Weight': round(tv_weight, 4) if not np.isnan(tv_weight) else None,
                'DCF_TV_Weight': round(tv_weight, 4) if not np.isnan(tv_weight) else None,
                # Columnas adicionales de riesgo
                'Debt_to_MCap': round(debt_to_mcap, 4) if not np.isnan(debt_to_mcap) else None,
                'FCF_Yield': round(fcf_yield, 4) if not np.isnan(fcf_yield) else None
            }

        except Exception as e:
            return None
    
    def run_analysis(self, use_cache=True):
        """Ejecuta el análisis completo con caché"""
        
        # Verificar caché primero
        if use_cache:
            cached = self.cache_manager.get_cached_results()
            if cached is not None:
                cached['from_cache'] = True
                return cached
        
        # Si no hay caché, ejecutar análisis
        start_time = time.time()
        
        log("🎯 Iniciando Oracle Screener V7.2")
        log("="*60)
        
        # 1. Obtener universo
        tickers = self.get_bulletproof_universe()
        log(f"🎯 Objetivo Real: Analizar {len(tickers)} empresas.")
        
        # 2. Análisis paralelo
        results = []
        with ThreadPoolExecutor(max_workers=self.config['MAX_WORKERS']) as executor:
            futures = {executor.submit(self.analyze_stock, t): t for t in tickers}
            for future in as_completed(futures):
                r = future.result()
                if r: 
                    results.append(r)
        
        # 3. Procesar resultados
        if not results:
            error_result = {
                "error": "Sin resultados (posible rate-limit o filtros muy estrictos)",
                "total_analyzed": len(tickers),
                "candidates_count": 0,
                "from_cache": False,
                "generated_at": datetime.now().isoformat()
            }
            log("❌ Sin resultados finales")
            return error_result
        
        df = pd.DataFrame(results)
        df = df.sort_values(by='MOS', ascending=False, na_position='last')
        
        # 4. Clasificación
        buy_candidates = df[df['MOS'] > 0.10].copy() if 'MOS' in df.columns else pd.DataFrame()
        fair_value = df[(df['MOS'] > 0) & (df['MOS'] <= 0.10)].copy() if 'MOS' in df.columns else pd.DataFrame()
        watchlist = df[df['MOS'] <= 0].copy() if 'MOS' in df.columns else pd.DataFrame()
        
        # 5. Resultado final
        execution_time = round(time.time() - start_time, 2)
        
        # Convertir TODOS los resultados a diccionarios (ordenados por MOS)
        all_results = df.replace({np.nan: None}).to_dict('records')
        
        result = {
            "total_analyzed": len(tickers),
            "candidates_count": len(df),
            "results": all_results,
            "summary": {
                "buy_zone_count": len(buy_candidates),
                "fair_zone_count": len(fair_value),
                "watch_zone_count": len(watchlist)
            },
            "generated_at": datetime.now().isoformat(),
            "cache_enabled": self.cache_manager.gcs_available,
            "from_cache": False,
            "execution_time_seconds": execution_time,
            "version": "Oracle Screener V7.2"
        }
        
        log("="*60)
        log(f"💎 RESULTADOS FINALES ({len(df)} encontrados):")
        log(f"📊 Total analizados: {len(tickers)}")
        log(f"⭐ Candidatos finales: {len(df)}")
        log(f"   🟢 Zona de Compra (MOS > 10%): {len(buy_candidates)}")
        log(f"   🟡 Valor Justo (MOS 0-10%): {len(fair_value)}")
        log(f"   🔴 Watchlist (MOS < 0%): {len(watchlist)}")
        log(f"⏱️  Tiempo de ejecución: {execution_time}s")
        log("="*60)
        
        # Guardar en caché
        if use_cache:
            self.cache_manager.save_to_cache(result)
        
        return result


# Función de conveniencia para uso directo
def analyze_portfolio(config=None, use_cache=True):
    """
    Función de conveniencia para ejecutar análisis
    
    Args:
        config: Dict con configuración personalizada
        use_cache: Si usar caché de Cloud Storage
        
    Returns:
        Dict con resultados del análisis
    """
    analyzer = PortfolioAnalyzer(config=config)
    return analyzer.run_analysis(use_cache=use_cache)


# Para uso standalone
if __name__ == "__main__":
    print("="*60)
    print("🏛️ Oracle Screener V7.2 (FINAL)")
    print("   DCF Audit + Risk Columns + REAL Piotroski (0-9)")
    print("="*60)
    print("")
    print("Uso:")
    print("  from portfolio_analyzer import PortfolioAnalyzer, CacheManager")
    print("  analyzer = PortfolioAnalyzer()")
    print("  results = analyzer.run_analysis()")
    print("")
    print("  # O con función de conveniencia:")
    print("  from portfolio_analyzer import analyze_portfolio")
    print("  results = analyze_portfolio()")
    print("")
    print("Configuración actual:")
    print(f"  MIN_ROIC: {DEFAULT_CONFIG['MIN_ROIC']*100}%")
    print(f"  MIN_PIOTROSKI: {DEFAULT_CONFIG['MIN_PIOTROSKI']} (real 0-9)")
    print(f"  MIN_PIO_COVERAGE: {DEFAULT_CONFIG['MIN_PIO_COVERAGE']}/9 señales")
    print(f"  MIN_WACC: {DEFAULT_CONFIG['MIN_WACC']*100}%")
    print(f"  MAX_WACC: {DEFAULT_CONFIG['MAX_WACC']*100}%")
    print(f"  RISK_FREE_RATE: {DEFAULT_CONFIG['RISK_FREE_RATE']*100}%")
