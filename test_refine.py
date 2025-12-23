#!/usr/bin/env python3
"""
test_refine.py - Script de prueba para el endpoint /refine
"""

import requests
import json
import sys

# URL del servicio (cambia esto por tu URL real)
SERVICE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"

print("="*60)
print("TEST: Endpoint /refine")
print("="*60)
print(f"URL: {SERVICE_URL}")
print()

# Test 1: Verificar que el servicio está activo
print("1️⃣  Verificando servicio...")
try:
    response = requests.get(f"{SERVICE_URL}/health", timeout=5)
    if response.status_code == 200:
        health = response.json()
        print(f"   ✅ Servicio activo")
        print(f"   Portfolio Refiner: {health.get('portfolio_refiner_available', False)}")
    else:
        print(f"   ❌ Servicio responde con error: {response.status_code}")
        sys.exit(1)
except Exception as e:
    print(f"   ❌ No se puede conectar al servicio: {e}")
    sys.exit(1)

print()

# Test 2: Verificar estado del caché
print("2️⃣  Verificando caché...")
try:
    response = requests.get(f"{SERVICE_URL}/cache-status", timeout=5)
    if response.status_code == 200:
        cache = response.json()
        if cache.get('cache_exists'):
            print(f"   ✅ Caché disponible")
            print(f"   Candidatos: {cache.get('candidates_count', 'N/A')}")
            print(f"   Tiempo restante: {cache.get('time_remaining_hours', 0):.1f}h")
        else:
            print(f"   ⚠️  No hay caché disponible")
            print(f"   Ejecuta primero: curl {SERVICE_URL}/analyze")
    else:
        print(f"   ⚠️  No se pudo verificar caché: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print()

# Test 3: Ejecutar /refine
print("3️⃣  Ejecutando /refine...")
print("   (esto puede tardar si no hay caché)")
print()

try:
    response = requests.get(f"{SERVICE_URL}/refine", timeout=300)  # 5 min timeout
    
    if response.status_code == 200:
        data = response.json()
        
        print("   ✅ Refinamiento exitoso!")
        print()
        
        # Mostrar resumen
        if 'refined_data' in data and 'summary' in data['refined_data']:
            summary = data['refined_data']['summary']
            
            print("   📊 RESUMEN:")
            print(f"      Total revisado: {summary.get('total_reviewed', 0)}")
            print(f"      💎 Joyas Reales: {summary.get('gems_count', 0)}")
            print(f"      ✅ Oportunidades: {summary.get('opportunities_count', 0)}")
            print(f"      ⚠️  Trampas: {summary.get('value_traps_count', 0)}")
            print(f"      📉 Ajustes: {summary.get('stocks_with_growth_adjustment', 0)}")
            print()
            
            # Mostrar distribución por categoría
            if 'by_category' in summary:
                print("   📋 POR CATEGORÍA:")
                for cat, count in summary['by_category'].items():
                    print(f"      {cat}: {count}")
                print()
            
            # Mostrar Joyas Reales si hay
            if 'gems' in data['refined_data'] and data['refined_data']['gems']:
                print("   💎 JOYAS REALES:")
                for gem in data['refined_data']['gems'][:5]:  # Primeras 5
                    print(f"      {gem['Ticker']} ({gem['Sector']})")
                    print(f"         MOS Ajustado: {gem['Adjusted_MOS']*100:.1f}%")
                    print(f"         ROIC: {gem['ROIC']*100:.1f}%")
                    print(f"         Razón: {gem['Reason']}")
                print()
            
            # Mostrar ejemplos de ajustes
            if 'refined_results' in data['refined_data']:
                adjusted = [r for r in data['refined_data']['refined_results'] 
                           if 'ajustado' in r.get('Reason', '').lower()]
                
                if adjusted:
                    print("   📉 EJEMPLOS DE AJUSTES:")
                    for stock in adjusted[:3]:  # Primeros 3
                        print(f"      {stock['Ticker']} ({stock['Sector']})")
                        print(f"         {stock['Reason']}")
                        print(f"         MOS: {stock['Original_MOS']*100:.1f}% → {stock['Adjusted_MOS']*100:.1f}%")
                    print()
        
        print("="*60)
        print("✅ TEST COMPLETADO EXITOSAMENTE")
        print("="*60)
        
    elif response.status_code == 404:
        print("   ❌ No hay datos para refinar")
        print("   Ejecuta primero: curl {SERVICE_URL}/analyze")
        
    elif response.status_code == 503:
        print("   ❌ Portfolio Refiner no disponible")
        print("   Verifica que portfolio_refiner.py esté en el servidor")
        
    else:
        print(f"   ❌ Error {response.status_code}")
        print(f"   {response.text}")
        
except requests.exceptions.Timeout:
    print("   ❌ Timeout - el análisis está tardando mucho")
    print("   Esto es normal si no había caché")
    
except Exception as e:
    print(f"   ❌ Error: {e}")
    import traceback
    traceback.print_exc()

print()
