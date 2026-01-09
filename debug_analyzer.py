#!/usr/bin/env python3
"""
debug_analyzer.py - Debug detallado del analyzer
"""

import sys
import os

# Simular ambiente sin yfinance para ver el error real
print("="*60)
print("🔍 DEBUG DETALLADO DEL ANALYZER")
print("="*60)

# Test 1: Imports
print("\n1️⃣ Testeando imports...")
try:
    import pandas as pd
    print("  ✅ pandas OK")
except Exception as e:
    print(f"  ❌ pandas: {e}")

try:
    import numpy as np
    print("  ✅ numpy OK")
except Exception as e:
    print(f"  ❌ numpy: {e}")

try:
    import yfinance as yf
    print("  ✅ yfinance OK")
except Exception as e:
    print(f"  ❌ yfinance: {e}")

# Test 2: Estructura del código
print("\n2️⃣ Analizando estructura del código...")
with open('/home/claude/portfolio_analyzer.py', 'r') as f:
    code = f.read()
    
    # Verificar que tenga las funciones clave
    checks = [
        ('class WarrenScreener', 'Clase principal'),
        ('def analyze_ticker', 'Método de análisis'),
        ('def compute_piotroski_fscore', 'Piotroski real'),
        ('MIN_PIO_COVERAGE', 'Config coverage'),
        ('def get_fuzzy_series', 'Fuzzy matching'),
        ('def analyze_portfolio', 'Función helper')
    ]
    
    for check, desc in checks:
        if check in code:
            print(f"  ✅ {desc}: Encontrado")
        else:
            print(f"  ❌ {desc}: NO encontrado")

# Test 3: Config por defecto
print("\n3️⃣ Verificando config por defecto...")
try:
    from portfolio_analyzer import WarrenScreener
    screener = WarrenScreener()
    config = screener.config
    
    required_keys = ['MAX_WORKERS', 'MIN_ROIC', 'MIN_PIOTROSKI', 'MIN_PIO_COVERAGE', 'DISCOUNT_RATE', 'MARGIN_OF_SAFETY_VIEW']
    
    for key in required_keys:
        if key in config:
            print(f"  ✅ {key}: {config[key]}")
        else:
            print(f"  ❌ {key}: FALTA")
            
except Exception as e:
    print(f"  ❌ Error al cargar config: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Universo
print("\n4️⃣ Testeando generación de universo...")
try:
    from portfolio_analyzer import WarrenScreener
    screener = WarrenScreener()
    
    # Probar solo con backup list
    print("  📋 Generando universo...")
    universe = screener.get_bulletproof_universe()
    print(f"  ✅ Universo generado: {len(universe)} tickers")
    print(f"  📝 Primeros 10: {universe[:10]}")
    
except Exception as e:
    print(f"  ❌ Error generando universo: {e}")
    import traceback
    traceback.print_exc()

# Test 5: Análisis de ticker (sin network)
print("\n5️⃣ Analizando lógica sin network...")
try:
    from portfolio_analyzer import WarrenScreener
    screener = WarrenScreener()
    
    # Ver qué pasa con un ticker
    print("  🔍 Intentando analizar AAPL...")
    result = screener.analyze_ticker("AAPL")
    
    if result:
        print(f"  ✅ Análisis exitoso:")
        for key, value in result.items():
            print(f"     {key}: {value}")
    else:
        print(f"  ⚠️  No pasó filtros o error de red (esperado sin red)")
        
except Exception as e:
    print(f"  ❌ Error en análisis: {e}")
    import traceback
    traceback.print_exc()

# Test 6: Verificar filtros
print("\n6️⃣ Verificando lógica de filtros...")
try:
    from portfolio_analyzer import WarrenScreener
    
    # Config muy permisivo
    screener = WarrenScreener(config={
        'MAX_WORKERS': 1,
        'MIN_ROIC': 0.01,  # 1%
        'MIN_PIOTROSKI': 1,  # Muy bajo
        'MIN_PIO_COVERAGE': 1,  # Muy bajo
        'DISCOUNT_RATE': 0.09,
        'MARGIN_OF_SAFETY_VIEW': -0.90  # Muy permisivo
    })
    
    print(f"  📊 Config permisivo:")
    print(f"     MIN_ROIC: {screener.config['MIN_ROIC']}")
    print(f"     MIN_PIOTROSKI: {screener.config['MIN_PIOTROSKI']}")
    print(f"     MIN_PIO_COVERAGE: {screener.config['MIN_PIO_COVERAGE']}")
    print(f"     MARGIN_OF_SAFETY_VIEW: {screener.config['MARGIN_OF_SAFETY_VIEW']}")
    
except Exception as e:
    print(f"  ❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("✅ DEBUG COMPLETADO")
print("="*60)
print("\n💡 Si todos los checks pasan pero /analyze retorna 0,")
print("   el problema es Yahoo Finance bloqueando las requests.")
print("   Solución: Esperar 1 hora o ejecutar desde Cloud Run.")
print()
