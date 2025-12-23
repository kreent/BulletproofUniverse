"""
post_processor.py - Script de Post-Procesamiento
Recibe los resultados del análisis y hace procesamiento adicional
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json

class ResultsPostProcessor:
    """
    Procesa los resultados del Warren Screener
    """
    
    def __init__(self, results_data):
        """
        Args:
            results_data: Dict con los resultados del análisis
        """
        self.raw_results = results_data
        self.df = None
        self.processed_data = {}
        
    def load_data(self):
        """Convierte los resultados a DataFrame"""
        if 'results' in self.raw_results:
            self.df = pd.DataFrame(self.raw_results['results'])
            print(f"✅ Cargados {len(self.df)} resultados para procesar")
            return True
        else:
            print("❌ No hay resultados para procesar")
            return False
    
    def categorize_by_sector(self):
        """Agrupa resultados por sector"""
        if self.df is None or self.df.empty:
            return {}
        
        sector_analysis = {}
        
        for sector in self.df['Sector'].unique():
            sector_df = self.df[self.df['Sector'] == sector]
            
            sector_analysis[sector] = {
                'count': len(sector_df),
                'avg_mos': sector_df['MOS'].mean() if 'MOS' in sector_df else None,
                'avg_roic': sector_df['ROIC'].mean() if 'ROIC' in sector_df else None,
                'avg_piotroski': sector_df['Piotroski'].mean() if 'Piotroski' in sector_df else None,
                'best_pick': sector_df.nlargest(1, 'MOS')[['Ticker', 'MOS']].to_dict('records')[0] if len(sector_df) > 0 else None
            }
        
        self.processed_data['sector_analysis'] = sector_analysis
        print(f"✅ Análisis por sector completado: {len(sector_analysis)} sectores")
        return sector_analysis
    
    def identify_top_opportunities(self, n=10):
        """Identifica las mejores oportunidades"""
        if self.df is None or self.df.empty:
            return []
        
        # Top por MOS
        top_mos = self.df.nlargest(n, 'MOS')[['Ticker', 'Price', 'Intrinsic', 'MOS', 'ROIC', 'Piotroski', 'Sector']]
        
        # Top por ROIC
        top_roic = self.df.nlargest(n, 'ROIC')[['Ticker', 'ROIC', 'MOS', 'Piotroski', 'Sector']]
        
        # Top por Piotroski
        top_piotroski = self.df.nlargest(n, 'Piotroski')[['Ticker', 'Piotroski', 'ROIC', 'MOS', 'Sector']]
        
        self.processed_data['top_opportunities'] = {
            'top_mos': top_mos.to_dict('records'),
            'top_roic': top_roic.to_dict('records'),
            'top_piotroski': top_piotroski.to_dict('records')
        }
        
        print(f"✅ Top {n} oportunidades identificadas")
        return self.processed_data['top_opportunities']
    
    def calculate_portfolio_metrics(self):
        """Calcula métricas de portfolio"""
        if self.df is None or self.df.empty:
            return {}
        
        # Filtrar solo empresas con MOS positivo
        buy_zone = self.df[self.df['MOS'] > 0.10] if 'MOS' in self.df.columns else pd.DataFrame()
        
        portfolio_metrics = {
            'total_candidates': len(self.df),
            'buy_zone_count': len(buy_zone),
            'avg_mos': float(self.df['MOS'].mean()) if 'MOS' in self.df else None,
            'avg_roic': float(self.df['ROIC'].mean()) if 'ROIC' in self.df else None,
            'avg_piotroski': float(self.df['Piotroski'].mean()) if 'Piotroski' in self.df else None,
            'median_price': float(self.df['Price'].median()) if 'Price' in self.df else None,
            'total_intrinsic_value': float(buy_zone['Intrinsic'].sum()) if len(buy_zone) > 0 and 'Intrinsic' in buy_zone else None,
            'total_market_value': float(buy_zone['Price'].sum()) if len(buy_zone) > 0 and 'Price' in buy_zone else None
        }
        
        # Calcular discount total
        if portfolio_metrics['total_intrinsic_value'] and portfolio_metrics['total_market_value']:
            portfolio_metrics['portfolio_discount'] = (
                portfolio_metrics['total_intrinsic_value'] - portfolio_metrics['total_market_value']
            ) / portfolio_metrics['total_intrinsic_value']
        
        self.processed_data['portfolio_metrics'] = portfolio_metrics
        print(f"✅ Métricas de portfolio calculadas")
        return portfolio_metrics
    
    def generate_alerts(self):
        """Genera alertas basadas en condiciones especiales"""
        if self.df is None or self.df.empty:
            return []
        
        alerts = []
        
        # Alert 1: Super Bargains (MOS > 50%)
        super_bargains = self.df[self.df['MOS'] > 0.50]
        if len(super_bargains) > 0:
            for _, row in super_bargains.iterrows():
                alerts.append({
                    'type': 'SUPER_BARGAIN',
                    'severity': 'HIGH',
                    'ticker': row['Ticker'],
                    'message': f"{row['Ticker']}: MOS de {row['MOS']*100:.1f}% - ¡Oportunidad excepcional!",
                    'data': row.to_dict()
                })
        
        # Alert 2: Perfect Quality (Piotroski = 9 o ROIC > 30%)
        perfect_quality = self.df[(self.df['Piotroski'] >= 8) | (self.df['ROIC'] > 0.30)]
        if len(perfect_quality) > 0:
            for _, row in perfect_quality.head(5).iterrows():
                alerts.append({
                    'type': 'QUALITY_EXCELLENCE',
                    'severity': 'MEDIUM',
                    'ticker': row['Ticker'],
                    'message': f"{row['Ticker']}: Calidad excepcional - Piotroski {row['Piotroski']}, ROIC {row['ROIC']*100:.1f}%",
                    'data': row.to_dict()
                })
        
        # Alert 3: High Growth Potential (Growth_Est > 12%)
        high_growth = self.df[self.df['Growth_Est'] > 0.12]
        if len(high_growth) > 0:
            for _, row in high_growth.head(3).iterrows():
                alerts.append({
                    'type': 'HIGH_GROWTH',
                    'severity': 'MEDIUM',
                    'ticker': row['Ticker'],
                    'message': f"{row['Ticker']}: Alto potencial de crecimiento {row['Growth_Est']*100:.1f}%",
                    'data': row.to_dict()
                })
        
        self.processed_data['alerts'] = alerts
        print(f"✅ {len(alerts)} alertas generadas")
        return alerts
    
    def create_watchlist(self, criteria='balanced'):
        """
        Crea una watchlist basada en diferentes criterios
        
        Args:
            criteria: 'aggressive', 'balanced', 'conservative'
        """
        if self.df is None or self.df.empty:
            return []
        
        if criteria == 'aggressive':
            # Mayor MOS, menos conservador con calidad
            watchlist = self.df[
                (self.df['MOS'] > 0.20) & 
                (self.df['Piotroski'] >= 5)
            ].nlargest(15, 'MOS')
            
        elif criteria == 'conservative':
            # Alta calidad, MOS moderado
            watchlist = self.df[
                (self.df['Piotroski'] >= 7) & 
                (self.df['ROIC'] > 0.15) &
                (self.df['MOS'] > 0.05)
            ].nlargest(15, 'ROIC')
            
        else:  # balanced
            # Balance entre MOS, ROIC y Piotroski
            self.df['score'] = (
                self.df['MOS'] * 0.4 + 
                (self.df['ROIC'] / self.df['ROIC'].max()) * 0.3 +
                (self.df['Piotroski'] / 9) * 0.3
            )
            watchlist = self.df.nlargest(15, 'score')
        
        watchlist_data = watchlist[['Ticker', 'Price', 'Intrinsic', 'MOS', 'ROIC', 'Piotroski', 'Sector']].to_dict('records')
        
        self.processed_data[f'watchlist_{criteria}'] = watchlist_data
        print(f"✅ Watchlist '{criteria}' creada con {len(watchlist_data)} acciones")
        return watchlist_data
    
    def export_to_json(self, filename=None):
        """Exporta los datos procesados a JSON"""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'processed_results_{timestamp}.json'
        
        output = {
            'metadata': {
                'processed_at': datetime.now().isoformat(),
                'original_analysis_date': self.raw_results.get('generated_at'),
                'total_analyzed': self.raw_results.get('total_analyzed'),
                'candidates_found': self.raw_results.get('candidates_count')
            },
            'processed_data': self.processed_data
        }
        
        with open(filename, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        
        print(f"✅ Datos exportados a: {filename}")
        return filename
    
    def process_all(self):
        """Ejecuta todo el pipeline de procesamiento"""
        print("="*60)
        print("🔄 Iniciando Post-Procesamiento")
        print("="*60)
        
        if not self.load_data():
            return None
        
        # Ejecutar todos los análisis
        self.categorize_by_sector()
        self.identify_top_opportunities(10)
        self.calculate_portfolio_metrics()
        self.generate_alerts()
        self.create_watchlist('aggressive')
        self.create_watchlist('balanced')
        self.create_watchlist('conservative')
        
        print("="*60)
        print("✅ Post-Procesamiento Completado")
        print("="*60)
        
        return self.processed_data


# Función helper para uso directo
def process_results(results_data):
    """
    Función de conveniencia para procesar resultados
    
    Args:
        results_data: Dict con los resultados del análisis
        
    Returns:
        Dict con datos procesados
    """
    processor = ResultsPostProcessor(results_data)
    return processor.process_all()


# Para uso standalone
if __name__ == "__main__":
    # Ejemplo de uso
    print("Post-Processor listo para recibir datos")
    print("Uso:")
    print("  from post_processor import process_results")
    print("  processed = process_results(results_data)")
