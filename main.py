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
from flask import Flask, jsonify
from google.cloud import storage
from concurrent.futures import ThreadPoolExecutor, as_completed

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
# ⚙️ PARÁMETROS DE CAZA (AJUSTADOS)
# ==========================================
CONFIG = {
    'MAX_WORKERS': 12,
    'MIN_ROIC': 0.08,           # 8% mínimo
    'MIN_PIOTROSKI': 5,         # Calidad mínima
    'DISCOUNT_RATE': 0.09,      # Tasa exigida del 9%
    'MARGIN_OF_SAFETY_VIEW': -0.20  # Watchlist hasta -20%
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

    # Intento 1: Datasets de GitHub (Más estable que Wikipedia)
    try:
        url_sp500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
        df = pd.read_csv(url_sp500, timeout=30)
        tickers.update(df['Symbol'].tolist())
        print(f"   -> S&P 500 cargado desde GitHub ({len(tickers)})")
    except Exception as e:
        print(f"   ⚠️ Fallo GitHub S&P 500.")

    # Intento 2: Nasdaq 100 (GitHub raw)
    try:
        url_ndx = "https://raw.githubusercontent.com/nasdaq-100/nasdaq-100-symbols/master/nasdaq-100-symbols.csv"
        # A veces viene sin header o con nombres distintos, intentamos robustez
        r = requests.get(url_ndx, timeout=30)
        text = r.text
        lines = text.split('\n')
        # Limpieza básica
        nasdaq_ticks = [x.split(',')[0].strip() for x in lines if x and 'Symbol' not in x]
        tickers.update(nasdaq_ticks)
        print(f"   -> Nasdaq cargado ({len(nasdaq_ticks)})")
    except Exception as e:
        print(f"   ⚠️ Fallo GitHub Nasdaq.")

    # Intento 3: Lista de Respaldo MANUAL (Si todo falla, usamos esto)
    # 80 empresas variadas para asegurar resultados
    BACKUP_LIST = [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B', 'LLY', 'V',
        'TSM', 'UNH', 'AVGO', 'JPM', 'NVO', 'WMT', 'XOM', 'MA', 'JNJ', 'PG',
        'HD', 'MRK', 'COST', 'ABBV', 'ORCL', 'ASML', 'CVX', 'ADBE', 'AMD', 'KO',
        'PEP', 'CRM', 'BAC', 'ACN', 'CSCO', 'NFLX', 'MCD', 'LIN', 'AZN', 'NKE',
        'DIS', 'TMUS', 'ABT', 'DHR', 'WFC', 'INTC', 'INTU', 'QCOM', 'CMCSA', 'TXN',
        'VZ', 'UPS', 'PM', 'NEE', 'RTX', 'MS', 'HON', 'AMGN', 'UNP', 'PFE',
        'LOW', 'SPGI', 'CAT', 'IBM', 'AMAT', 'DE', 'GS', 'GE', 'LMT', 'PLD',
        'BLK', 'SYK', 'T', 'ISRG', 'BKNG', 'ELV', 'MDT', 'TJX', 'ADI', 'NOW',
        'MMC', 'CVS', 'ADP', 'VRTX', 'LRCX', 'UBER', 'REGN', 'PYPL', 'ZTS', 'CI'
    ]

    if len(tickers) < 50:
        print("⚠️ Fallaron descargas externas. Usando Lista de Respaldo Manual.")
        tickers.update(BACKUP_LIST)

    final_list = list(set([t.replace('.', '-') for t in tickers]))
    return final_list[:500] # Limitamos a 500 para velocidad

# ==========================================
# 2. MOTOR DE BÚSQUEDA FUZZY (V5 Core)
# ==========================================
def get_fuzzy_series(df, keywords):
    """Búsqueda fuzzy de campos en DataFrames financieros"""
    if df.empty: 
        return pd.Series(dtype=float)
    
    df.index = df.index.astype(str).str.lower().str.strip()
    
    for key in keywords:
        key = key.lower()
        if key in df.index: 
            return df.loc[key]
        matches = [idx for idx in df.index if key in idx]
        if matches: 
            return df.loc[min(matches, key=len)]
    
    return pd.Series(dtype=float)

# ==========================================
# 3. ANÁLISIS FINANCIERO (DCF 2-STAGE + CALIDAD)
# ==========================================
def analyze_stock_v7(ticker):
    """Analiza una acción individual con metodología Warren Buffett + DCF"""
    try:
        t = yf.Ticker(ticker)

        # Filtro rápido de liquidez/precio
        try:
            fast = t.fast_info
            if fast.market_cap < 5_000_000_000: 
                return None  # Solo > 5B Cap
        except: 
            return None

        inc = t.income_stmt
        bal = t.balance_sheet
        cf = t.cashflow

        if inc.empty or bal.empty or cf.empty: 
            return None

        # Ordenar cronológicamente
        inc = inc[sorted(inc.columns, reverse=True)]
        bal = bal[sorted(bal.columns, reverse=True)]
        cf = cf[sorted(cf.columns, reverse=True)]

        # Extracción Fuzzy
        ni = get_fuzzy_series(inc, ['Net Income', 'NetIncome'])
        ebit = get_fuzzy_series(inc, ['EBIT', 'Operating Income'])
        ocf = get_fuzzy_series(cf, ['Operating Cash Flow', 'Total Cash From Operating Activities'])
        capex = get_fuzzy_series(cf, ['Capital Expenditures', 'Purchase of PPE'])
        equity = get_fuzzy_series(bal, ['Stockholders Equity', 'Total Equity'])
        debt = get_fuzzy_series(bal, ['Total Debt'])
        cash = get_fuzzy_series(bal, ['Cash', 'Cash And Cash Equivalents'])

        if ni.empty or ocf.empty or equity.empty: 
            return None

        # --- A. CALIDAD (ROIC & PIOTROSKI) ---
        # ROIC
        curr_ebit = ebit.iloc[0] if not ebit.empty else ni.iloc[0]
        curr_eq = equity.iloc[0]
        curr_debt = debt.iloc[0] if not debt.empty else 0
        curr_cash = cash.iloc[0] if not cash.empty else 0

        invested_cap = curr_eq + curr_debt - curr_cash
        roic = (curr_ebit * 0.79) / invested_cap if invested_cap > 0 else 0

        if roic < CONFIG['MIN_ROIC']: 
            return None

        # Piotroski Rápido
        piotroski = 0
        try:
            if len(ni) > 1:
                piotroski += 1 if ni.iloc[0] > 0 else 0
                piotroski += 1 if ocf.iloc[0] > 0 else 0
                piotroski += 1 if ni.iloc[0] > ni.iloc[1] else 0
                piotroski += 1 if ocf.iloc[0] > ni.iloc[0] else 0
                piotroski += 1 if (not debt.empty and len(debt)>1 and curr_debt <= debt.iloc[1]) else 0
            else: 
                piotroski = 5  # Beneficio de la duda
        except: 
            piotroski = 5

        if piotroski < CONFIG['MIN_PIOTROSKI']: 
            return None

        # --- B. VALORACIÓN (DCF 2-Etapas) ---
        price = fast.last_price
        cpx_val = abs(capex.iloc[0]) if not capex.empty else 0
        fcf = ocf.iloc[0] - cpx_val

        intrinsic = 0
        mos = -0.99

        if fcf > 0:
            # Tasa de crecimiento: Proxy basado en ROIC y Reinvestment
            growth_proxy = min(roic * 0.5, 0.14)  # Max 14%
            growth_proxy = max(growth_proxy, 0.03)  # Min 3%

            # Stage 1: 5 años
            future_cash = 0
            for i in range(1, 6):
                val = fcf * ((1 + growth_proxy) ** i)
                future_cash += val / ((1 + CONFIG['DISCOUNT_RATE']) ** i)

            # Stage 2: Terminal
            terminal_fcf = fcf * ((1 + growth_proxy) ** 5)
            term_val = (terminal_fcf * 1.03) / (CONFIG['DISCOUNT_RATE'] - 0.03)
            term_val_pv = term_val / ((1 + CONFIG['DISCOUNT_RATE']) ** 5)

            ev = future_cash + term_val_pv
            equity_val = ev + curr_cash - curr_debt
            intrinsic = equity_val / fast.shares

            if intrinsic > 0:
                mos = (intrinsic - price) / intrinsic

        # FILTRO DE SALIDA
        if mos < CONFIG['MARGIN_OF_SAFETY_VIEW'] and piotroski < 7:
            return None

        # Obtener sector
        try:
            sector = t.info.get('sector', 'N/A')
        except:
            sector = 'N/A'

        return {
            'Ticker': ticker,
            'Price': round(price, 2),
            'Sector': sector,
            'ROIC': roic,
            'Piotroski': piotroski,
            'Growth_Est': growth_proxy,
            'Intrinsic': intrinsic,
            'MOS': mos
        }

    except Exception as e:
        # Log silencioso de errores individuales
        return None

# ==========================================
# 4. FUNCIÓN PRINCIPAL DE ANÁLISIS
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
        "version": "8.0",
        "cache": cache_status,
        "bucket": GCS_BUCKET_NAME if GCS_AVAILABLE else "not configured",
        "cache_ttl_hours": CACHE_TTL_HOURS,
        "methodology": [
            "ROIC mínimo 8% (retorno sobre capital invertido)",
            "Piotroski Score >= 5 (calidad financiera)",
            "DCF 2-Stage con tasa de descuento 9%",
            "Growth estimado basado en ROIC",
            "Margen de seguridad calculado vs precio actual"
        ],
        "filters": {
            "min_market_cap": "5B USD",
            "min_roic": f"{CONFIG['MIN_ROIC']*100}%",
            "min_piotroski": CONFIG['MIN_PIOTROSKI'],
            "discount_rate": f"{CONFIG['DISCOUNT_RATE']*100}%"
        },
        "endpoints": {
            "/analyze": "Run analysis (with 24h cache)",
            "/cache-status": "Check cache status",
            "/clear-cache": "Clear cache manually",
            "/health": "Health check"
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
        "version": "8.0 - DCF 2-Stage + Quality"
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    log(f"🚀 Iniciando Warren Screener v8 en puerto {port}")
    log(f"📦 Metodología: DCF 2-Stage + ROIC + Piotroski")
    log(f"💾 Cache: {'Enabled' if GCS_AVAILABLE else 'Disabled'}")
    if GCS_AVAILABLE:
        log(f"🪣 Bucket: {GCS_BUCKET_NAME}")
    app.run(host="0.0.0.0", port=port)
