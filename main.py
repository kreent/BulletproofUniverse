# =========================================
# Warren Screener v8 - DCF 2-Stage + Quality Focus
# CON CACHÉ EN CLOUD STORAGE DE 24 HORAS
# Análisis basado en ROIC, Piotroski y DCF avanzado
# =========================================

import logging
import json
import os
import sys
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from google.cloud import storage

# Portfolio Analyzer (core del screener)
try:
    from portfolio_analyzer import analyze_portfolio, WarrenScreener
    PORTFOLIO_ANALYZER_AVAILABLE = True
except ImportError:
    PORTFOLIO_ANALYZER_AVAILABLE = False
    print("❌ Portfolio Analyzer no disponible")

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
# FUNCIÓN PRINCIPAL DE ANÁLISIS
# ==========================================
def run_analysis():
    """
    Ejecuta el análisis completo usando WarrenScreener
    Esta función reemplaza todo el código de análisis que estaba en main.py
    
    Los parámetros de configuración están definidos en portfolio_analyzer.py
    y pueden sobrescribirse pasando un dict personalizado.
    """
    if not PORTFOLIO_ANALYZER_AVAILABLE:
        log("❌ Portfolio Analyzer no disponible")
        return None
    
    try:
        # Usar configuración por defecto del módulo portfolio_analyzer
        # Si necesitas personalizar, puedes pasar un config dict:
        # custom_config = {'MIN_ROIC': 0.10, 'MIN_PIOTROSKI': 6}
        # results = analyze_portfolio(custom_config)
        
        results = analyze_portfolio()  # Usa CONFIG por defecto del módulo
        return results
        
    except Exception as e:
        log(f"❌ Error en análisis: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

# ==========================================
# FLASK APP
# ==========================================
app = Flask(__name__)

@app.route('/analyze')
def analyze():
    """
    Endpoint principal: Ejecuta análisis o sirve desde caché
    
    Query params opcionales para sobrescribir configuración:
    - min_roic: float (default: 0.08)
    - min_piotroski: int (default: 5)
    - discount_rate: float (default: 0.09)
    - margin_of_safety_view: float (default: -0.20)
    """
    log("\n" + "="*60)
    log("📊 Warren Screener v8.0 - Request recibido")
    log("="*60)
    
    # Verificar si hay parámetros de configuración personalizados
    custom_config = None
    if any(key in request.args for key in ['min_roic', 'min_piotroski', 'discount_rate', 'margin_of_safety_view']):
        from portfolio_analyzer import WarrenScreener
        # Obtener config por defecto y sobrescribir solo lo que venga en los params
        default_config = WarrenScreener().config
        custom_config = default_config.copy()
        
        if 'min_roic' in request.args:
            try:
                custom_config['MIN_ROIC'] = float(request.args['min_roic'])
                log(f"🔧 MIN_ROIC personalizado: {custom_config['MIN_ROIC']}")
            except ValueError:
                pass
        
        if 'min_piotroski' in request.args:
            try:
                custom_config['MIN_PIOTROSKI'] = int(request.args['min_piotroski'])
                log(f"🔧 MIN_PIOTROSKI personalizado: {custom_config['MIN_PIOTROSKI']}")
            except ValueError:
                pass
        
        if 'discount_rate' in request.args:
            try:
                custom_config['DISCOUNT_RATE'] = float(request.args['discount_rate'])
                log(f"🔧 DISCOUNT_RATE personalizado: {custom_config['DISCOUNT_RATE']}")
            except ValueError:
                pass
        
        if 'margin_of_safety_view' in request.args:
            try:
                custom_config['MARGIN_OF_SAFETY_VIEW'] = float(request.args['margin_of_safety_view'])
                log(f"🔧 MARGIN_OF_SAFETY_VIEW personalizado: {custom_config['MARGIN_OF_SAFETY_VIEW']}")
            except ValueError:
                pass
    
    # 1. Verificar si hay caché válido (solo si no hay config personalizado)
    if custom_config is None:
        cached_data = get_cached_results()
        
        if cached_data:
            # Servir desde caché
            log("✅ Sirviendo desde caché")
            log("="*60)
            
            response = cached_data.copy()
            response['from_cache'] = True
            response['execution_time_seconds'] = 0.2
            
            return jsonify(response)
    else:
        log("⚠️  Config personalizado detectado, omitiendo caché")
    
    # 2. Ejecutar análisis completo
    log("🔄 Ejecutando análisis completo...")
    
    if custom_config:
        # Análisis con config personalizado
        results = analyze_portfolio(custom_config)
    else:
        # Análisis con config por defecto
        results = run_analysis()
    
    if not results:
        log("❌ Análisis falló")
        return jsonify({"error": "Analysis failed"}), 500
    
    # 3. Guardar en caché solo si es análisis con config por defecto
    if custom_config is None:
        save_to_cache(results)
    else:
        log("⚠️  Config personalizado, no se guardará en caché")
    
    # 4. Retornar resultados
    results['from_cache'] = False
    
    log("\n" + "="*60)
    log("✅ Análisis completado exitosamente")
    log(f"📊 Candidatos: {results.get('candidates_count', 0)}")
    log(f"🟢 Compra: {results.get('buy_candidates', 0)}")
    log(f"🟡 Justo: {results.get('fair_value', 0)}")
    log(f"🔴 Watch: {results.get('watchlist', 0)}")
    log(f"⏱️  Tiempo: {results.get('execution_time_seconds', 0)}s")
    log("="*60)
    
    return jsonify(results)

@app.route('/cache-status')
def cache_status():
    """Endpoint para verificar el estado del caché"""
    if not GCS_AVAILABLE:
        return jsonify({
            "cache_available": False,
            "message": "Cloud Storage not available"
        })
    
    try:
        blob = bucket.blob(CACHE_FILE_NAME)
        
        if not blob.exists():
            return jsonify({
                "cache_available": False,
                "message": "No cache data found"
            })
        
        cache_content = blob.download_as_string()
        data = json.loads(cache_content)
        
        cached_at = datetime.fromisoformat(data.get("cached_at", ""))
        expires_at = datetime.fromisoformat(data.get("expires_at", ""))
        time_diff = datetime.now() - cached_at
        time_until_expiry = expires_at - datetime.now()
        
        is_valid = time_diff < timedelta(hours=CACHE_TTL_HOURS)
        
        return jsonify({
            "cache_available": True,
            "is_valid": is_valid,
            "cached_at": cached_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "hours_ago": round(time_diff.total_seconds() / 3600, 1),
            "hours_until_expiry": round(time_until_expiry.total_seconds() / 3600, 1),
            "total_candidates": data["results"].get("candidates_count", 0) if "results" in data else 0
        })
        
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

@app.route('/clear-cache', methods=['GET', 'POST'])
def clear_cache():
    """Endpoint para limpiar el caché manualmente"""
    if not GCS_AVAILABLE:
        return jsonify({
            "success": False,
            "message": "Cloud Storage not available"
        })
    
    try:
        blob = bucket.blob(CACHE_FILE_NAME)
        
        if blob.exists():
            blob.delete()
            log("🗑️  Caché eliminado manualmente")
            return jsonify({
                "success": True,
                "message": "Cache cleared successfully. Next /analyze will run fresh analysis."
            })
        else:
            return jsonify({
                "success": True,
                "message": "No cache to clear"
            })
            
    except Exception as e:
        log(f"❌ Error limpiando caché: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/diagnose')
def diagnose():
    """Endpoint de diagnóstico para debug"""
    if not PORTFOLIO_ANALYZER_AVAILABLE:
        return jsonify({
            "error": "Portfolio Analyzer not available"
        }), 503
    
    try:
        from portfolio_analyzer import WarrenScreener
        
        # Crear screener con config por defecto
        screener = WarrenScreener()
        
        # Probar con un ticker conocido
        test_ticker = "AAPL"
        log(f"\n🔍 Diagnosticando con {test_ticker}...")
        result = screener.analyze_ticker(test_ticker)
        
        return jsonify({
            "status": "ok",
            "test_ticker": test_ticker,
            "result": result,
            "config_used": screener.config,
            "terminal_g_sectors": screener.TERMINAL_G_BY_SECTOR
        })
        
    except Exception as e:
        log(f"❌ Error en diagnóstico: {str(e)}")
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

@app.route('/analyze-debug')
def analyze_debug():
    """
    Endpoint de debugging con filtros MUY permisivos
    Solo para diagnosticar problemas - analiza 50 tickers
    """
    if not PORTFOLIO_ANALYZER_AVAILABLE:
        return jsonify({
            "error": "Portfolio Analyzer not available"
        }), 503
    
    log("\n" + "="*60)
    log("🐛 DEBUG MODE - Análisis con filtros ultra permisivos")
    log("="*60)
    
    try:
        # Config ultra permisivo
        debug_config = {
            'MAX_WORKERS': 6,
            'MIN_ROIC': 0.01,  # 1% - súper permisivo
            'MIN_PIOTROSKI': 3,
            'MIN_PIO_COVERAGE': 3,
            'DISCOUNT_RATE': 0.09,
            'MARGIN_OF_SAFETY_VIEW': -0.90
        }
        
        log(f"📊 Config de debug:")
        for key, value in debug_config.items():
            log(f"   {key}: {value}")
        
        from portfolio_analyzer import WarrenScreener
        screener = WarrenScreener(debug_config)
        
        # Solo 50 tickers para test rápido
        screener.get_bulletproof_universe()
        screener.universe = screener.universe[:50]
        
        log(f"\n🎯 Analizando {len(screener.universe)} tickers...")
        log(f"   Muestra: {screener.universe[:10]}")
        
        screener.run_parallel_analysis()
        categorized = screener.categorize_results()
        
        import pandas as pd
        df_all = pd.DataFrame(screener.results) if screener.results else pd.DataFrame()
        top_10 = df_all.nlargest(10, 'MOS').to_dict('records') if not df_all.empty else []
        
        result = {
            'mode': 'DEBUG',
            'config': debug_config,
            'universe_size': len(screener.universe),
            'candidates_count': len(screener.results),
            'buy_candidates': len(categorized['buy_zone']),
            'top_10': top_10,
            'all_results': screener.results[:20],  # Solo primeros 20
            'generated_at': datetime.now().isoformat()
        }
        
        log("="*60)
        log(f"✅ Debug: {len(screener.results)} candidatos de {len(screener.universe)}")
        log("="*60)
        
        return jsonify(result)
        
    except Exception as e:
        log(f"❌ Error en debug: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache_available": GCS_AVAILABLE,
        "portfolio_analyzer_available": PORTFOLIO_ANALYZER_AVAILABLE,
        "post_processor_available": POST_PROCESSOR_AVAILABLE,
        "portfolio_refiner_available": PORTFOLIO_REFINER_AVAILABLE,
        "portfolio_tracker_available": PORTFOLIO_TRACKER_AVAILABLE,
        "version": "8.0 - DCF 2-Stage + Quality + Portfolio Manager + Tracker"
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
    log(f"🚀 Iniciando Warren Screener v8 en puerto {port}")
    log(f"📦 Metodología: DCF 2-Stage + ROIC + Piotroski")
    log(f"💾 Cache: {'Enabled' if GCS_AVAILABLE else 'Disabled'}")
    if GCS_AVAILABLE:
        log(f"🪣 Bucket: {GCS_BUCKET_NAME}")
    app.run(host="0.0.0.0", port=port)
