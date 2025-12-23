"""
portfolio_refiner.py - Portfolio Manager Review
Refina los resultados del análisis aplicando ajustes realistas por sector
"""

import pandas as pd
import numpy as np
import json

class PortfolioRefiner:
    """
    Portfolio Manager que revisa y ajusta los resultados del screener
    aplicando límites de crecimiento realistas por sector
    """
    
    # Límites de crecimiento realistas por sector
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
        'Consumer Cyclical': 0.10,
        'Basic Materials': 0.07,
        'N/A': 0.10                  # Default
    }
    
    def __init__(self, results_data):
        """
        Args:
            results_data: Dict con los resultados del análisis o DataFrame
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
        else:
            print("❌ Formato de datos no válido")
            return False
        
        if self.df is None or self.df.empty:
            print("❌ No hay datos para analizar")
            return False
        
        print(f"✅ Cargados {len(self.df)} resultados para refinar")
        return True
    
    def refine_portfolio(self):
        """
        Ejecuta el análisis de refinamiento completo
        """
        if self.df is None or self.df.empty:
            return None
        
        report = []
        
        for index, row in self.df.iterrows():
            ticker = row.get('Ticker', 'UNKNOWN')
            sector = row.get('Sector', 'N/A')
            price = row.get('Price', 0)
            old_mos = row.get('MOS', 0)
            old_growth = row.get('Growth_Est', 0)
            roic = row.get('ROIC', 0)
            piotroski = row.get('Piotroski', 0)
            intrinsic = row.get('Intrinsic', 0)
            
            # --- LÓGICA DE FILTRADO ---
            category = "❓ Revisar"
            reason = ""
            new_intrinsic = intrinsic
            new_mos = old_mos
            
            # A. ELIMINACIÓN DE FINANCIEROS (DCF Inválido)
            if sector == 'Financial Services':
                category = "🏦 Banco/Seguro"
                reason = "Ignorar DCF. Valorar por Price/Book."
                new_mos = 0  # Anulamos MOS para no confundir
            
            # B. AJUSTE DE CRECIMIENTO (Reality Check)
            else:
                cap = self.SECTOR_CAPS.get(sector, 0.10)  # Default 10%
                
                # Si el modelo anterior fue muy optimista, castigamos
                if old_growth > cap:
                    adj_growth = cap
                    reason = f"Crecimiento ajustado de {old_growth:.1%} a {cap:.1%} (Sector)."
                    
                    # Recalculamos DCF rápido con el nuevo crecimiento
                    # Factor de corrección aproximado:
                    correction_factor = (1 + adj_growth) / (1 + old_growth) if old_growth > 0 else 1
                    
                    # Castigamos el valor intrínseco proporcionalmente (heurístico)
                    new_intrinsic = intrinsic * (correction_factor ** 2.5)  # Elevado para ser conservador
                    
                    if new_intrinsic > 0 and price > 0:
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
                        if not reason:
                            reason = "Buen descuento + Calidad aceptable"
                    else:
                        category = "⚠️ Trampa Valor"
                        reason += " MOS alto pero Calidad Media."
                        
                elif new_mos > 0:
                    category = "⚖️ Precio Justo"
                    if not reason:
                        reason = "Valoración razonable"
                else:
                    category = "❌ Cara/Ajustada"
                    if "ajustado" in reason.lower():
                        reason += " Ya no es atractiva tras ajuste."
                    else:
                        reason = "Sobrevalorada según DCF ajustado"
                
                # D. DETECTOR DE TRAMPAS DE DEUDA/CÍCLICAS
                # Si el descuento es absurdo (>60%) y no es tech/biotech, sospechamos
                if new_mos > 0.60 and sector not in ['Technology', 'Healthcare']:
                    category = "⚠️ Trampa Valor?"
                    reason = "Descuento sospechoso. Mercado descuenta quiebra o caída cíclica."
            
            report.append({
                'Ticker': ticker,
                'Sector': sector,
                'Category': category,
                'Reason': reason,
                'Original_MOS': old_mos,
                'Adjusted_MOS': new_mos,
                'Original_Growth': old_growth,
                'Sector_Cap_Growth': self.SECTOR_CAPS.get(sector, 0.10),
                'ROIC': roic,
                'Piotroski': piotroski,
                'Price': price,
                'Original_Intrinsic': intrinsic,
                'Adjusted_Intrinsic': new_intrinsic
            })
        
        # Crear DF y ordenar
        self.refined_df = pd.DataFrame(report)
        
        # Orden de prioridad
        cat_order = {
            "💎 JOYA REAL": 0,
            "✅ Oportunidad": 1,
            "⚖️ Precio Justo": 2,
            "⚠️ Trampa Valor?": 3,
            "🏦 Banco/Seguro": 4,
            "❌ Cara/Ajustada": 5,
            "⚠️ Trampa Valor": 6
        }
        
        self.refined_df['_sort'] = self.refined_df['Category'].map(cat_order)
        self.refined_df = self.refined_df.sort_values(
            by=['_sort', 'Adjusted_MOS'], 
            ascending=[True, False]
        ).drop('_sort', axis=1)
        
        return self.refined_df
    
    def get_summary_stats(self):
        """Genera estadísticas del refinamiento"""
        if self.refined_df is None or self.refined_df.empty:
            return {}
        
        stats = {
            'total_reviewed': len(self.refined_df),
            'by_category': self.refined_df['Category'].value_counts().to_dict(),
            'gems_count': len(self.refined_df[self.refined_df['Category'] == '💎 JOYA REAL']),
            'opportunities_count': len(self.refined_df[self.refined_df['Category'] == '✅ Oportunidad']),
            'value_traps_count': len(self.refined_df[self.refined_df['Category'].str.contains('Trampa', na=False)]),
            'avg_mos_adjustment': float((self.refined_df['Adjusted_MOS'] - self.refined_df['Original_MOS']).mean()),
            'stocks_with_growth_adjustment': len(self.refined_df[self.refined_df['Reason'].str.contains('ajustado', na=False)])
        }
        
        return stats
    
    def get_gems(self):
        """Retorna solo las JOYAS REALES"""
        if self.refined_df is None:
            return []
        
        gems = self.refined_df[self.refined_df['Category'] == '💎 JOYA REAL']
        return gems.to_dict('records')
    
    def get_opportunities(self):
        """Retorna las Oportunidades"""
        if self.refined_df is None:
            return []
        
        opps = self.refined_df[self.refined_df['Category'] == '✅ Oportunidad']
        return opps.to_dict('records')
    
    def get_value_traps(self):
        """Retorna posibles trampas de valor"""
        if self.refined_df is None:
            return []
        
        traps = self.refined_df[self.refined_df['Category'].str.contains('Trampa', na=False)]
        return traps.to_dict('records')
    
    def export_to_dict(self):
        """Exporta todos los datos refinados"""
        if self.refined_df is None:
            return None
        
        return {
            'refined_results': self.refined_df.to_dict('records'),
            'summary': self.get_summary_stats(),
            'gems': self.get_gems(),
            'opportunities': self.get_opportunities(),
            'value_traps': self.get_value_traps()
        }
    
    def refine_all(self):
        """Pipeline completo de refinamiento"""
        print("="*60)
        print("🧠 Portfolio Manager Review Iniciado")
        print("="*60)
        
        if not self.load_data():
            return None
        
        print("\n🔍 Analizando y ajustando resultados por sector...")
        self.refine_portfolio()
        
        stats = self.get_summary_stats()
        
        print("\n" + "="*60)
        print("✅ Refinamiento Completado")
        print("="*60)
        print(f"\n📊 Resultados:")
        print(f"   💎 Joyas Reales: {stats['gems_count']}")
        print(f"   ✅ Oportunidades: {stats['opportunities_count']}")
        print(f"   ⚠️  Trampas de Valor: {stats['value_traps_count']}")
        print(f"   📉 Ajustes de crecimiento: {stats['stocks_with_growth_adjustment']}")
        print(f"   📊 Ajuste MOS promedio: {stats['avg_mos_adjustment']*100:.2f}%")
        
        print("\n📋 Por Categoría:")
        for cat, count in stats['by_category'].items():
            print(f"   {cat}: {count}")
        
        print("="*60)
        
        return self.export_to_dict()


# Función helper
def refine_results(results_data):
    """
    Función de conveniencia para refinar resultados
    
    Args:
        results_data: Dict con resultados del análisis o DataFrame
        
    Returns:
        Dict con datos refinados
    """
    refiner = PortfolioRefiner(results_data)
    return refiner.refine_all()


# Para uso standalone
if __name__ == "__main__":
    print("Portfolio Refiner listo para recibir datos")
    print("Uso:")
    print("  from portfolio_refiner import refine_results")
    print("  refined = refine_results(results_data)")
