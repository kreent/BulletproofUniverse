# =========================================
# Warren Screener v8 - DCF 2-Stage + Quality Focus
# CON CACHÉ EN CLOUD STORAGE DE 24 HORAS
# Análisis basado en ROIC, Piotroski y DCF avanzado
# =========================================

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import io
import sys
import time
import logging
import json
import os
from datetime import datetime, timedelta
from tqdm.auto import tqdm
from flask import Flask, jsonify, request
from google.cloud import storage
from concurrent.futures import ThreadPoolExecutor, as_completed

# Post-processor
try:
    from post_processor import ResultsPostProcessor
    POST_PROCESSOR_AVAILABLE = True
except ImportError:
    POST_PROCESSOR_AVAILABLE = False
    print("⚠️  Post-processor no disponible")

# Portfolio Refiner
try:
    from portfolio_refiner import PortfolioRefiner
    PORTFOLIO_REFINER_AVAILABLE = True
except ImportError:
    PORTFOLIO_REFINER_AVAILABLE = False
    print("⚠️  Portfolio Refiner no disponible")

# Portfolio Tracker
try:
    from portfolio_tracker import PortfolioTracker
    PORTFOLIO_TRACKER_AVAILABLE = True
except ImportError:
    PORTFOLIO_TRACKER_AVAILABLE = False
    print("⚠️  Portfolio Tracker no disponible")

# Silencio de logs ruidosos
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# -------- Configuración de Cloud Storage --------
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "warren-screener-cache")
CACHE_FILE_NAME = "screener_results.json"
CACHE_TTL_HOURS = 24

# Inicializar cliente de Cloud Storage
try:
    storage_client = storage.Client()
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    GCS_AVAILABLE = True
    print(f"✓ Cloud Storage conectado al bucket: {GCS_BUCKET_NAME}")
except Exception as e:
    print(f"⚠ Cloud Storage no disponible: {e}")
    GCS_AVAILABLE = False
    bucket = None

# ==========================================
# ⚙️ CONFIG - Oracle V7.2
# ==========================================
CONFIG = {
    "MAX_WORKERS": 12,
    "MIN_ROIC": 0.08,

    # ✅ Piotroski REAL (0-9)
    "MIN_PIOTROSKI": 6,        # 6 = ok, 7 = fuerte, 8+ excelente
    "MIN_PIO_COVERAGE": 7,     # mínimo señales evaluadas (de 9)

    "DISCOUNT_RATE": 0.09,
    "MARGIN_OF_SAFETY_VIEW": -0.20
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

def log(msg):
    print(msg)
    sys.stdout.flush()

# -------- Funciones de Caché con Cloud Storage --------
def get_cached_results():
    """Intenta obtener resultados del caché en Cloud Storage"""
    if not GCS_AVAILABLE:
        log("⚠ Cloud Storage no disponible, ejecutando sin caché")
        return None
    
    try:
        blob = bucket.blob(CACHE_FILE_NAME)
        
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
        
        if time_diff < timedelta(hours=CACHE_TTL_HOURS):
            hours_ago = round(time_diff.total_seconds() / 3600, 1)
            log(f"✓ Usando datos del caché (generados hace {hours_ago} horas)")
            return data["results"]
        else:
            log(f"⚠ Caché expirado (más de {CACHE_TTL_HOURS}h), regenerando datos...")
            blob.delete()
            return None
            
    except Exception as e:
        log(f"⚠ Error leyendo caché: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_full_cached_data():
    """
    Obtiene el objeto completo del caché (no solo results)
    Usado por /refine para tener acceso a todos los datos del análisis
    """
    if not GCS_AVAILABLE:
        return None
    
    try:
        blob = bucket.blob(CACHE_FILE_NAME)
        
        if not blob.exists():
            return None
        
        cache_content = blob.download_as_string()
        data = json.loads(cache_content)
        
        if "results" not in data or "cached_at" not in data:
            blob.delete()
            return None
        
        cache_time = datetime.fromisoformat(data.get("cached_at", ""))
        time_diff = datetime.now() - cache_time
        
        if time_diff < timedelta(hours=CACHE_TTL_HOURS):
            # Retornar el objeto completo con metadata
            return data["results"]
        else:
            blob.delete()
            return None
            
    except Exception as e:
        return None

def save_to_cache(results):
    """Guarda resultados en Cloud Storage"""
    if not GCS_AVAILABLE:
        log("⚠ Cloud Storage no disponible, no se guardará caché")
        return False
    
    try:
        cache_data = {
            "results": results,
            "cached_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=CACHE_TTL_HOURS)).isoformat()
        }
        
        blob = bucket.blob(CACHE_FILE_NAME)
        json_string = json.dumps(cache_data, default=str, allow_nan=False)
        json_string = json_string.replace('NaN', 'null').replace('Infinity', 'null').replace('-Infinity', 'null')
        
        blob.upload_from_string(json_string, content_type='application/json')
        log(f"✓ Resultados guardados en caché por {CACHE_TTL_HOURS} horas")
        return True
        
    except Exception as e:
        log(f"⚠ Error guardando en caché: {e}")
        import traceback
        traceback.print_exc()
        return False

# ==========================================
# 1. UNIVERSO INDESTRUCTIBLE (CSV + HARDCODE)
# ==========================================
def get_bulletproof_universe():
    tickers = set()
    print("🌍 Generando Universo...")

    # Intento 1: GitHub API (más confiable que raw)
    try:
        # Usando GitHub API en lugar de raw.githubusercontent.com
        url_sp500 = "https://api.github.com/repos/datasets/s-and-p-500-companies/contents/data/constituents.csv"
        headers = {'Accept': 'application/vnd.github.v3.raw'}
        r = requests.get(url_sp500, headers=headers, timeout=30)
        r.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(r.text))
        tickers.update(df['Symbol'].tolist())
        print(f"   -> S&P 500 cargado desde GitHub API ({len(tickers)})")
    except Exception as e:
        print(f"   ⚠️ Fallo GitHub S&P 500: {str(e)}")
        
        # Fallback: Intentar con raw.githubusercontent.com
        try:
            url_sp500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
            df = pd.read_csv(url_sp500, timeout=30)
            tickers.update(df['Symbol'].tolist())
            print(f"   -> S&P 500 cargado desde GitHub raw ({len(tickers)})")
        except Exception as e2:
            print(f"   ⚠️ Fallo GitHub raw: {str(e2)}")

    # Intento 2: Nasdaq 100
    try:
        url_ndx = "https://api.github.com/repos/nasdaq-100/nasdaq-100-symbols/contents/nasdaq-100-symbols.csv"
        headers = {'Accept': 'application/vnd.github.v3.raw'}
        r = requests.get(url_ndx, headers=headers, timeout=30)
        if r.status_code == 200:
            text = r.text
            lines = text.split('\n')
            nasdaq_ticks = [x.split(',')[0].strip() for x in lines if x and 'Symbol' not in x]
            tickers.update(nasdaq_ticks)
            print(f"   -> Nasdaq cargado ({len(nasdaq_ticks)})")
    except Exception as e:
        print(f"   ⚠️ Fallo GitHub Nasdaq: {str(e)}")

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
        print("⚠️ Fallaron descargas externas. Usando Lista de Respaldo Manual.")
        tickers.update(BACKUP_LIST)

    final_list = list(set([t.replace(".", "-") for t in tickers]))
    return final_list[:500]

# ==========================================
# 2. MOTOR DE BÚSQUEDA FUZZY (V5 Core)
# ==========================================
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


# ==========================================
# 3. SAFE FLOAT Y UTILIDADES (Oracle V7.2)
# ==========================================
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

# ==========================================
# 4. REAL PIOTROSKI (0–9) + COVERAGE (Oracle V7.2)
# ==========================================
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

# ==========================================
# 5. ANÁLISIS FINANCIERO (Oracle V7.2)
# ==========================================
def analyze_stock_v7(ticker):
    """Analiza una acción individual con Oracle V7.2"""
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

        debt_to_mcap = (curr_debt / market_cap) if (market_cap > 0) else np.nan
        fcf_yield = (fcf / market_cap) if (market_cap > 0 and not np.isnan(fcf)) else np.nan

        return {
            "Ticker": ticker,
            "Price": round(price, 2),
            "Sector": sector,
            "ROIC": roic,
            "Piotroski": piotroski,
            "Piotroski_Coverage": pio_cov,
            "Growth_Est": growth_proxy,
            "Terminal_g": terminal_g,
            "Intrinsic": intrinsic,
            "MOS": mos,
            "FCF": fcf,
            "OCF": ocf_val,
            "Capex": cpx_val,
            "Debt": curr_debt,
            "Cash": curr_cash,
            "Equity": curr_eq,
            "InvestedCap": invested_cap,
            "Shares": shares,
            "MarketCap": market_cap,
            "Debt_to_MCap": debt_to_mcap,
            "FCF_Yield": fcf_yield,
            "DCF_TV_Weight": tv_weight
        }

    except Exception:
        return None

# ==========================================
# 6. FUNCIÓN PRINCIPAL DE ANÁLISIS
# ==========================================
def run_analysis():
    """Ejecuta el análisis completo con caché"""
    
    # Verificar caché primero
    cached = get_cached_results()
    if cached is not None:
        cached['from_cache'] = True
        return cached
    
    # Si no hay caché, ejecutar análisis
    start_time = time.time()
    
    log("🎯 Iniciando Warren Screener v8")
    log("="*60)
    
    # 1. Obtener universo
    tickers = get_bulletproof_universe()
    log(f"🎯 Objetivo Real: Analizar {len(tickers)} empresas.")
    
    # 2. Análisis paralelo
    results = []
    with ThreadPoolExecutor(max_workers=CONFIG['MAX_WORKERS']) as executor:
        futures = {executor.submit(analyze_stock_v7, t): t for t in tickers}
        for future in as_completed(futures):
            r = future.result()
            if r: results.append(r)
    
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
        "results": all_results,  # TODOS los resultados, ordenados por MOS descendente
        "summary": {
            "buy_zone_count": len(buy_candidates),      # MOS > 10%
            "fair_zone_count": len(fair_value),         # MOS 0-10%
            "watch_zone_count": len(watchlist)          # MOS < 0%
        },
        "generated_at": datetime.now().isoformat(),
        "cache_enabled": GCS_AVAILABLE,
        "from_cache": False,
        "execution_time_seconds": execution_time
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
    save_to_cache(result)
    
    return result

# -------- Flask App --------
app = Flask(__name__)

@app.route('/')
def home():
    """Página principal con información del servicio"""
    cache_status = "enabled" if GCS_AVAILABLE else "disabled"
    return jsonify({
        "status": "Warren Screener v8 - DCF 2-Stage + Quality Focus",
        "version": "8.0 - Oracle V7.2 Integration",
        "cache": cache_status,
        "bucket": GCS_BUCKET_NAME if GCS_AVAILABLE else "not configured",
        "cache_ttl_hours": CACHE_TTL_HOURS,
        "methodology": [
            "ROIC mínimo 8% (retorno sobre capital invertido)",
            "Piotroski Score >= 6 (calidad financiera REAL con 9 señales)",
            "DCF 2-Stage con tasa de descuento 9%",
            "Growth estimado basado en ROIC",
            "Terminal growth ajustado por sector",
            "Margen de seguridad calculado vs precio actual"
        ],
        "filters": {
            "min_market_cap": "5B USD",
            "min_roic": f"{CONFIG['MIN_ROIC']*100}%",
            "min_piotroski": CONFIG['MIN_PIOTROSKI'],
            "min_pio_coverage": CONFIG['MIN_PIO_COVERAGE'],
            "discount_rate": f"{CONFIG['DISCOUNT_RATE']*100}%"
        },
        "endpoints": {
            "/analyze": "Run analysis (with 24h cache + auto post-processing)",
            "/refine": "GET - Analyst AI V7: Portfolio Analysis + Exit Plan (6M/12M targets)",
            "/follow": "POST - Portfolio Performance Tracker (analyze your portfolio)",
            "/post-process": "POST - Manual post-processing of results",
            "/cache-status": "Check cache status",
            "/clear-cache": "Clear cache manually",
            "/health": "Health check"
        },
        "features": {
            "auto_post_processing": POST_PROCESSOR_AVAILABLE,
            "portfolio_refinement": PORTFOLIO_REFINER_AVAILABLE,
            "portfolio_tracking": PORTFOLIO_TRACKER_AVAILABLE,
            "sector_analysis": POST_PROCESSOR_AVAILABLE,
            "portfolio_metrics": POST_PROCESSOR_AVAILABLE,
            "smart_alerts": POST_PROCESSOR_AVAILABLE
        }
    })

@app.route('/analyze')
def analyze():
    """Endpoint principal de análisis"""
    try:
        log("\n" + "="*60)
        log("📊 Nueva petición de análisis recibida")
        log("="*60)
        
        results = run_analysis()
        
        # Post-procesamiento automático
        if POST_PROCESSOR_AVAILABLE and results.get('candidates_count', 0) > 0:
            try:
                log("🔄 Ejecutando post-procesamiento...")
                processor = ResultsPostProcessor(results)
                processed_data = processor.process_all()
                
                # Agregar datos procesados a la respuesta
                results['post_processed'] = processed_data
                log("✅ Post-procesamiento completado")
            except Exception as e:
                log(f"⚠️  Error en post-procesamiento: {e}")
                results['post_processed'] = None
        
        response = app.response_class(
            response=json.dumps(results, default=str, allow_nan=False)
                     .replace('NaN', 'null')
                     .replace('Infinity', 'null')
                     .replace('-Infinity', 'null'),
            status=200,
            mimetype='application/json'
        )
        return response
        
    except Exception as e:
        log(f"❌ Error en análisis: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/cache-status')
def cache_status():
    """Verifica el estado del caché"""
    if not GCS_AVAILABLE:
        return jsonify({
            "cache_enabled": False,
            "message": "Cloud Storage not available"
        })
    
    try:
        blob = bucket.blob(CACHE_FILE_NAME)
        
        if not blob.exists():
            return jsonify({
                "cache_enabled": True,
                "cache_exists": False,
                "message": "No cached data available"
            })
        
        cache_content = blob.download_as_string()
        data = json.loads(cache_content)
        
        cache_time = datetime.fromisoformat(data.get("cached_at", ""))
        expires_at = datetime.fromisoformat(data.get("expires_at", ""))
        time_remaining = expires_at - datetime.now()
        
        is_expired = time_remaining.total_seconds() <= 0
        
        return jsonify({
            "cache_enabled": True,
            "cache_exists": True,
            "is_expired": is_expired,
            "cached_at": cache_time.isoformat(),
            "expires_at": expires_at.isoformat(),
            "time_remaining_hours": round(time_remaining.total_seconds() / 3600, 2),
            "results_count": data["results"].get("total_analyzed", 0),
            "candidates_count": data["results"].get("candidates_count", 0),
            "file_size_kb": round(blob.size / 1024, 2)
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/clear-cache')
def clear_cache():
    """Limpia el caché manualmente"""
    if not GCS_AVAILABLE:
        return jsonify({"status": "Cloud Storage not available"}), 503
    
    try:
        blob = bucket.blob(CACHE_FILE_NAME)
        if blob.exists():
            blob.delete()
            log("🗑️ Caché limpiado manualmente")
            return jsonify({
                "status": "success",
                "message": "Cache cleared successfully"
            })
        else:
            return jsonify({
                "status": "success",
                "message": "No cache to clear"
            })
    except Exception as e:
        log(f"❌ Error limpiando caché: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache_available": GCS_AVAILABLE,
        "post_processor_available": POST_PROCESSOR_AVAILABLE,
        "portfolio_refiner_available": PORTFOLIO_REFINER_AVAILABLE,
        "portfolio_tracker_available": PORTFOLIO_TRACKER_AVAILABLE,
        "version": "8.0 - Oracle V7.2 + Analyst AI V7 Integration"
    })

@app.route('/post-process', methods=['POST'])
def post_process_endpoint():
    """
    Endpoint para post-procesar resultados manualmente
    Acepta JSON con los resultados del análisis
    """
    if not POST_PROCESSOR_AVAILABLE:
        return jsonify({
            "error": "Post-processor not available"
        }), 503
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "error": "No data provided"
            }), 400
        
        log("🔄 Post-procesando datos recibidos...")
        processor = ResultsPostProcessor(data)
        processed_data = processor.process_all()
        
        return jsonify({
            "status": "success",
            "processed_data": processed_data,
            "processed_at": datetime.now().isoformat()
        })
        
    except Exception as e:
        log(f"❌ Error en post-procesamiento: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/follow', methods=['POST'])
def follow_endpoint():
    """
    Endpoint para Portfolio Tracking
    Recibe tickers, start_date e initial_capital
    Retorna análisis de rendimiento del portfolio
    
    Body JSON:
    {
        "tickers": ["AAPL", "MSFT", "GOOGL"],
        "start_date": "2024-01-01",
        "initial_capital": 10000
    }
    """
    if not PORTFOLIO_TRACKER_AVAILABLE:
        return jsonify({
            "error": "Portfolio Tracker not available"
        }), 503
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "error": "No data provided"
            }), 400
        
        # Validar campos requeridos
        required_fields = ['tickers', 'start_date', 'initial_capital']
        missing = [f for f in required_fields if f not in data]
        
        if missing:
            return jsonify({
                "error": f"Missing required fields: {', '.join(missing)}"
            }), 400
        
        tickers = data['tickers']
        start_date = data['start_date']
        initial_capital = data['initial_capital']
        
        # Validaciones
        if not isinstance(tickers, list) or len(tickers) == 0:
            return jsonify({
                "error": "tickers must be a non-empty list"
            }), 400
        
        if not isinstance(initial_capital, (int, float)) or initial_capital <= 0:
            return jsonify({
                "error": "initial_capital must be a positive number"
            }), 400
        
        # Validar formato de fecha
        try:
            datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            return jsonify({
                "error": "start_date must be in YYYY-MM-DD format"
            }), 400
        
        log("\n" + "="*60)
        log("📊 Portfolio Tracking Request")
        log("="*60)
        log(f"Tickers: {', '.join(tickers)}")
        log(f"Start Date: {start_date}")
        log(f"Initial Capital: ${initial_capital:,.2f}")
        
        # Ejecutar tracking
        tracker = PortfolioTracker(tickers, start_date, initial_capital)
        result = tracker.analyze()
        
        if result is None:
            return jsonify({
                "error": "Failed to analyze portfolio. Check if tickers are valid and dates have available data."
            }), 500
        
        log("✅ Portfolio tracking completado")
        log("="*60)
        
        return jsonify({
            "status": "success",
            "analysis": result,
            "analyzed_at": datetime.now().isoformat()
        })
        
    except Exception as e:
        log(f"❌ Error en portfolio tracking: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ==========================================
# 7. ANALYST AI V7 (Analyst + Exit Plan)
# ==========================================
def analyst_ai_v37(df_input: pd.DataFrame, return_all: bool = False) -> pd.DataFrame:
    """
    Selecciona SOLO oportunidades de alta convicción ("JOYAS"),
    con gates estrictos y lógica anti-trampas (especialmente DEFENSIVE).

    - No usa Top N. Pasa/falla por umbrales.
    - Por defecto devuelve SOLO STRONG BUY / BUY.
    - return_all=True devuelve WATCH/AVOID también.
    """

    required_cols = [
        "Ticker","Price","Sector","ROIC","Piotroski","Growth_Est","Terminal_g",
        "Intrinsic","MOS","FCF","Debt","Cash","MarketCap","Debt_to_MCap","FCF_Yield","DCF_TV_Weight"
    ]
    missing = [c for c in required_cols if c not in df_input.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas en el df de entrada: {missing}")

    df = df_input.copy()

    # Normalización numérica
    num_cols = [
        "Price","ROIC","Piotroski","Growth_Est","Terminal_g","Intrinsic","MOS",
        "FCF","Debt","Cash","MarketCap","Debt_to_MCap","FCF_Yield","DCF_TV_Weight"
    ]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], np.nan)

    df["Sector"] = df["Sector"].fillna("N/A").astype(str)
    df["Ticker"] = df["Ticker"].astype(str)

    # Buckets sectoriales
    DEFENSIVE = {"Consumer Defensive","Utilities","Healthcare"}
    CYCLICAL  = {"Consumer Cyclical","Industrials","Basic Materials","Energy","Real Estate"}
    GROWTH    = {"Technology","Communication Services"}

    def sector_bucket(sector: str) -> str:
        if sector in DEFENSIVE: return "DEFENSIVE"
        if sector in CYCLICAL:  return "CYCLICAL"
        if sector in GROWTH:    return "GROWTH"
        return "OTHER"

    # Dedup por issuer (clases)
    def issuer_key(ticker: str) -> str:
        t = ticker.upper()
        for suf in ["-A","-B","-C",".A",".B",".C"]:
            if t.endswith(suf):
                t = t[: -len(suf)]
        if t in {"FOXA","FOX"}: return "FOX"
        if t in {"GOOGL","GOOG"}: return "GOOG"
        return t

    # Config institucional (estricta)
    CFG = {
        "MIN_PIO_BUY": 6,
        "MIN_PIO_STRONG": 7,
        "MIN_ROIC_BUY": 0.10,
        "MIN_ROIC_STRONG": 0.12,

        "MAX_TVW_BUY": 0.80,
        "MAX_TVW_STRONG": 0.77,

        "MAX_DTM_BUY": 1.0,
        "MAX_DTM_STRONG": 0.9,

        "MOS_BUY":    {"DEFENSIVE":0.36, "CYCLICAL":0.34, "GROWTH":0.30, "OTHER":0.32},
        "MOS_STRONG": {"DEFENSIVE":0.44, "CYCLICAL":0.42, "GROWTH":0.38, "OTHER":0.40},

        "FCFY_BUY":    {"DEFENSIVE":0.085, "CYCLICAL":0.055, "GROWTH":0.045, "OTHER":0.055},
        "FCFY_STRONG": {"DEFENSIVE":0.100, "CYCLICAL":0.065, "GROWTH":0.055, "OTHER":0.065},

        "UP_BUY": 0.55,
        "UP_STRONG": 0.85,

        "DEF_MAX_GROWTH_EST": 0.10,
        "REQUIRE_POSITIVE_FCF": True,
    }

    def mos_penalty(dtm, tvw):
        pen = 0.0
        if not pd.isna(dtm):
            if dtm >= 1.2: pen += 0.06
            elif dtm >= 1.0: pen += 0.03
        if not pd.isna(tvw):
            if tvw >= 0.85: pen += 0.07
            elif tvw >= 0.80: pen += 0.04
        return pen

    out = []
    for _, r in df.iterrows():
        ticker = r["Ticker"]
        sector = r["Sector"]
        bucket = sector_bucket(sector)

        price = r["Price"]
        fair  = r["Intrinsic"]  # ← fair value DCF

        roic = r["ROIC"]
        pio  = r["Piotroski"]
        fcf  = r["FCF"]
        fcfy = r["FCF_Yield"]
        dtm  = r["Debt_to_MCap"]
        tvw  = r["DCF_TV_Weight"]
        g_est = r["Growth_Est"]
        t_g   = r["Terminal_g"]

        # Financieras fuera de DCF
        if sector == "Financial Services":
            if return_all:
                out.append({
                    "Ticker": ticker, "Issuer": issuer_key(ticker), "Sector": sector, "Bucket": bucket,
                    "Price": price, "Target_Fair": np.nan, "Upside": np.nan, "Real_MOS": np.nan,
                    "Action": "VALUAR P/B", "Cat": "🏦 Banco/Seguro",
                    "Flags": "DCF_NA",
                    "Why": "Bancos/seguros: usar P/B + ROE + calidad de balance.",
                    "DCF_TV_Weight": tvw, "Debt_to_MCap": dtm, "FCF_Yield": fcfy, "Piotroski": pio, "ROIC": roic
                })
            continue

        # sanity
        if pd.isna(price) or pd.isna(fair) or price <= 0 or fair <= 0:
            continue

        upside = (fair - price) / price
        real_mos = (fair - price) / fair

        flags, why = [], []

        # FCF positivo obligatorio
        fcf_ok = (not pd.isna(fcf)) and (fcf > 0)
        if CFG["REQUIRE_POSITIVE_FCF"] and (not fcf_ok):
            flags.append("FCF_NEG")

        mos_req_buy    = CFG["MOS_BUY"][bucket]    + mos_penalty(dtm, tvw)
        mos_req_strong = CFG["MOS_STRONG"][bucket] + mos_penalty(dtm, tvw)

        fcfy_req_buy    = CFG["FCFY_BUY"][bucket]
        fcfy_req_strong = CFG["FCFY_STRONG"][bucket]

        # Anti-trampa defensivos
        defensive_trap = False
        if bucket == "DEFENSIVE":
            if (not pd.isna(g_est)) and (g_est > CFG["DEF_MAX_GROWTH_EST"]):
                defensive_trap = True
                flags.append("DEF_GROWTH_IMPLAUSIBLE")
            if (not pd.isna(pio)) and (pio <= 5):
                defensive_trap = True
                flags.append("DEF_LOW_PIO")
            if (pd.isna(fcfy)) or (fcfy < fcfy_req_buy):
                flags.append("DEF_FCFY_LOW")

        # Fragilidad DCF
        if (not pd.isna(tvw)) and (tvw > 0.85):
            flags.append("TV_HEAVY")

        base_ok_buy = (
            (not pd.isna(pio)) and (pio >= CFG["MIN_PIO_BUY"]) and
            (not pd.isna(roic)) and (roic >= CFG["MIN_ROIC_BUY"]) and
            (not pd.isna(fcfy)) and (fcfy >= fcfy_req_buy) and
            (not pd.isna(dtm)) and (dtm <= CFG["MAX_DTM_BUY"]) and
            (not pd.isna(tvw)) and (tvw <= CFG["MAX_TVW_BUY"]) and
            fcf_ok and
            (real_mos >= mos_req_buy) and
            (upside >= CFG["UP_BUY"]) and
            (not defensive_trap)
        )

        base_ok_strong = (
            (not pd.isna(pio)) and (pio >= CFG["MIN_PIO_STRONG"]) and
            (not pd.isna(roic)) and (roic >= CFG["MIN_ROIC_STRONG"]) and
            (not pd.isna(fcfy)) and (fcfy >= fcfy_req_strong) and
            (not pd.isna(dtm)) and (dtm <= CFG["MAX_DTM_STRONG"]) and
            (not pd.isna(tvw)) and (tvw <= CFG["MAX_TVW_STRONG"]) and
            fcf_ok and
            (real_mos >= mos_req_strong) and
            (upside >= CFG["UP_STRONG"]) and
            (not defensive_trap)
        )

        action, cat = "AVOID", "❌ No pasa filtros"
        if base_ok_strong:
            action, cat = "STRONG BUY", "💎 JOYA REAL"
            why.append("Pasa gates estrictos (calidad + robustez + riesgo controlado).")
        elif base_ok_buy:
            action, cat = "BUY", "✅ Oportunidad"
            why.append("Pasa gates institucionales (MOS/FCFY + riesgo controlado).")
        else:
            if (real_mos >= 0.18) and (upside >= 0.30):
                action, cat = "WATCH", "⚖️ Casi, pero no"
                why.append("Hay descuento, pero no alcanza robustez/calidad/riesgo para compra.")

        if (not return_all) and (action not in {"STRONG BUY","BUY"}):
            continue

        out.append({
            "Ticker": ticker,
            "Issuer": issuer_key(ticker),
            "Sector": sector,
            "Bucket": bucket,
            "Price": price,
            "Target_Fair": fair,
            "Upside": upside,
            "Real_MOS": real_mos,
            "Piotroski": pio,
            "ROIC": roic,
            "FCF_Yield": fcfy,
            "Debt_to_MCap": dtm,
            "DCF_TV_Weight": tvw,
            "Growth_Est": g_est,
            "Terminal_g": t_g,
            "Action": action,
            "Cat": cat,
            "Flags": ",".join(sorted(set(flags))),
            "Why": " ".join(why) if why else ""
        })

    res = pd.DataFrame(out)
    if res.empty:
        return res

    # Dedup por issuer: mejor acción, luego upside
    action_rank = {"STRONG BUY": 0, "BUY": 1, "WATCH": 2, "AVOID": 3, "VALUAR P/B": 4}
    res["_ar"] = res["Action"].map(action_rank).fillna(99)
    res = res.sort_values(by=["_ar","Upside"], ascending=[True, False])
    res = res.drop_duplicates(subset=["Issuer"], keep="first").drop(columns=["_ar"])

    # Orden final
    res["_ar2"] = res["Action"].map(action_rank).fillna(99)
    res = res.sort_values(by=["_ar2","Upside"], ascending=[True, False]).drop(columns=["_ar2"])

    return res

def add_exit_plan(df_rec: pd.DataFrame) -> pd.DataFrame:
    """
    Construye targets de salida realistas (6m y 12m) usando convergencia parcial al fair value,
    penalizando fragilidad del DCF (TV weight alto). Agrega trim y stop.
    """
    if df_rec is None or df_rec.empty:
        return df_rec

    dfp = df_rec.copy()

    price = pd.to_numeric(dfp["Price"], errors="coerce")
    fair  = pd.to_numeric(dfp["Target_Fair"], errors="coerce")
    tvw   = pd.to_numeric(dfp["DCF_TV_Weight"], errors="coerce")

    # Penalización por TV weight (fragilidad del fair)
    # (mientras más TVW, más conservador el target)
    tv_penalty = np.where(tvw >= 0.78, 0.90, np.where(tvw >= 0.74, 0.95, 1.00))
    dfp["TV_Penalty"] = tv_penalty

    gap = (fair - price).clip(lower=0)

    # Convergencia parcial por horizonte y tipo de acción
    # 6m: más conservador
    conv6 = np.where(dfp["Action"].eq("STRONG BUY"), 0.60,
            np.where(dfp["Action"].eq("BUY"),        0.45, 0.40))
    # 12m: más "tesis"
    conv12 = np.where(dfp["Action"].eq("STRONG BUY"), 0.80,
             np.where(dfp["Action"].eq("BUY"),        0.65, 0.55))

    dfp["Conv_6M"] = conv6
    dfp["Conv_12M"] = conv12

    # Targets base
    tgt6  = price + gap * dfp["Conv_6M"]  * dfp["TV_Penalty"]
    tgt12 = price + gap * dfp["Conv_12M"] * dfp["TV_Penalty"]

    # Caps de upside para no pedir imposibles (operativo)
    cap6  = np.where(dfp["Action"].eq("STRONG BUY"), 1.20, 0.90)  # 120% vs 90%
    cap12 = np.where(dfp["Action"].eq("STRONG BUY"), 1.80, 1.40)  # 180% vs 140%

    dfp["Target_6M"]  = np.minimum(tgt6,  price * (1 + cap6))
    dfp["Target_12M"] = np.minimum(tgt12, price * (1 + cap12))

    dfp["Upside_6M"]  = (dfp["Target_6M"]  - price) / price
    dfp["Upside_12M"] = (dfp["Target_12M"] - price) / price

    # Trim y Stop (simple sin ATR)
    # Trim_6M: toma parcial al 70% del camino al Target_6M
    dfp["Trim_6M"] = price + (dfp["Target_6M"] - price) * 0.70

    # Stop: STRONG -12%, BUY -10%
    stop_pct = np.where(dfp["Action"].eq("STRONG BUY"), 0.12, 0.10)
    dfp["Stop_Price"] = price * (1 - stop_pct)

    return dfp

@app.route('/refine', methods=['GET'])
def refine_endpoint():
    """
    Endpoint para Analyst AI V7 - Portfolio Analysis + Exit Plan
    Toma los datos del último análisis (caché o ejecuta nuevo) y aplica análisis avanzado
    """
    
    try:
        log("\n" + "="*60)
        log("🧠 Analyst AI V7 - Portfolio Analysis + Exit Plan")
        log("="*60)
        
        # 1. Intentar obtener datos del caché primero
        log("📂 Buscando datos en caché...")
        cached_data = get_full_cached_data()
        
        if cached_data:
            log("✅ Datos encontrados en caché")
            data = cached_data
        else:
            # 2. Si no hay caché, ejecutar análisis nuevo
            log("⚠️  No hay caché, ejecutando análisis nuevo...")
            data = run_analysis()
        
        # 3. Verificar que tenemos resultados
        if not data:
            log("❌ No hay resultados para analizar")
            return jsonify({
                "error": "No analysis results available. Run /analyze first."
            }), 404
        
        # 4. Verificar formato de datos y extraer results
        if isinstance(data, list):
            results_list = data
        elif isinstance(data, dict) and 'results' in data:
            results_list = data['results']
        else:
            log("❌ Formato de datos inválido")
            return jsonify({
                "error": "Invalid data format"
            }), 500
        
        if not results_list:
            log("❌ Lista de resultados vacía")
            return jsonify({
                "error": "No results to analyze"
            }), 404
        
        # 5. Convertir a DataFrame para Analyst AI
        log(f"🔍 Analizando {len(results_list)} candidatos con Analyst AI V7...")
        df_input = pd.DataFrame(results_list)
        
        # 6. Aplicar Analyst AI V7 (solo JOYAS)
        df_analyzed = analyst_ai_v37(df_input, return_all=False)
        
        if df_analyzed.empty:
            log("⚠️  No se encontraron JOYAS (STRONG BUY/BUY)")
            # Retornar estructura vacía pero válida
            return jsonify({
                "status": "success",
                "refined_data": {
                    "joyas": [],
                    "summary": {
                        "total_candidates": len(results_list),
                        "strong_buy_count": 0,
                        "buy_count": 0,
                        "total_joyas": 0
                    },
                    "methodology": "Analyst AI V7 - Institutional Grade Selection"
                },
                "refined_at": datetime.now().isoformat(),
                "original_analysis": {
                    "generated_at": data.get('generated_at') if isinstance(data, dict) else None,
                    "total_analyzed": data.get('total_analyzed') if isinstance(data, dict) else len(results_list),
                    "candidates_count": len(results_list),
                    "from_cache": data.get('from_cache', False) if isinstance(data, dict) else False
                }
            })
        
        # 7. Agregar Exit Plan (Targets 6M/12M + Trim/Stop)
        df_final = add_exit_plan(df_analyzed)
        
        # 8. Convertir a diccionarios para JSON (con manejo de NaN/Inf)
        joyas_list = df_final.replace({np.nan: None, np.inf: None, -np.inf: None}).to_dict('records')
        
        # 9. Calcular métricas de resumen
        strong_buy_count = len(df_final[df_final['Action'] == 'STRONG BUY'])
        buy_count = len(df_final[df_final['Action'] == 'BUY'])
        
        log(f"✅ Análisis completado: {len(joyas_list)} JOYAS encontradas")
        log(f"   💎 STRONG BUY: {strong_buy_count}")
        log(f"   ✅ BUY: {buy_count}")
        log("="*60)
        
        # 10. Preparar respuesta estructurada
        refined_data = {
            "joyas": joyas_list,
            "summary": {
                "total_candidates": len(results_list),
                "strong_buy_count": strong_buy_count,
                "buy_count": buy_count,
                "total_joyas": len(joyas_list)
            },
            "methodology": {
                "name": "Analyst AI V7 - Institutional Grade Selection",
                "description": "Filtros estrictos de calidad, robustez y riesgo controlado",
                "gates": {
                    "min_piotroski_buy": 6,
                    "min_piotroski_strong": 7,
                    "min_roic_buy": "10%",
                    "min_roic_strong": "12%",
                    "max_tv_weight_buy": "80%",
                    "max_tv_weight_strong": "77%",
                    "max_debt_to_mcap_buy": 1.0,
                    "max_debt_to_mcap_strong": 0.9,
                    "require_positive_fcf": True
                },
                "exit_plan": {
                    "target_6m": "Conservative convergence to fair value (40-60%)",
                    "target_12m": "Thesis convergence to fair value (55-80%)",
                    "trim_6m": "70% of the way to 6M target",
                    "stop_loss": "STRONG BUY: -12%, BUY: -10%"
                }
            }
        }
        
        response_data = {
            "status": "success",
            "refined_data": refined_data,
            "refined_at": datetime.now().isoformat(),
            "original_analysis": {
                "generated_at": data.get('generated_at') if isinstance(data, dict) else None,
                "total_analyzed": data.get('total_analyzed') if isinstance(data, dict) else len(results_list),
                "candidates_count": len(results_list),
                "from_cache": data.get('from_cache', False) if isinstance(data, dict) else False
            }
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        log(f"❌ Error en Analyst AI: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    log(f"🚀 Iniciando Warren Screener v8 - Oracle V7.2 + Analyst AI V7 en puerto {port}")
    log(f"📦 Metodología: Oracle V7.2 (DCF 2-Stage + ROIC + Piotroski Real)")
    log(f"🧠 Analyst AI: Institutional Grade Selection + Exit Plan")
    log(f"💾 Cache: {'Enabled' if GCS_AVAILABLE else 'Disabled'}")
    if GCS_AVAILABLE:
        log(f"🪣 Bucket: {GCS_BUCKET_NAME}")
    app.run(host="0.0.0.0", port=port)
