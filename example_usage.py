"""
example_usage.py - Ejemplo de cómo consumir los datos del Warren Screener

Este script muestra diferentes formas de obtener y procesar los datos
"""

import requests
import json
import pandas as pd
from datetime import datetime

# ============================================
# CONFIGURACIÓN
# ============================================

# URL de tu servicio en Cloud Run
SERVICE_URL = "https://warren-screener-xxxxx.run.app"  # ← Cambia esto por tu URL

# ============================================
# OPCIÓN 1: OBTENER DATOS CON POST-PROCESAMIENTO AUTOMÁTICO
# ============================================

def get_analyzed_data_auto():
    """
    Obtiene datos del análisis con post-procesamiento automático
    El servidor hace todo el trabajo
    """
    print("🔍 Obteniendo datos del análisis...")
    
    response = requests.get(f"{SERVICE_URL}/analyze")
    
    if response.status_code == 200:
        data = response.json()
        
        print(f"✅ Análisis completado:")
        print(f"   Total analizados: {data.get('total_analyzed')}")
        print(f"   Candidatos encontrados: {data.get('candidates_count')}")
        print(f"   Desde caché: {data.get('from_cache')}")
        
        # Los datos post-procesados vienen incluidos
        if 'post_processed' in data and data['post_processed']:
            print("\n📊 Datos post-procesados disponibles:")
            
            # Métricas de portfolio
            if 'portfolio_metrics' in data['post_processed']:
                metrics = data['post_processed']['portfolio_metrics']
                print(f"   MOS promedio: {metrics.get('avg_mos', 0)*100:.2f}%")
                print(f"   ROIC promedio: {metrics.get('avg_roic', 0)*100:.2f}%")
                print(f"   Zona de compra: {metrics.get('buy_zone_count')} acciones")
            
            # Alertas
            if 'alerts' in data['post_processed']:
                alerts = data['post_processed']['alerts']
                print(f"\n🚨 {len(alerts)} alertas generadas")
                for alert in alerts[:3]:  # Mostrar primeras 3
                    print(f"   {alert['severity']}: {alert['message']}")
            
            # Análisis por sector
            if 'sector_analysis' in data['post_processed']:
                sectors = data['post_processed']['sector_analysis']
                print(f"\n🏭 {len(sectors)} sectores analizados")
                for sector, info in list(sectors.items())[:3]:
                    print(f"   {sector}: {info['count']} empresas")
        
        return data
    else:
        print(f"❌ Error: {response.status_code}")
        return None

# ============================================
# OPCIÓN 2: POST-PROCESAMIENTO MANUAL
# ============================================

def get_and_process_manually():
    """
    Obtiene datos crudos y los procesa localmente
    Útil si quieres tu propia lógica de procesamiento
    """
    print("🔍 Obteniendo datos crudos...")
    
    response = requests.get(f"{SERVICE_URL}/analyze")
    
    if response.status_code == 200:
        data = response.json()
        
        # Convertir a DataFrame para procesamiento local
        if 'results' in data:
            df = pd.DataFrame(data['results'])
            
            print(f"\n✅ {len(df)} resultados obtenidos")
            print("\n📊 Procesamiento local:")
            
            # Tu lógica personalizada aquí
            # Ejemplo: Filtrar por sector específico
            tech_stocks = df[df['Sector'] == 'Technology']
            print(f"   Acciones tech: {len(tech_stocks)}")
            
            # Ejemplo: Top 5 por MOS
            top_5 = df.nlargest(5, 'MOS')
            print(f"\n🏆 Top 5 por MOS:")
            for _, row in top_5.iterrows():
                print(f"   {row['Ticker']}: MOS {row['MOS']*100:.1f}%")
            
            return df
    
    return None

# ============================================
# OPCIÓN 3: ENVIAR A OTRO ENDPOINT PARA POST-PROCESAMIENTO
# ============================================

def send_to_post_processor():
    """
    Obtiene datos y los envía al endpoint de post-procesamiento
    """
    print("🔍 Obteniendo datos...")
    
    # 1. Obtener datos
    response = requests.get(f"{SERVICE_URL}/analyze")
    
    if response.status_code == 200:
        data = response.json()
        
        # 2. Enviar a post-procesamiento
        print("🔄 Enviando a post-procesamiento...")
        
        post_response = requests.post(
            f"{SERVICE_URL}/post-process",
            json=data,
            headers={'Content-Type': 'application/json'}
        )
        
        if post_response.status_code == 200:
            processed = post_response.json()
            print("✅ Post-procesamiento completado")
            
            # Acceder a watchlists
            if 'processed_data' in processed:
                pd_data = processed['processed_data']
                
                # Watchlist agresiva
                if 'watchlist_aggressive' in pd_data:
                    print(f"\n💪 Watchlist Agresiva:")
                    for stock in pd_data['watchlist_aggressive'][:5]:
                        print(f"   {stock['Ticker']}: MOS {stock['MOS']*100:.1f}%")
                
                # Watchlist conservadora
                if 'watchlist_conservative' in pd_data:
                    print(f"\n🛡️  Watchlist Conservadora:")
                    for stock in pd_data['watchlist_conservative'][:5]:
                        print(f"   {stock['Ticker']}: ROIC {stock['ROIC']*100:.1f}%")
            
            return processed
    
    return None

# ============================================
# OPCIÓN 4: INTEGRACIÓN CON TU PROPIO SCRIPT
# ============================================

def integrate_with_your_logic(results_data):
    """
    Función que recibe los datos y hace tu lógica personalizada
    
    Args:
        results_data: Dict con los resultados del análisis
    """
    print("🎯 Ejecutando lógica personalizada...")
    
    if 'results' not in results_data:
        print("❌ No hay resultados")
        return
    
    df = pd.DataFrame(results_data['results'])
    
    # ====== TU LÓGICA AQUÍ ======
    
    # Ejemplo 1: Crear tu propia puntuación
    df['custom_score'] = (
        df['MOS'] * 0.5 +  # 50% peso al MOS
        (df['ROIC'] / df['ROIC'].max()) * 0.3 +  # 30% peso al ROIC
        (df['Piotroski'] / 9) * 0.2  # 20% peso a Piotroski
    )
    
    top_custom = df.nlargest(10, 'custom_score')
    print("\n🎯 Top 10 según tu scoring:")
    for _, row in top_custom.iterrows():
        print(f"   {row['Ticker']}: Score {row['custom_score']:.3f}")
    
    # Ejemplo 2: Filtrar por tus criterios
    your_criteria = df[
        (df['MOS'] > 0.15) &  # MOS > 15%
        (df['ROIC'] > 0.12) &  # ROIC > 12%
        (df['Piotroski'] >= 6)  # Piotroski >= 6
    ]
    
    print(f"\n✅ {len(your_criteria)} acciones cumplen tus criterios")
    
    # Ejemplo 3: Exportar a tu formato
    output_file = f"mis_picks_{datetime.now().strftime('%Y%m%d')}.csv"
    your_criteria.to_csv(output_file, index=False)
    print(f"\n💾 Guardado en: {output_file}")
    
    # Ejemplo 4: Enviar a tu base de datos
    # send_to_database(your_criteria)
    
    # Ejemplo 5: Enviar alertas
    # send_email_alerts(your_criteria)
    
    return your_criteria

# ============================================
# OPCIÓN 5: CONSUMO PERIÓDICO (CRON/SCHEDULER)
# ============================================

def scheduled_analysis():
    """
    Función para ejecutar en un cron job o scheduler
    """
    print(f"⏰ Análisis programado - {datetime.now()}")
    
    # Obtener datos
    data = get_analyzed_data_auto()
    
    if data and 'results' in data:
        df = pd.DataFrame(data['results'])
        
        # Filtrar alertas importantes
        urgent = df[df['MOS'] > 0.40]  # MOS > 40%
        
        if len(urgent) > 0:
            print(f"\n🚨 ¡{len(urgent)} OPORTUNIDADES URGENTES!")
            
            # Aquí puedes:
            # 1. Enviar email
            # 2. Enviar notificación push
            # 3. Actualizar dashboard
            # 4. Guardar en base de datos
            
            for _, row in urgent.iterrows():
                print(f"   🔥 {row['Ticker']}: MOS {row['MOS']*100:.1f}%")
                # send_telegram_alert(row)
                # send_email_alert(row)
    
    print("✅ Análisis programado completado")

# ============================================
# EJECUTAR EJEMPLOS
# ============================================

if __name__ == "__main__":
    print("="*60)
    print("Warren Screener - Ejemplos de Uso")
    print("="*60)
    
    # Opción 1: Obtener con post-procesamiento automático
    print("\n" + "="*60)
    print("OPCIÓN 1: Post-procesamiento Automático")
    print("="*60)
    data = get_analyzed_data_auto()
    
    # Opción 2: Procesamiento manual
    if data:
        print("\n" + "="*60)
        print("OPCIÓN 2: Procesamiento Manual")
        print("="*60)
        df = get_and_process_manually()
        
        # Opción 4: Tu lógica personalizada
        if df is not None:
            print("\n" + "="*60)
            print("OPCIÓN 4: Lógica Personalizada")
            print("="*60)
            integrate_with_your_logic(data)
    
    print("\n" + "="*60)
    print("✅ Ejemplos completados")
    print("="*60)
