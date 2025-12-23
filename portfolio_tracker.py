"""
portfolio_tracker.py - Portfolio Performance Tracker
Análisis de rendimiento de portfolio basado en el notebook original
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

class PortfolioTracker:
    """
    Rastrea el rendimiento de un portfolio de acciones
    """
    
    def __init__(self, tickers, start_date, initial_capital):
        """
        Args:
            tickers: List de símbolos (ej: ["AAPL", "MSFT"])
            start_date: Fecha inicial (str formato YYYY-MM-DD)
            initial_capital: Capital inicial (float)
        """
        self.tickers = tickers
        self.start_date = start_date
        self.initial_capital = initial_capital
        self.weights = np.array([1/len(tickers)] * len(tickers))
        
        self.data = None
        self.portfolio_value = None
        self.daily_returns = None
        self.metrics = {}
        
    def download_data(self):
        """Descarga datos históricos de Yahoo Finance"""
        print(f"📊 Descargando datos para {len(self.tickers)} acciones...")
        
        # Buffer de 7 días antes para asegurar datos
        start_buffer = (pd.to_datetime(self.start_date) - timedelta(days=7)).strftime("%Y-%m-%d")
        today = datetime.today().strftime("%Y-%m-%d")
        
        try:
            raw = yf.download(
                self.tickers,
                start=start_buffer,
                end=today,
                auto_adjust=True,
                progress=False
            )
            
            # Si viene multiíndice (OHLCV), usamos "Close"
            if isinstance(raw.columns, pd.MultiIndex):
                data = raw["Close"].copy()
            else:
                data = raw.copy()
            
            # Filtrar desde fecha de inicio
            data = data[data.index >= self.start_date]
            
            if data.empty:
                print("❌ No se encontraron datos para las fechas especificadas")
                return False
            
            if isinstance(data, pd.Series):
                data = data.to_frame()
            
            # Reordenar columnas según TICKERS
            self.data = data[self.tickers]
            
            print(f"✅ Datos descargados: {len(self.data)} días")
            return True
            
        except Exception as e:
            print(f"❌ Error descargando datos: {e}")
            return False
    
    def calculate_portfolio_value(self):
        """Calcula el valor del portfolio a lo largo del tiempo"""
        # Normalizamos precios en 1 el día inicial
        normalized_prices = self.data / self.data.iloc[0]
        
        # Índice del portafolio (valor relativo)
        portfolio_index = (normalized_prices * self.weights).sum(axis=1)
        
        # Valor nominal
        self.portfolio_value = portfolio_index * self.initial_capital
        
        # Rendimientos diarios
        self.daily_returns = self.data.pct_change().dropna()
        
    def calculate_metrics(self):
        """Calcula todas las métricas del portfolio"""
        port_daily_ret = (self.daily_returns * self.weights).sum(axis=1)
        
        # Retorno total
        total_return = self.portfolio_value.iloc[-1] / self.portfolio_value.iloc[0] - 1
        
        # Días y años invertidos
        days_invested = (self.portfolio_value.index[-1] - self.portfolio_value.index[0]).days
        years_invested = days_invested / 365.25 if days_invested > 0 else np.nan
        
        # CAGR (rentabilidad anualizada)
        if years_invested > 0:
            cagr = (self.portfolio_value.iloc[-1] / self.portfolio_value.iloc[0]) ** (1 / years_invested) - 1
        else:
            cagr = np.nan
        
        # Drawdown
        rolling_max = self.portfolio_value.cummax()
        drawdown = self.portfolio_value / rolling_max - 1
        max_drawdown = drawdown.min()
        
        # Volatilidad anualizada
        port_vol_annual = port_daily_ret.std() * np.sqrt(252)
        
        # Sharpe ratio (rf ≈ 0)
        if not np.isnan(port_vol_annual) and port_vol_annual != 0 and years_invested > 0:
            sharpe = ((1 + total_return) ** (1/years_invested) - 1) / port_vol_annual
        else:
            sharpe = np.nan
        
        self.metrics = {
            'fecha_inicio': self.portfolio_value.index[0].strftime('%Y-%m-%d'),
            'fecha_actual': self.portfolio_value.index[-1].strftime('%Y-%m-%d'),
            'dias_invertidos': int(days_invested),
            'valor_inicial': float(self.initial_capital),
            'valor_actual': float(self.portfolio_value.iloc[-1]),
            'ganancia_perdida': float(self.portfolio_value.iloc[-1] - self.initial_capital),
            'retorno_total_pct': float(total_return * 100),
            'cagr_pct': float(cagr * 100) if not np.isnan(cagr) else None,
            'volatilidad_anual_pct': float(port_vol_annual * 100),
            'sharpe_ratio': float(sharpe) if not np.isnan(sharpe) else None,
            'max_drawdown_pct': float(max_drawdown * 100)
        }
        
    def calculate_per_ticker_metrics(self):
        """Calcula métricas por cada acción"""
        # Retorno total de cada activo
        returns_by_ticker = self.data.iloc[-1] / self.data.iloc[0] - 1
        
        # Capital invertido y valor actual por activo
        capital_by_ticker = self.initial_capital * self.weights
        current_value_by_ticker = capital_by_ticker * (1 + returns_by_ticker)
        pnl_by_ticker = current_value_by_ticker - capital_by_ticker
        
        # Volatilidad anual por ticker
        vol_by_ticker = self.daily_returns.std() * np.sqrt(252)
        
        # Contribución al retorno del portafolio
        contrib_return = self.weights * returns_by_ticker
        contrib_return_pct = contrib_return / contrib_return.sum() if contrib_return.sum() != 0 else contrib_return
        
        per_ticker = []
        for i, ticker in enumerate(self.tickers):
            per_ticker.append({
                'ticker': ticker,
                'peso_portfolio': float(self.weights[i]),
                'capital_inicial': float(capital_by_ticker.iloc[i]),
                'valor_actual': float(current_value_by_ticker.iloc[i]),
                'ganancia_perdida': float(pnl_by_ticker.iloc[i]),
                'retorno_pct': float(returns_by_ticker.iloc[i] * 100),
                'volatilidad_anual_pct': float(vol_by_ticker.iloc[i] * 100),
                'contribucion_retorno_pct': float(contrib_return_pct.iloc[i] * 100)
            })
        
        # Identificar mejor y peor
        best_idx = returns_by_ticker.idxmax()
        worst_idx = returns_by_ticker.idxmin()
        top_contrib_idx = contrib_return_pct.sort_values(ascending=False).index[0]
        
        return {
            'detalle_por_accion': per_ticker,
            'mejor_accion': {
                'ticker': best_idx,
                'retorno_pct': float(returns_by_ticker[best_idx] * 100)
            },
            'peor_accion': {
                'ticker': worst_idx,
                'retorno_pct': float(returns_by_ticker[worst_idx] * 100)
            },
            'mayor_contribucion': {
                'ticker': top_contrib_idx,
                'contribucion_pct': float(contrib_return_pct[top_contrib_idx] * 100)
            }
        }
    
    def analyze(self):
        """Ejecuta el análisis completo"""
        print("="*60)
        print("📊 Portfolio Performance Tracker")
        print("="*60)
        
        # 1. Descargar datos
        if not self.download_data():
            return None
        
        # 2. Calcular valor del portfolio
        print("💰 Calculando valor del portfolio...")
        self.calculate_portfolio_value()
        
        # 3. Calcular métricas
        print("📈 Calculando métricas...")
        self.calculate_metrics()
        
        # 4. Métricas por ticker
        print("🎯 Analizando rendimiento por acción...")
        ticker_metrics = self.calculate_per_ticker_metrics()
        
        print("="*60)
        print("✅ Análisis Completado")
        print("="*60)
        print(f"Valor inicial: ${self.metrics['valor_inicial']:,.2f}")
        print(f"Valor actual:  ${self.metrics['valor_actual']:,.2f}")
        print(f"Ganancia:      ${self.metrics['ganancia_perdida']:,.2f} ({self.metrics['retorno_total_pct']:.2f}%)")
        print(f"Mejor acción:  {ticker_metrics['mejor_accion']['ticker']} (+{ticker_metrics['mejor_accion']['retorno_pct']:.2f}%)")
        print(f"Peor acción:   {ticker_metrics['peor_accion']['ticker']} ({ticker_metrics['peor_accion']['retorno_pct']:.2f}%)")
        print("="*60)
        
        # Retornar todo
        return {
            'portfolio_metrics': self.metrics,
            'ticker_analysis': ticker_metrics,
            'tickers': self.tickers,
            'start_date': self.start_date,
            'initial_capital': self.initial_capital
        }


def track_portfolio(tickers, start_date, initial_capital):
    """
    Función de conveniencia para tracking de portfolio
    
    Args:
        tickers: Lista de símbolos
        start_date: Fecha inicial (YYYY-MM-DD)
        initial_capital: Capital inicial
        
    Returns:
        Dict con análisis completo
    """
    tracker = PortfolioTracker(tickers, start_date, initial_capital)
    return tracker.analyze()


# Para uso standalone
if __name__ == "__main__":
    # Ejemplo
    result = track_portfolio(
        tickers=["AAPL", "MSFT", "GOOGL"],
        start_date="2024-01-01",
        initial_capital=10000
    )
    
    if result:
        print("\n📊 Resultados:")
        print(json.dumps(result, indent=2))
