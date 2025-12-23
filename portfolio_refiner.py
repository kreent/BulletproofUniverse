"""
portfolio_refiner.py - Portfolio Manager Review
Script EXACTO del segundo análisis proporcionado
"""

import pandas as pd
import numpy as np
import json

def portfolio_manager_review(df_input):
    """
    Función EXACTA del script original
    Recibe DataFrame y retorna DataFrame refinado
    """
    if df_input is None or df_input.empty:
        print("❌ No hay datos para analizar. Ejecuta el paso anterior primero.")
        return None

    df = df_input.copy()

    # 1. DEFINIR LÍMITES DE CRECIMIENTO REALISTAS POR SECTOR
    # Un humano sabe que el Cloro no crece al 14%. El código ahora lo sabrá.
    SECTOR_CAPS = {
        'Consumer Defensive': 0.06,  # Max 6%
        'Utilities': 0.05,           # Max 5%
        'Energy': 0.05,              # Max 5% (Cíclico)
        'Industrials': 0.08,         # Max 8%
        'Financial Services': 0.00,  # Caso especial
        'Real Estate': 0.06,
        'Technology': 0.15,          # Permitimos alto crecimiento
        'Healthcare': 0.12,
        'Communication Services': 0.12,
        'Consumer Cyclical': 0.10
    }

    report = []

    for index, row in df.iterrows():
        ticker = row['Ticker']
        sector = row['Sector']
        price = row['Price']
        old_mos = row['MOS']
        old_growth = row['Growth_Est']
        roic = row['ROIC']
        piotroski = row['Piotroski']

        # --- LÓGICA DE FILTRADO ---

        category = "❓ Revisar"
        reason = ""
        new_intrinsic = row['Intrinsic']
        new_mos = old_mos

        # A. ELIMINACIÓN DE FINANCIEROS (DCF Invalido)
        if sector == 'Financial Services':
            category = "🏦 Banco/Seguro"
            reason = "Ignorar DCF. Valorar por Price/Book."
            new_mos = 0  # Anulamos MOS para no confundir

        # B. AJUSTE DE CRECIMIENTO (Reality Check)
        else:
            cap = SECTOR_CAPS.get(sector, 0.10)  # Default 10%

            # Si el modelo anterior fue muy optimista, castigamos
            if old_growth > cap:
                adj_growth = cap
                reason = f"Crecimiento ajustado de {old_growth:.1%} a {cap:.1%} (Sector)."

                # Recalculamos DCF rápido con el nuevo crecimiento (Simplificado para ajuste)
                # Asumimos que el Intrinsic es linealmente sensible al crecimiento en el Stage 1
                # Factor de corrección aproximado:
                correction_factor = (1 + adj_growth) / (1 + old_growth)
                # Castigamos el valor intrínseco proporcionalmente (heurístico)
                new_intrinsic = row['Intrinsic'] * (correction_factor ** 2.5)  # Elevado para ser conservador

                if new_intrinsic > 0:
                    new_mos = (new_intrinsic - price) / new_intrinsic
                else:
                    new_mos = -0.99

            # C. CLASIFICACIÓN FINAL
            if new_mos > 0.15:
                # Si sigue barata tras el ajuste
                if roic > 0.15 and piotroski >= 6:
                    category = "💎 JOYA REAL"
                    if not reason: 
                        reason = "Alta Calidad + Precio Justo"
                elif roic > 0.10:
                    category = "✅ Oportunidad"
                else:
                    category = "⚠️ Trampa Valor"
                    reason += " MOS alto pero Calidad Media."
            elif new_mos > 0:
                category = "⚖️ Precio Justo"
            else:
                category = "❌ Cara/Ajustada"
                if "ajustado" in reason: 
                    reason += " Ya no es atractiva tras ajuste."

            # D. DETECTOR DE TRAMPAS DE DEUDA/CÍCLICAS
            # Si el descuento es absurdo (>60%) y no es tech/biotech, sospechamos
            if new_mos > 0.60 and sector not in ['Technology', 'Healthcare']:
                category = "⚠️ Trampa Valor?"
                reason = "Descuento sospechoso. Mercado descuenta quiebra o caída cíclica."

        report.append({
            'Ticker': ticker,
            'Sector': sector,
            'Cat': category,
            'Why': reason,
            'Old_MOS': old_mos,
            'Real_MOS': new_mos,
            'ROIC': roic,
            'Piotroski': piotroski
        })

    # Crear DF y ordenar
    res = pd.DataFrame(report)

    # Orden de prioridad: Joyas -> Oportunidades -> Precio Justo -> Bancos -> Resto
    cat_order = {
        "💎 JOYA REAL": 0, 
        "✅ Oportunidad": 1, 
        "⚖️ Precio Justo": 2, 
        "⚠️ Trampa Valor?": 3, 
        "🏦 Banco/Seguro": 4, 
        "❌ Cara/Ajustada": 5, 
        "⚠️ Trampa Valor": 6
    }
    res['Sort'] = res['Cat'].map(cat_order)
    res = res.sort_values(by=['Sort', 'Real_MOS'], ascending=[True, False]).drop('Sort', axis=1)

    return res


class PortfolioRefiner:
    """
    Wrapper para usar con el endpoint /refine
    """
    
    def __init__(self, results_data):
        """
        Args:
            results_data: Dict con los resultados del análisis
        """
        self.raw_data = results_data
        self.df = None
        self.refined_df = None
        
    def load_data(self):
        """Convierte los resultados a DataFrame"""
        if isinstance(self.raw_data, pd.DataFrame):
            self.df = self.raw_data.copy()
        elif isinstance(self.raw_data, dict) and 'results' in self.raw_data:
            self.df = pd.DataFrame(self.raw_data['results'])
        elif isinstance(self.raw_data, list):
            self.df = pd.DataFrame(self.raw_data)
        else:
            print("❌ Formato de datos no válido")
            return False
        
        if self.df is None or self.df.empty:
            print("❌ No hay datos para analizar")
            return False
        
        print(f"✅ Cargados {len(self.df)} resultados para refinar")
        return True
    
    def refine_all(self):
        """Pipeline completo de refinamiento"""
        print("="*60)
        print("🧠 El 'Portfolio Manager' está revisando los resultados...")
        print("="*60)
        
        if not self.load_data():
            return None
        
        # Ejecutar refinamiento con la función EXACTA del script original
        self.refined_df = portfolio_manager_review(self.df)
        
        if self.refined_df is None or self.refined_df.empty:
            print("❌ Error en refinamiento")
            return None
        
        # Generar estadísticas
        stats = self.get_summary_stats()
        
        print("\n" + "="*60)
        print("✅ Refinamiento Completado")
        print("="*60)
        print(f"\n📊 Resultados:")
        print(f"   💎 Joyas Reales: {stats['gems_count']}")
        print(f"   ✅ Oportunidades: {stats['opportunities_count']}")
        print(f"   ⚖️ Precio Justo: {stats['fair_count']}")
        print(f"   ⚠️  Trampas de Valor: {stats['value_traps_count']}")
        print(f"   🏦 Bancos/Seguros: {stats['banks_count']}")
        
        print("\n📋 Por Categoría:")
        for cat, count in stats['by_category'].items():
            print(f"   {cat}: {count}")
        
        print("="*60)
        
        return self.export_to_dict()
    
    def get_summary_stats(self):
        """Genera estadísticas del refinamiento"""
        if self.refined_df is None or self.refined_df.empty:
            return {}
        
        stats = {
            'total_reviewed': len(self.refined_df),
            'by_category': self.refined_df['Cat'].value_counts().to_dict(),
            'gems_count': len(self.refined_df[self.refined_df['Cat'] == '💎 JOYA REAL']),
            'opportunities_count': len(self.refined_df[self.refined_df['Cat'] == '✅ Oportunidad']),
            'fair_count': len(self.refined_df[self.refined_df['Cat'] == '⚖️ Precio Justo']),
            'value_traps_count': len(self.refined_df[self.refined_df['Cat'].str.contains('Trampa', na=False)]),
            'banks_count': len(self.refined_df[self.refined_df['Cat'] == '🏦 Banco/Seguro']),
            'avg_mos_change': float((self.refined_df['Real_MOS'] - self.refined_df['Old_MOS']).mean())
        }
        
        return stats
    
    def export_to_dict(self):
        """Exporta todos los datos refinados"""
        if self.refined_df is None:
            return None
        
        return {
            'refined_results': self.refined_df.to_dict('records'),
            'summary': self.get_summary_stats(),
            'gems': self.refined_df[self.refined_df['Cat'] == '💎 JOYA REAL'].to_dict('records'),
            'opportunities': self.refined_df[self.refined_df['Cat'] == '✅ Oportunidad'].to_dict('records'),
            'fair_value': self.refined_df[self.refined_df['Cat'] == '⚖️ Precio Justo'].to_dict('records'),
            'value_traps': self.refined_df[self.refined_df['Cat'].str.contains('Trampa', na=False)].to_dict('records'),
            'banks': self.refined_df[self.refined_df['Cat'] == '🏦 Banco/Seguro'].to_dict('records')
        }


# Para uso standalone
if __name__ == "__main__":
    print("Portfolio Refiner listo para recibir datos")
    print("Uso:")
    print("  from portfolio_refiner import PortfolioRefiner")
    print("  refiner = PortfolioRefiner(results_data)")
    print("  refined = refiner.refine_all()")

