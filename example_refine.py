"""
example_refine.py - Ejemplo de uso del Portfolio Manager Review

Muestra cómo usar el endpoint /refine para obtener análisis refinado
"""

import requests
import json
import pandas as pd

# ============================================
# CONFIGURACIÓN
# ============================================

SERVICE_URL = "https://warren-screener-xxxxx.run.app"  # ← Cambia por tu URL

# ============================================
# OPCIÓN 1: REFINAR USANDO DATOS DEL CACHÉ
# ============================================

def refine_from_cache():
    """
    Obtiene los datos del último análisis en caché y los refina
    """
    print("🔍 Refinando datos del último análisis...")
    
    response = requests.get(f"{SERVICE_URL}/refine")
    
    if response.status_code == 200:
        data = response.json()
        
        print("✅ Refinamiento completado")
        print(f"\n📊 Resumen:")
        
        summary = data['refined_data']['summary']
        print(f"   Total revisado: {summary['total_reviewed']}")
        print(f"   💎 Joyas Reales: {summary['gems_count']}")
        print(f"   ✅ Oportunidades: {summary['opportunities_count']}")
        print(f"   ⚠️  Trampas de Valor: {summary['value_traps_count']}")
        print(f"   📉 Ajustes de crecimiento: {summary['stocks_with_growth_adjustment']}")
        
        # Mostrar JOYAS REALES
        if data['refined_data']['gems']:
            print("\n💎 JOYAS REALES encontradas:")
            for gem in data['refined_data']['gems']:
                print(f"   {gem['Ticker']} ({gem['Sector']})")
                print(f"      MOS Ajustado: {gem['Adjusted_MOS']*100:.1f}%")
                print(f"      ROIC: {gem['ROIC']*100:.1f}%")
                print(f"      Razón: {gem['Reason']}")
                print()
        
        return data
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)
        return None

# ============================================
# OPCIÓN 2: REFINAR DATOS ESPECÍFICOS
# ============================================

def refine_custom_data():
    """
    Primero obtiene análisis, luego refina
    """
    print("🔍 Obteniendo análisis...")
    
    # 1. Obtener análisis
    response = requests.get(f"{SERVICE_URL}/analyze")
    
    if response.status_code != 200:
        print(f"❌ Error obteniendo análisis: {response.status_code}")
        return None
    
    analysis_data = response.json()
    
    # 2. Refinar
    print("🧠 Refinando resultados...")
    
    refine_response = requests.post(
        f"{SERVICE_URL}/refine",
        json=analysis_data,
        headers={'Content-Type': 'application/json'}
    )
    
    if refine_response.status_code == 200:
        refined_data = refine_response.json()
        
        print("✅ Refinamiento completado")
        
        # Acceder a diferentes categorías
        rd = refined_data['refined_data']
        
        print("\n📋 Por Categoría:")
        for cat, count in rd['summary']['by_category'].items():
            print(f"   {cat}: {count}")
        
        return refined_data
    else:
        print(f"❌ Error en refinamiento: {refine_response.status_code}")
        return None

# ============================================
# OPCIÓN 3: ANÁLISIS DETALLADO DE RESULTADOS
# ============================================

def detailed_analysis():
    """
    Análisis detallado mostrando ajustes
    """
    print("🔍 Ejecutando análisis detallado...")
    
    response = requests.get(f"{SERVICE_URL}/refine")
    
    if response.status_code != 200:
        print(f"❌ Error: {response.status_code}")
        return None
    
    data = response.json()
    refined_results = data['refined_data']['refined_results']
    
    # Convertir a DataFrame para mejor análisis
    df = pd.DataFrame(refined_results)
    
    print("\n" + "="*80)
    print("📊 ANÁLISIS DETALLADO DE AJUSTES")
    print("="*80)
    
    # 1. Acciones con ajuste de crecimiento
    adjusted = df[df['Reason'].str.contains('ajustado', na=False)]
    
    if len(adjusted) > 0:
        print(f"\n📉 {len(adjusted)} acciones con crecimiento ajustado:")
        print()
        for _, row in adjusted.head(10).iterrows():
            print(f"   {row['Ticker']} ({row['Sector']})")
            print(f"      Crecimiento: {row['Original_Growth']*100:.1f}% → {row['Sector_Cap_Growth']*100:.1f}%")
            print(f"      MOS: {row['Original_MOS']*100:.1f}% → {row['Adjusted_MOS']*100:.1f}%")
            print(f"      Cambio: {(row['Adjusted_MOS'] - row['Original_MOS'])*100:.1f}%")
            print()
    
    # 2. Mayor cambio en MOS
    df['mos_change'] = df['Adjusted_MOS'] - df['Original_MOS']
    biggest_changes = df.nsmallest(5, 'mos_change')
    
    print("\n📊 Top 5 mayores ajustes negativos en MOS:")
    print()
    for _, row in biggest_changes.iterrows():
        print(f"   {row['Ticker']}: {row['mos_change']*100:.1f}% de cambio")
        print(f"      {row['Reason']}")
        print()
    
    # 3. Categorías finales
    print("\n📋 DISTRIBUCIÓN FINAL:")
    print()
    category_dist = df['Category'].value_counts()
    for cat, count in category_dist.items():
        pct = (count / len(df)) * 100
        print(f"   {cat}: {count} ({pct:.1f}%)")
    
    # 4. Estadísticas por sector
    print("\n🏭 AJUSTES POR SECTOR:")
    print()
    sector_stats = df.groupby('Sector').agg({
        'Original_Growth': 'mean',
        'Sector_Cap_Growth': 'first',
        'mos_change': 'mean'
    }).round(3)
    
    print(sector_stats.to_string())
    
    return df

# ============================================
# OPCIÓN 4: FILTRAR SOLO LO MEJOR
# ============================================

def get_best_picks():
    """
    Obtiene solo las mejores oportunidades
    """
    print("💎 Obteniendo mejores picks...")
    
    response = requests.get(f"{SERVICE_URL}/refine")
    
    if response.status_code != 200:
        print(f"❌ Error: {response.status_code}")
        return None
    
    data = response.json()
    rd = data['refined_data']
    
    # Combinar Joyas y Oportunidades
    best_picks = rd['gems'] + rd['opportunities']
    
    if best_picks:
        print(f"\n✅ {len(best_picks)} picks recomendados:")
        print()
        
        df = pd.DataFrame(best_picks)
        df = df.sort_values('Adjusted_MOS', ascending=False)
        
        print(df[['Ticker', 'Category', 'Adjusted_MOS', 'ROIC', 'Piotroski', 'Sector']].to_string(index=False))
        
        # Exportar a CSV
        output_file = f"best_picks_{pd.Timestamp.now().strftime('%Y%m%d')}.csv"
        df.to_csv(output_file, index=False)
        print(f"\n💾 Guardado en: {output_file}")
        
        return df
    else:
        print("⚠️  No se encontraron picks recomendados")
        return None

# ============================================
# OPCIÓN 5: COMPARAR ANTES/DESPUÉS
# ============================================

def compare_before_after():
    """
    Compara resultados originales vs refinados
    """
    print("🔍 Comparando análisis original vs refinado...")
    
    # Obtener ambos
    analysis = requests.get(f"{SERVICE_URL}/analyze").json()
    refined = requests.get(f"{SERVICE_URL}/refine").json()
    
    original_df = pd.DataFrame(analysis['results'])
    refined_df = pd.DataFrame(refined['refined_data']['refined_results'])
    
    print("\n" + "="*80)
    print("📊 COMPARACIÓN: ORIGINAL vs REFINADO")
    print("="*80)
    
    # Estadísticas generales
    print("\n📈 ESTADÍSTICAS GENERALES:")
    print(f"   Total acciones: {len(original_df)}")
    print(f"   MOS promedio original: {original_df['MOS'].mean()*100:.2f}%")
    print(f"   MOS promedio refinado: {refined_df['Adjusted_MOS'].mean()*100:.2f}%")
    print(f"   Cambio promedio: {(refined_df['Adjusted_MOS'].mean() - original_df['MOS'].mean())*100:.2f}%")
    
    # Comparar Top 10
    print("\n🏆 COMPARACIÓN TOP 10:")
    print("\nORIGINAL:")
    original_top = original_df.nlargest(10, 'MOS')
    print(original_top[['Ticker', 'MOS', 'Sector']].to_string(index=False))
    
    print("\nREFINADO:")
    refined_top = refined_df[refined_df['Category'].isin(['💎 JOYA REAL', '✅ Oportunidad'])].head(10)
    print(refined_top[['Ticker', 'Adjusted_MOS', 'Category', 'Sector']].to_string(index=False))
    
    # Stocks que salieron del top 10
    original_top_tickers = set(original_top['Ticker'])
    refined_top_tickers = set(refined_top['Ticker'])
    
    removed = original_top_tickers - refined_top_tickers
    added = refined_top_tickers - original_top_tickers
    
    if removed:
        print(f"\n❌ Removidos del Top 10 tras ajuste: {', '.join(removed)}")
    if added:
        print(f"\n✅ Nuevos en Top 10 tras ajuste: {', '.join(added)}")
    
    return {
        'original': original_df,
        'refined': refined_df
    }

# ============================================
# EJECUTAR EJEMPLOS
# ============================================

if __name__ == "__main__":
    print("="*80)
    print("Portfolio Manager Review - Ejemplos de Uso")
    print("="*80)
    
    # Opción 1: Refinar desde caché (más simple)
    print("\n" + "="*80)
    print("OPCIÓN 1: Refinar desde Caché")
    print("="*80)
    refine_from_cache()
    
    # Opción 3: Análisis detallado
    print("\n" + "="*80)
    print("OPCIÓN 3: Análisis Detallado")
    print("="*80)
    detailed_analysis()
    
    # Opción 4: Solo lo mejor
    print("\n" + "="*80)
    print("OPCIÓN 4: Mejores Picks")
    print("="*80)
    get_best_picks()
    
    print("\n" + "="*80)
    print("✅ Ejemplos completados")
    print("="*80)
