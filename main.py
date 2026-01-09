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
# 1) UNIVERSO - Oracle V7.2
# ==========================================
def get_bulletproof_universe():
    tickers = set()
    print("🌍 Generando Universo...")

    try:
        url_sp500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
        df = pd.read_csv(url_sp500)
        tickers.update(df["Symbol"].tolist())
        print(f"   -> S&P 500 cargado desde GitHub ({len(tickers)})")
    except:
        print("   ⚠️ Fallo GitHub S&P 500.")

    try:
        url_ndx = "https://raw.githubusercontent.com/nasdaq-100/nasdaq-100-symbols/master/nasdaq-100-symbols.csv"
        r = requests.get(url_ndx, timeout=15)
        lines = r.text.split("\n")
        nasdaq_ticks = [x.split(",")[0].strip() for x in lines if x and "Symbol" not in x]
        tickers.update(nasdaq_ticks)
        print(f"   -> Nasdaq cargado ({len(nasdaq_ticks)})")
    except:
        print("   ⚠️ Fallo GitHub Nasdaq.")

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
# 2) FUZZY SERIES - Oracle V7.2
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

# ==========================================
# 3) REAL PIOTROSKI (0–9) + COVERAGE - Oracle V7.2
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
# 4) ANALYZE STOCK (V7.2) - Oracle V7.2
# ==========================================
def analyze_stock_v72(ticker: str):
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
            "Price": price,
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
# 5) RUN ANALYSIS - Oracle V7.2
# ==========================================
def run_analysis():
    """
    Ejecuta el análisis completo usando Oracle V7.2
    Retorna estructura compatible con el formato original
    """
    tickers = get_bulletproof_universe()
    log(f"🎯 Objetivo Real: Analizar {len(tickers)} empresas.")

    results = []
    with ThreadPoolExecutor(max_workers=CONFIG["MAX_WORKERS"]) as executor:
        futures = {executor.submit(analyze_stock_v72, tk): tk for tk in tickers}
        for future in tqdm(as_completed(futures), total=len(tickers), desc="Analizando"):
            r = future.result()
            if r:
                results.append(r)

    log(f"\n💎 RESULTADOS FINALES ({len(results)} encontrados)")
    
    # Estructura de retorno compatible
    return {
        "results": results,
        "total_analyzed": len(tickers),
        "candidates_count": len(results),
        "generated_at": datetime.now().isoformat(),
        "from_cache": False
    }

# ==========================================
# 6) FLASK APP
# ==========================================
app = Flask(__name__)

@app.route('/analyze')
def analyze():
    """
    Endpoint principal de análisis usando Oracle V7.2
    Primero busca en caché, si no ejecuta análisis nuevo
    """
    try:
        log("\n" + "="*60)
        log("🔍 Warren Screener - Análisis de Calidad")
        log("="*60)
        
        # 1. Intentar obtener del caché
        cached = get_cached_results()
        
        if cached:
            log("✅ Retornando resultados desde caché")
            
            # Si cached es un dict con 'results', retornar completo
            if isinstance(cached, dict) and 'results' in cached:
                response_data = cached
                response_data['from_cache'] = True
            # Si cached es una lista, construir el objeto
            elif isinstance(cached, list):
                response_data = {
                    "results": cached,
                    "candidates_count": len(cached),
                    "from_cache": True,
                    "generated_at": datetime.now().isoformat()
                }
            else:
                response_data = cached
                
            return jsonify(response_data)
        
        # 2. Si no hay caché, ejecutar análisis
        log("⚠️ No hay caché válido, ejecutando análisis completo...")
        log("="*60)
        
        analysis_result = run_analysis()
        
        if not analysis_result or not analysis_result.get('results'):
            log("❌ No se encontraron resultados")
            return jsonify({
                "error": "No candidates found matching criteria",
                "total_analyzed": analysis_result.get('total_analyzed', 0) if analysis_result else 0,
                "candidates_count": 0
            }), 404
        
        # 3. Guardar en caché
        save_to_cache(analysis_result)
        
        # 4. Post-procesar si está disponible
        if POST_PROCESSOR_AVAILABLE:
            try:
                log("🔄 Post-procesando resultados...")
                processor = ResultsPostProcessor(analysis_result)
                processed_data = processor.process_all()
                analysis_result['processed'] = processed_data
                log("✅ Post-procesamiento completado")
            except Exception as e:
                log(f"⚠️ Error en post-procesamiento: {e}")
        
        log("="*60)
        log(f"✅ Análisis completado: {analysis_result['candidates_count']} candidatos encontrados")
        log("="*60)
        
        return jsonify(analysis_result)
        
    except Exception as e:
        log(f"❌ Error crítico en /analyze: {str(e)}")
        import traceback
        traceback.print_exc()
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
        "version": "8.0 - Oracle V7.2 Integration"
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

@app.route('/refine', methods=['GET'])
def refine_endpoint():
    """
    Endpoint para Portfolio Manager Review
    Toma los datos del último análisis (caché o ejecuta nuevo) y los refina
    """
    if not PORTFOLIO_REFINER_AVAILABLE:
        return jsonify({
            "error": "Portfolio Refiner not available"
        }), 503
    
    try:
        log("\n" + "="*60)
        log("🧠 Portfolio Manager Review")
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
            log("❌ No hay resultados para refinar")
            return jsonify({
                "error": "No analysis results available. Run /analyze first."
            }), 404
        
        # 4. Verificar formato de datos
        # Si data tiene 'results', lo usamos directamente
        # Si data es una lista, necesitamos construir el objeto
        if isinstance(data, list):
            # Es solo la lista de results, construir objeto completo
            data_obj = {'results': data}
        elif isinstance(data, dict) and 'results' in data:
            data_obj = data
        else:
            log("❌ Formato de datos inválido")
            return jsonify({
                "error": "Invalid data format"
            }), 500
        
        # 5. Refinar los datos
        candidates_count = len(data_obj.get('results', [])) if isinstance(data_obj.get('results'), list) else data_obj.get('candidates_count', 0)
        log(f"🔍 Refinando {candidates_count} candidatos...")
        
        refiner = PortfolioRefiner(data_obj)
        refined_data = refiner.refine_all()
        
        if refined_data is None:
            log("❌ Error en refinamiento")
            return jsonify({
                "error": "Failed to refine data"
            }), 500
        
        log("✅ Refinamiento completado exitosamente")
        log("="*60)
        
        # 6. Retornar respuesta
        response_data = {
            "status": "success",
            "refined_data": refined_data,
            "refined_at": datetime.now().isoformat(),
            "original_analysis": {
                "generated_at": data_obj.get('generated_at'),
                "total_analyzed": data_obj.get('total_analyzed'),
                "candidates_count": data_obj.get('candidates_count'),
                "from_cache": data_obj.get('from_cache', False)
            }
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        log(f"❌ Error en refinamiento: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    log(f"🚀 Iniciando Warren Screener v8 - Oracle V7.2 Integration en puerto {port}")
    log(f"📦 Metodología: Oracle V7.2 (DCF 2-Stage + ROIC + Piotroski Real)")
    log(f"💾 Cache: {'Enabled' if GCS_AVAILABLE else 'Disabled'}")
    if GCS_AVAILABLE:
        log(f"🪣 Bucket: {GCS_BUCKET_NAME}")
    app.run(host="0.0.0.0", port=port)
