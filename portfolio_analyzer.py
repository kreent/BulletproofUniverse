"""
portfolio_analyzer.py - Warren Screener v8 Core Analysis Engine
Módulo principal de análisis DCF 2-Stage + Quality Focus
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
# ⚙️ PARÁMETROS DE CAZA (AJUSTADOS)
# ==========================================
DEFAULT_CONFIG = {
    'MAX_WORKERS': 12,
    'MIN_ROIC': 0.08,           # 8% mínimo
    'MIN_PIOTROSKI': 5,         # Calidad mínima
    'DISCOUNT_RATE': 0.09,      # Tasa exigida del 9%
    'MARGIN_OF_SAFETY_VIEW': -0.20  # Watchlist hasta -20%
}

# Cache configuration
DEFAULT_CACHE_TTL_HOURS = 24
DEFAULT_CACHE_FILE_NAME = "screener_results.json"


def log(msg):
    """Helper para logging con flush inmediato"""
    print(msg)
    sys.stdout.flush()


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
    Motor principal de análisis de acciones
    Implementa metodología Warren Buffett con DCF 2-Stage
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

        # Intento 1: GitHub API (más confiable que raw)
        try:
            url_sp500 = "https://api.github.com/repos/datasets/s-and-p-500-companies/contents/data/constituents.csv"
            headers = {'Accept': 'application/vnd.github.v3.raw'}
            r = requests.get(url_sp500, headers=headers, timeout=30)
            r.raise_for_status()
            from io import StringIO
            df = pd.read_csv(StringIO(r.text))
            tickers.update(df['Symbol'].tolist())
            log(f"   -> S&P 500 cargado desde GitHub API ({len(tickers)})")
        except Exception as e:
            log(f"   ⚠️ Fallo GitHub S&P 500: {str(e)}")
            
            # Fallback: Intentar con raw.githubusercontent.com
            try:
                url_sp500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
                df = pd.read_csv(url_sp500, timeout=30)
                tickers.update(df['Symbol'].tolist())
                log(f"   -> S&P 500 cargado desde GitHub raw ({len(tickers)})")
            except Exception as e2:
                log(f"   ⚠️ Fallo GitHub raw: {str(e2)}")

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
                log(f"   -> Nasdaq cargado ({len(nasdaq_ticks)})")
        except Exception as e:
            log(f"   ⚠️ Fallo GitHub Nasdaq: {str(e)}")

        # Intento 3: Lista de Respaldo MANUAL COMPLETA
        BACKUP_LIST = [
            # Originales (90 tickers)
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B', 'LLY', 'V',
            'TSM', 'UNH', 'AVGO', 'JPM', 'NVO', 'WMT', 'XOM', 'MA', 'JNJ', 'PG',
            'HD', 'MRK', 'COST', 'ABBV', 'ORCL', 'ASML', 'CVX', 'ADBE', 'AMD', 'KO',
            'PEP', 'CRM', 'BAC', 'ACN', 'CSCO', 'NFLX', 'MCD', 'LIN', 'AZN', 'NKE',
            'DIS', 'TMUS', 'ABT', 'DHR', 'WFC', 'INTC', 'INTU', 'QCOM', 'CMCSA', 'TXN',
            'VZ', 'UPS', 'PM', 'NEE', 'RTX', 'MS', 'HON', 'AMGN', 'UNP', 'PFE',
            'LOW', 'SPGI', 'CAT', 'IBM', 'AMAT', 'DE', 'GS', 'GE', 'LMT', 'PLD',
            'BLK', 'SYK', 'T', 'ISRG', 'BKNG', 'ELV', 'MDT', 'TJX', 'ADI', 'NOW',
            'MMC', 'CVS', 'ADP', 'VRTX', 'LRCX', 'UBER', 'REGN', 'PYPL', 'ZTS', 'CI',
            # Agregados - Los que salen en Colab pero faltaban
            'MET', 'AMP', 'KMB', 'FCX', 'CLX', 'IT', 'BIIB', 'CL', 'ZBRA', 'WSM',
            'MKTX', 'LII', 'FDS', 'RL', 'HAS',
            # Más del S&P 500 para completar
            'GOOG', 'BRK-A', 'AVGO', 'TSLA', 'JPM', 'UNH', 'LLY', 'XOM', 'V', 'PG',
            'JNJ', 'MA', 'NVDA', 'HD', 'ABBV', 'MRK', 'COST', 'CVX', 'ADBE', 'PEP',
            'KO', 'TMO', 'CSCO', 'ACN', 'MCD', 'ABT', 'NFLX', 'WFC', 'ORCL', 'CRM',
            'DHR', 'TXN', 'AMD', 'CMCSA', 'QCOM', 'INTU', 'NKE', 'VZ', 'PM', 'UPS',
            'NEE', 'RTX', 'HON', 'AMGN', 'LOW', 'SPGI', 'BMY', 'SBUX', 'BA', 'CAT',
            'GS', 'IBM', 'AXP', 'ISRG', 'GILD', 'BLK', 'DE', 'ELV', 'MDT', 'SCHW',
            'AMAT', 'SYK', 'PLD', 'LMT', 'ADI', 'BKNG', 'VRTX', 'TJX', 'REGN', 'ADP',
            'MDLZ', 'CB', 'NOW', 'LRCX', 'MO', 'AMT', 'MMC', 'PYPL', 'PGR', 'SO',
            'CI', 'DUK', 'ETN', 'BSX', 'SLB', 'ZTS', 'GE', 'EQIX', 'PNC', 'NOC',
            'USB', 'TGT', 'ITW', 'REGN', 'BDX', 'MU', 'HCA', 'MS', 'WELL', 'KLAC',
            'EOG', 'C', 'MMM', 'APH', 'FI', 'MCK', 'WM', 'PH', 'SNPS', 'CDNS',
            'SHW', 'CMG', 'MAR', 'TDG', 'EMR', 'NSC', 'APD', 'MSI', 'NXPI', 'CARR',
            'PSX', 'ADSK', 'CSX', 'CME', 'COP', 'MPC', 'TT', 'AJG', 'MCO', 'GM',
            'AFL', 'ROP', 'PCAR', 'O', 'MCHP', 'SRE', 'HUM', 'ORLY', 'AZO', 'PAYX',
            'D', 'ICE', 'MSCI', 'FTNT', 'KMB', 'ROST', 'ECL', 'AIG', 'TRV', 'CCI',
            'JCI', 'TEL', 'CPRT', 'AEP', 'CL', 'HSY', 'GWW', 'PSA', 'MNST', 'KMI',
            'EW', 'FAST', 'BK', 'CTAS', 'FCX', 'NEM', 'ALL', 'ODFL', 'DLR', 'EXC',
            'SPG', 'CMI', 'IQV', 'KHC', 'CTVA', 'YUM', 'EA', 'XEL', 'GIS', 'VRSK',
            'AME', 'DXCM', 'HLT', 'KVUE', 'PCG', 'DD', 'OTIS', 'RSG', 'IDXX', 'A',
            'ANSS', 'VICI', 'VMC', 'MLM', 'BKR', 'KEYS', 'CTSH', 'IT', 'WMB', 'ROK',
            'EXR', 'OKE', 'RMD', 'PPG', 'DOV', 'GEHC', 'AVB', 'BIIB', 'FICO', 'SYY',
            'EIX', 'ED', 'CBRE', 'TROW', 'MTD', 'IRM', 'DAL', 'ALNY', 'HAL', 'ACGL',
            'MPWR', 'WEC', 'WSM', 'XYL', 'FTV', 'GLW', 'WBD', 'FITB', 'IR', 'CHTR',
            'CDW', 'HPQ', 'TSCO', 'AWK', 'DTE', 'ES', 'CAH', 'PPL', 'FDS', 'ETR',
            'LH', 'GPN', 'CHD', 'EBAY', 'KEYS', 'RF', 'MTB', 'HPE', 'RL', 'ZBRA',
            'TTWO', 'NTAP', 'STT', 'BALL', 'CLX', 'HAS', 'LUV', 'UAL', 'MKTX',
            'LII', 'AMP', 'MET', 'ULTA', 'APTV', 'STE', 'DFS', 'CFG', 'INVH', 'HBAN'
        ]

        if len(tickers) < 50:
            log(f"   ⚠️ Fallaron descargas externas. Usando Lista de Respaldo Manual ({len(BACKUP_LIST)} tickers).")
            tickers.update(BACKUP_LIST)

        final_list = list(set([t.replace('.', '-') for t in tickers]))
        final_count = min(500, len(final_list))
        log(f"   ✅ Total final: {final_count} tickers para analizar")
        return final_list[:500]
    
    @staticmethod
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
    
    def analyze_stock(self, ticker):
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
            ni = self.get_fuzzy_series(inc, ['Net Income', 'NetIncome'])
            ebit = self.get_fuzzy_series(inc, ['EBIT', 'Operating Income'])
            ocf = self.get_fuzzy_series(cf, ['Operating Cash Flow', 'Total Cash From Operating Activities'])
            capex = self.get_fuzzy_series(cf, ['Capital Expenditures', 'Purchase of PPE'])
            equity = self.get_fuzzy_series(bal, ['Stockholders Equity', 'Total Equity'])
            debt = self.get_fuzzy_series(bal, ['Total Debt'])
            cash = self.get_fuzzy_series(bal, ['Cash', 'Cash And Cash Equivalents'])

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

            if roic < self.config['MIN_ROIC']: 
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

            if piotroski < self.config['MIN_PIOTROSKI']: 
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
                    future_cash += val / ((1 + self.config['DISCOUNT_RATE']) ** i)

                # Stage 2: Terminal
                terminal_fcf = fcf * ((1 + growth_proxy) ** 5)
                term_val = (terminal_fcf * 1.03) / (self.config['DISCOUNT_RATE'] - 0.03)
                term_val_pv = term_val / ((1 + self.config['DISCOUNT_RATE']) ** 5)

                ev = future_cash + term_val_pv
                equity_val = ev + curr_cash - curr_debt
                intrinsic = equity_val / fast.shares

                if intrinsic > 0:
                    mos = (intrinsic - price) / intrinsic

            # FILTRO DE SALIDA
            if mos < self.config['MARGIN_OF_SAFETY_VIEW'] and piotroski < 7:
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
        
        log("🎯 Iniciando Warren Screener v8")
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
            "results": all_results,  # TODOS los resultados, ordenados por MOS descendente
            "summary": {
                "buy_zone_count": len(buy_candidates),      # MOS > 10%
                "fair_zone_count": len(fair_value),         # MOS 0-10%
                "watch_zone_count": len(watchlist)          # MOS < 0%
            },
            "generated_at": datetime.now().isoformat(),
            "cache_enabled": self.cache_manager.gcs_available,
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
    print("Portfolio Analyzer listo para ejecutar")
    print("Uso:")
    print("  from portfolio_analyzer import PortfolioAnalyzer, CacheManager")
    print("  analyzer = PortfolioAnalyzer()")
    print("  results = analyzer.run_analysis()")
    print("")
    print("  # O con función de conveniencia:")
    print("  from portfolio_analyzer import analyze_portfolio")
    print("  results = analyze_portfolio()")
