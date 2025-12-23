#!/usr/bin/env python3
"""
example_follow.py - Ejemplos de uso del endpoint /follow
Portfolio Performance Tracker
"""

import requests
import json
import sys

# URL del servicio
SERVICE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"

print("="*60)
print("📊 Portfolio Performance Tracker - Ejemplos")
print("="*60)
print(f"URL: {SERVICE_URL}\n")

# ============================================
# EJEMPLO 1: Portfolio Simple
# ============================================

def example_simple_portfolio():
    """Portfolio simple con 3 acciones"""
    print("\n" + "="*60)
    print("EJEMPLO 1: Portfolio Simple (3 acciones)")
    print("="*60)
    
    payload = {
        "tickers": ["AAPL", "MSFT", "GOOGL"],
        "start_date": "2024-01-01",
        "initial_capital": 10000
    }
    
    print(f"\n📤 Enviando:")
    print(json.dumps(payload, indent=2))
    print()
    
    try:
        response = requests.post(
            f"{SERVICE_URL}/follow",
            json=payload,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            
            print("✅ Análisis completado!\n")
            
            # Métricas del portfolio
            metrics = data['analysis']['portfolio_metrics']
            print("📊 MÉTRICAS DEL PORTFOLIO:")
            print(f"   Período: {metrics['fecha_inicio']} a {metrics['fecha_actual']}")
            print(f"   Días invertidos: {metrics['dias_invertidos']}")
            print(f"   Valor inicial: ${metrics['valor_inicial']:,.2f}")
            print(f"   Valor actual:  ${metrics['valor_actual']:,.2f}")
            print(f"   Ganancia:      ${metrics['ganancia_perdida']:,.2f} ({metrics['retorno_total_pct']:.2f}%)")
            
            if metrics['cagr_pct']:
                print(f"   CAGR:          {metrics['cagr_pct']:.2f}%")
            
            print(f"   Volatilidad:   {metrics['volatilidad_anual_pct']:.2f}%")
            
            if metrics['sharpe_ratio']:
                print(f"   Sharpe Ratio:  {metrics['sharpe_ratio']:.2f}")
            
            print(f"   Max Drawdown:  {metrics['max_drawdown_pct']:.2f}%")
            
            # Análisis por acción
            ticker_analysis = data['analysis']['ticker_analysis']
            print(f"\n🎯 ANÁLISIS POR ACCIÓN:")
            print(f"   Mejor:  {ticker_analysis['mejor_accion']['ticker']} (+{ticker_analysis['mejor_accion']['retorno_pct']:.2f}%)")
            print(f"   Peor:   {ticker_analysis['peor_accion']['ticker']} ({ticker_analysis['peor_accion']['retorno_pct']:.2f}%)")
            print(f"   Mayor contribución: {ticker_analysis['mayor_contribucion']['ticker']}")
            
        else:
            print(f"❌ Error {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Error: {e}")

# ============================================
# EJEMPLO 2: Portfolio de las Joyas del Refine
# ============================================

def example_gems_portfolio():
    """Portfolio con las joyas reales encontradas"""
    print("\n" + "="*60)
    print("EJEMPLO 2: Portfolio de Joyas Reales")
    print("="*60)
    
    # Los tickers del notebook original
    tickers_from_refine = ["FCX", "IT", "EXPE", "KMB", "CLX", "CL", "WSM", "ZBRA", "ZTS", "UNP"]
    
    payload = {
        "tickers": tickers_from_refine,
        "start_date": "2024-11-20",
        "initial_capital": 10000
    }
    
    print(f"\n📤 Portfolio con {len(tickers_from_refine)} acciones desde Nov 2024")
    print()
    
    try:
        response = requests.post(
            f"{SERVICE_URL}/follow",
            json=payload,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            
            print("✅ Análisis completado!\n")
            
            metrics = data['analysis']['portfolio_metrics']
            ticker_analysis = data['analysis']['ticker_analysis']
            
            # Resumen ejecutivo
            print("📈 RESUMEN EJECUTIVO:")
            print(f"   Inversión inicial: ${metrics['valor_inicial']:,.2f}")
            print(f"   Valor actual:      ${metrics['valor_actual']:,.2f}")
            print(f"   Resultado:         ${metrics['ganancia_perdida']:,.2f}")
            print(f"   Retorno:           {metrics['retorno_total_pct']:.2f}%")
            print()
            
            # Top 3 y Bottom 3
            detalle = ticker_analysis['detalle_por_accion']
            detalle_sorted = sorted(detalle, key=lambda x: x['retorno_pct'], reverse=True)
            
            print("🏆 TOP 3 MEJORES:")
            for stock in detalle_sorted[:3]:
                print(f"   {stock['ticker']:6s} {stock['retorno_pct']:+7.2f}%  (${stock['ganancia_perdida']:+,.2f})")
            
            print("\n📉 TOP 3 PEORES:")
            for stock in detalle_sorted[-3:]:
                print(f"   {stock['ticker']:6s} {stock['retorno_pct']:+7.2f}%  (${stock['ganancia_perdida']:+,.2f})")
            
        else:
            print(f"❌ Error {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Error: {e}")

# ============================================
# EJEMPLO 3: Diferentes períodos
# ============================================

def example_time_periods():
    """Analizar mismo portfolio en diferentes períodos"""
    print("\n" + "="*60)
    print("EJEMPLO 3: Análisis de Diferentes Períodos")
    print("="*60)
    
    tickers = ["AAPL", "MSFT", "NVDA"]
    capital = 10000
    
    periods = [
        ("2024-01-01", "YTD 2024"),
        ("2023-01-01", "2 años"),
        ("2020-01-01", "5 años")
    ]
    
    for start_date, label in periods:
        print(f"\n📅 {label} (desde {start_date}):")
        
        try:
            response = requests.post(
                f"{SERVICE_URL}/follow",
                json={
                    "tickers": tickers,
                    "start_date": start_date,
                    "initial_capital": capital
                },
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                metrics = data['analysis']['portfolio_metrics']
                
                print(f"   Retorno: {metrics['retorno_total_pct']:+.2f}%")
                
                if metrics['cagr_pct']:
                    print(f"   CAGR:    {metrics['cagr_pct']:+.2f}%")
                
            else:
                print(f"   ❌ Error {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")

# ============================================
# EJEMPLO 4: Guardar resultados detallados
# ============================================

def example_save_detailed():
    """Obtener y guardar todos los detalles"""
    print("\n" + "="*60)
    print("EJEMPLO 4: Guardar Resultados Detallados")
    print("="*60)
    
    payload = {
        "tickers": ["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
        "start_date": "2024-01-01",
        "initial_capital": 50000
    }
    
    print(f"\n📤 Analizando portfolio de ${payload['initial_capital']:,.0f}...")
    
    try:
        response = requests.post(
            f"{SERVICE_URL}/follow",
            json=payload,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Guardar JSON completo
            filename = f"portfolio_analysis_{data['analyzed_at'][:10]}.json"
            
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            
            print(f"✅ Resultados guardados en: {filename}")
            
            # Mostrar resumen
            metrics = data['analysis']['portfolio_metrics']
            print(f"\n📊 Resumen:")
            print(f"   Retorno: ${metrics['ganancia_perdida']:,.2f} ({metrics['retorno_total_pct']:.2f}%)")
            print(f"   Archivo: {filename}")
            
        else:
            print(f"❌ Error {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

# ============================================
# EJECUTAR EJEMPLOS
# ============================================

if __name__ == "__main__":
    # Ejemplo 1: Simple
    example_simple_portfolio()
    
    # Ejemplo 2: Joyas del refine
    example_gems_portfolio()
    
    # Ejemplo 3: Diferentes períodos
    example_time_periods()
    
    # Ejemplo 4: Guardar detallado
    example_save_detailed()
    
    print("\n" + "="*60)
    print("✅ Ejemplos completados")
    print("="*60)
