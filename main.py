# =========================================
# Warren Screener v8 - DCF 2-Stage + Quality Focus
# CON CACHÉ EN CLOUD STORAGE DE 24 HORAS
# Análisis basado en ROIC, Piotroski y DCF avanzado
# =========================================

import json
import os
import sys
import logging
from datetime import datetime
from flask import Flask, jsonify, request

# Silencio de logs ruidosos
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.WARNING)

def log(msg):
    print(msg)
    sys.stdout.flush()

# -------- Importar módulos de análisis --------

# Portfolio Analyzer (Core)
try:
    from portfolio_analyzer import PortfolioAnalyzer, CacheManager
    from uk_analyzer import UKAnalyzer
    PORTFOLIO_ANALYZER_AVAILABLE = True
    # Inicializar instancias globales
    cache_manager = CacheManager()
    analyzer = PortfolioAnalyzer(cache_manager=cache_manager)
    GCS_AVAILABLE = cache_manager.gcs_available
    GCS_BUCKET_NAME = cache_manager.bucket_name
    CACHE_TTL_HOURS = cache_manager.cache_ttl_hours
    print("✓ Portfolio Analyzer cargado")
except ImportError as e:
    PORTFOLIO_ANALYZER_AVAILABLE = False
    GCS_AVAILABLE = False
    GCS_BUCKET_NAME = "not configured"
    CACHE_TTL_HOURS = 24
    cache_manager = None
    analyzer = None
    print(f"⚠️  Portfolio Analyzer no disponible: {e}")

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

# -------- Configuración --------
CONFIG = {
    'MAX_WORKERS': 12,
    'MIN_ROIC': 0.08,           # 8% mínimo
    'MIN_PIOTROSKI': 6,         # Calidad mínima (ajustado a 6)
    'RISK_FREE_RATE': 0.042,
    'MARGIN_OF_SAFETY_VIEW': -0.20
}

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
            "Piotroski Score >= 6 (calidad financiera sólida)",
            "DCF 2-Stage con WACC Dinámico (CAPM)",
            "Growth estimado basado en ROIC",
            "Margen de seguridad calculado vs precio actual"
        ],
        "filters": {
            "min_market_cap": "2B USD (Mid-cap support)",
            "min_roic": f"{CONFIG['MIN_ROIC']*100}%",
            "min_piotroski": CONFIG['MIN_PIOTROSKI'],
            "risk_free_rate": f"{CONFIG['RISK_FREE_RATE']*100}%"
        },
        "endpoints": {
            "/analyze": "Run US analysis (600 tickers, 24h cache)",
            "/analyzeuk": "Run UK analysis (FTSE 100/250, supports ?as_of=YYYY-MM-DD)",
            "/refine": "GET - Portfolio Manager Review (adjust growth by sector)",
            "/follow": "POST - Portfolio Performance Tracker (analyze your portfolio)",
            "/post-process": "POST - Manual post-processing of results",
            "/cache-status": "Check cache status",
            "/clear-cache": "Clear cache manually",
            "/health": "Health check"
        },
        "features": {
            "portfolio_analyzer": PORTFOLIO_ANALYZER_AVAILABLE,
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
    if not PORTFOLIO_ANALYZER_AVAILABLE:
        return jsonify({
            "error": "Portfolio Analyzer not available"
        }), 503
    
    try:
        log("\n" + "="*60)
        log("📊 Nueva petición de análisis recibida")
        log("="*60)
        
        results = analyzer.run_analysis()
        
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

@app.route('/analyzeuk')
def analyze_uk():
    """Endpoint de análisis para el mercado UK (FTSE 100 + FTSE 250)"""
    try:
        as_of = request.args.get('as_of', None)
        use_cache = request.args.get('cache', 'true').lower() == 'true'
        
        log("\n" + "="*60)
        log(f"🇬🇧 Petición de análisis UK recibida (As-Of: {as_of or 'Today'})")
        log("="*60)
        
        uk_analyzer = UKAnalyzer()
        results = uk_analyzer.run_analysis(as_of_date=as_of, use_cache=use_cache)
        
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
        log(f"❌ Error en análisis UK: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/cache-status')
def cache_status():
    """Verifica el estado del caché"""
    if not PORTFOLIO_ANALYZER_AVAILABLE or cache_manager is None:
        return jsonify({
            "cache_enabled": False,
            "message": "Portfolio Analyzer not available"
        })
    
    try:
        status = cache_manager.get_cache_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/clear-cache')
def clear_cache():
    """Limpia el caché manualmente"""
    if not PORTFOLIO_ANALYZER_AVAILABLE or cache_manager is None:
        return jsonify({"status": "Portfolio Analyzer not available"}), 503
    
    try:
        result = cache_manager.clear_cache()
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)
    except Exception as e:
        log(f"❌ Error limpiando caché: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "portfolio_analyzer_available": PORTFOLIO_ANALYZER_AVAILABLE,
        "cache_available": GCS_AVAILABLE,
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
    
    if not PORTFOLIO_ANALYZER_AVAILABLE or cache_manager is None:
        return jsonify({
            "error": "Portfolio Analyzer not available"
        }), 503
    
    try:
        log("\n" + "="*60)
        log("🧠 Portfolio Manager Review")
        log("="*60)
        
        # 1. Intentar obtener datos del caché primero
        log("📂 Buscando datos en caché...")
        cached_data = cache_manager.get_full_cached_data()
        
        if cached_data:
            log("✅ Datos encontrados en caché")
            data = cached_data
        else:
            # 2. Si no hay caché, ejecutar análisis nuevo
            log("⚠️  No hay caché, ejecutando análisis nuevo...")
            data = analyzer.run_analysis()
        
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
