"""
portfolio_analyzer.py - Warren Screener Core Analysis
Toda la lógica de análisis DCF 2-Stage + ROIC + Piotroski
"""

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm.auto import tqdm
from io import StringIO


class WarrenScreener:
    """
    Warren Screener v8.0 - DCF 2-Stage + Quality Focus
    Análisis basado en ROIC, Piotroski y DCF avanzado
    """
    
    def __init__(self, config=None):
        """
        Args:
            config: Dict con configuración del screener
        """
        self.config = config or {
            'MAX_WORKERS': 12,
            'MIN_ROIC': 0.08,
            'MIN_PIOTROSKI': 5,
            'DISCOUNT_RATE': 0.09,
            'MARGIN_OF_SAFETY_VIEW': -0.20
        }
        
        self.universe = []
        self.results = []
        
    def log(self, msg):
        """Helper para logging"""
        print(msg)
        sys.stdout.flush()
    
    # ==========================================
    # 1. UNIVERSO INDESTRUCTIBLE (CSV + HARDCODE)
    # ==========================================
    def get_bulletproof_universe(self):
        """Genera universo robusto de tickers desde múltiples fuentes"""
        tickers = set()
        self.log("🌍 Generando Universo...")

        # Intento 1: GitHub API (más confiable que raw)
        try:
            url_sp500 = "https://api.github.com/repos/datasets/s-and-p-500-companies/contents/data/constituents.csv"
            headers = {'Accept': 'application/vnd.github.v3.raw'}
            r = requests.get(url_sp500, headers=headers, timeout=30)
            r.raise_for_status()
            df = pd.read_csv(StringIO(r.text))
            tickers.update(df['Symbol'].tolist())
            self.log(f"   -> S&P 500 cargado desde GitHub API ({len(tickers)})")
        except Exception as e:
            self.log(f"   ⚠️ Fallo GitHub S&P 500: {str(e)}")
            
            # Fallback: Intentar con raw.githubusercontent.com
            try:
                url_sp500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
                df = pd.read_csv(url_sp500, timeout=30)
                tickers.update(df['Symbol'].tolist())
                self.log(f"   -> S&P 500 cargado desde GitHub raw ({len(tickers)})")
            except Exception as e2:
                self.log(f"   ⚠️ Fallo GitHub raw: {str(e2)}")

        # Intento 2: Nasdaq 100
        try:
            url_ndx = "https://api.github.com/repos/nasdaq-100/nasdaq-100-symbols/contents/nasdaq-100-symbols.csv"
            headers = {'Accept': 'application/vnd.github.v3.raw'}
            r = requests.get(url_ndx, headers=headers, timeout=30)
            if r.status_code == 200:
                text = r.text
                lines = text.split('\n')
                nasdaq_ticks = [x.split(',')[0].strip() for x in lines if x and 'Symbol' not in x]
                tickers.update(nasdaq_ticks)
                self.log(f"   -> Nasdaq cargado ({len(nasdaq_ticks)})")
        except Exception as e:
            self.log(f"   ⚠️ Fallo GitHub Nasdaq: {str(e)}")

        # Intento 3: Lista de Respaldo MANUAL COMPLETA
        BACKUP_LIST = [
            # Originales (90 tickers)
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B', 'LLY', 'V',
            'TSM', 'UNH', 'AVGO', 'JPM', 'NVO', 'WMT', 'XOM', 'MA', 'JNJ', 'PG',
            'HD', 'MRK', 'COST', 'ABBV', 'ORCL', 'ASML', 'CVX', 'ADBE', 'AMD', 'KO',
            'PEP', 'NFLX', 'TMO', 'CRM', 'ACN', 'CSCO', 'MCD', 'ABT', 'LIN', 'NKE',
            'TXN', 'DHR', 'INTC', 'WFC', 'QCOM', 'PM', 'INTU', 'VZ', 'CMCSA', 'UNP',
            'RTX', 'IBM', 'AMGN', 'CAT', 'HON', 'T', 'GE', 'BA', 'GS', 'LOW',
            'NEE', 'SPGI', 'BLK', 'AXP', 'NOW', 'ISRG', 'SBUX', 'SYK', 'ELV', 'MS',
            'BKNG', 'PLD', 'GILD', 'TJX', 'MDT', 'MMC', 'ADP', 'C', 'VRTX', 'CVS',
            'REGN', 'BMY', 'ZTS', 'SCHW', 'ADI', 'PGR', 'MO', 'ETN', 'CB', 'SO',
            # 410 tickers adicionales del universo completo
            'DUK', 'LRCX', 'AMT', 'BDX', 'CI', 'TMUS', 'FI', 'DE', 'SLB', 'PYPL',
            'AMAT', 'MDLZ', 'USB', 'TGT', 'BSX', 'PNC', 'EQIX', 'CME', 'ITW', 'AON',
            'APD', 'CL', 'WELL', 'MMM', 'EOG', 'SHW', 'CSX', 'WM', 'NSC', 'GD',
            'ICE', 'MCO', 'FCX', 'APH', 'MAR', 'COF', 'MU', 'HCA', 'NOC', 'EMR',
            'PSA', 'SNPS', 'CCI', 'OXY', 'ECL', 'TFC', 'MCK', 'FDX', 'ROP', 'AJG',
            'NXPI', 'AFL', 'GM', 'ADM', 'F', 'AIG', 'AEP', 'TRV', 'SRE', 'MPC',
            'TEL', 'ADSK', 'CDNS', 'PSX', 'MNST', 'AZO', 'KMB', 'JCI', 'HUM', 'RSG',
            'PAYX', 'VLO', 'COR', 'ALL', 'LHX', 'DHI', 'O', 'SPG', 'D', 'KLAC',
            'NEM', 'EW', 'PRU', 'HSY', 'CMG', 'MSCI', 'YUM', 'KHC', 'KMI', 'MSI',
            'EXC', 'ORLY', 'MCHP', 'GIS', 'SYY', 'CTVA', 'BK', 'LEN', 'A', 'OKE',
            'EXR', 'ODFL', 'CEG', 'IQV', 'CNC', 'TROW', 'FAST', 'IDXX', 'HES', 'DD',
            'VST', 'CTAS', 'XEL', 'IT', 'ROK', 'ED', 'DOW', 'KR', 'EA', 'CPRT',
            'GEHC', 'ROST', 'VICI', 'KVUE', 'ON', 'VRSK', 'GLW', 'STZ', 'VMC', 'PPG',
            'AME', 'BKR', 'CMI', 'ANSS', 'HAL', 'DXCM', 'AWK', 'ACGL', 'URI', 'CHTR',
            'HPQ', 'PCAR', 'MTD', 'DVN', 'IR', 'CSGP', 'PCG', 'MLM', 'IFF', 'FANG',
            'WMB', 'EBAY', 'FITB', 'GPN', 'DAL', 'WEC', 'HWM', 'RMD', 'TTWO', 'ETR',
            'WAB', 'HIG', 'AMP', 'PPL', 'BRO', 'SBAC', 'GRMN', 'CARR', 'NDAQ', 'WTW',
            'KEYS', 'FTV', 'HPE', 'WBD', 'DLR', 'LYB', 'STE', 'DLTR', 'FE', 'EXPE',
            'GWW', 'APTV', 'STT', 'HBAN', 'PEG', 'NTRS', 'MTB', 'EQR', 'AVB', 'HUBB',
            'ZBH', 'AEE', 'WAT', 'RF', 'WY', 'LH', 'VTR', 'BLDR', 'EFX', 'ARE',
            'EIX', 'PFG', 'DFS', 'INVH', 'ULTA', 'ESS', 'DTE', 'SYF', 'IRM', 'DG',
            'TSCO', 'TDY', 'BBY', 'CBOE', 'MAA', 'DRI', 'K', 'CAH', 'TRGP', 'EQT',
            'BALL', 'ATO', 'FDS', 'OMC', 'MKC', 'VLTO', 'TYL', 'LDOS', 'CBRE', 'BAX',
            'HOLX', 'EXPD', 'DGX', 'STLD', 'TXT', 'CLX', 'LUV', 'CFG', 'RJF', 'MPWR',
            'TSN', 'SWK', 'CNP', 'CMS', 'MOH', 'WST', 'DOV', 'NI', 'PTC', 'MRO',
            'TER', 'PODD', 'FLT', 'NRG', 'L', 'WDC', 'ZBRA', 'PKG', 'NVR', 'IP',
            'AES', 'SWKS', 'J', 'COO', 'VRSN', 'AMCR', 'LVS', 'UAL', 'JBHT', 'CINF',
            'TPR', 'LNT', 'EVRG', 'SJM', 'FICO', 'AVY', 'NUE', 'AKAM', 'NTAP', 'CHRW',
            'KIM', 'ALGN', 'HST', 'BXP', 'POOL', 'CZR', 'ALB', 'GNRC', 'MAS', 'JKHY',
            'BEN', 'TECH', 'IPG', 'UDR', 'AIZ', 'CTLT', 'ENPH', 'CPT', 'TFX', 'REG',
            'PKI', 'NDSN', 'GL', 'IEX', 'EMN', 'LKQ', 'CE', 'BBWI', 'PAYC', 'TAP',
            'JNPR', 'AOS', 'DAY', 'HII', 'AAL', 'HRL', 'HSIC', 'AAP', 'UHS', 'INCY',
            'MKTX', 'CPB', 'BF-B', 'BWA', 'BIO', 'WBA', 'NWSA', 'EPAM', 'FFIV', 'CRL',
            'VTRS', 'DXC', 'QRVO', 'SEE', 'PNR', 'WYNN', 'RL', 'RHI', 'AIV', 'FOXA',
            'NWS', 'HAS', 'IVZ', 'ETSY', 'MTCH', 'DISH', 'FOX', 'PARA', 'NCLH', 'CCL',
            'DINO', 'SEDG', 'WHR', 'PNW', 'CMA', 'MGM', 'DVA', 'GPC', 'FRT', 'APA',
            'KMX', 'ZION', 'LW', 'ALLE', 'MHK', 'NWL', 'TAP', 'BG', 'VFC', 'FMC',
            # Añadir más tickers si hace falta
            'ABNB', 'RIVN', 'LCID', 'PLTR', 'SNOW', 'RBLX', 'U', 'DASH', 'COIN',
            'SHOP', 'SQ', 'ZM', 'ROKU', 'PINS', 'DOCU', 'CRWD', 'NET', 'DDOG', 'OKTA'
        ]
        
        tickers.update(BACKUP_LIST)
        self.log(f"   -> Backup manual agregado ({len(BACKUP_LIST)} tickers)")

        # Limpieza
        cleaned = sorted([t.upper().strip() for t in tickers if t and t.strip()])
        self.log(f"✅ Universo final: {len(cleaned)} tickers")
        
        self.universe = cleaned
        return cleaned

    # ==========================================
    # 2. LÓGICA DE ANÁLISIS (DCF 2-STAGE)
    # ==========================================
    
    def _safe_get(self, data, keys, default=None):
        """Navegación segura por diccionarios anidados"""
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
                if current is None:
                    return default
            else:
                return default
        return current if current is not None else default

    def _fuzzy_find(self, info, possible_keys, default=None):
        """Busca fuzzy entre múltiples claves posibles"""
        for key in possible_keys:
            val = info.get(key)
            if val is not None and val not in [np.nan, float('inf'), float('-inf')]:
                return val
        return default

    def calculate_roic(self, ticker_obj):
        """Calcula ROIC = EBIT * (1 - Tax) / (Equity + Debt - Cash)"""
        try:
            info = ticker_obj.info
            bs = ticker_obj.balance_sheet
            inc = ticker_obj.income_stmt
            
            if bs.empty or inc.empty:
                return None
            
            # EBIT
            ebit = self._fuzzy_find(inc.iloc[:, 0].to_dict(), 
                                    ['EBIT', 'Operating Income', 'operatingIncome'])
            if ebit is None:
                return None
            
            # Tax Rate
            tax_rate = self._fuzzy_find(info, ['effectiveTaxRate', 'taxRate'], 0.21)
            
            # Balance
            equity = self._fuzzy_find(bs.iloc[:, 0].to_dict(), 
                                     ['Total Equity', 'Stockholders Equity', 
                                      'Total Stockholder Equity', 'totalStockholderEquity'])
            total_debt = self._fuzzy_find(bs.iloc[:, 0].to_dict(),
                                         ['Total Debt', 'totalDebt', 'Long Term Debt'])
            cash = self._fuzzy_find(bs.iloc[:, 0].to_dict(),
                                   ['Cash And Cash Equivalents', 'Cash', 'cashAndCashEquivalents'])
            
            if None in [equity, total_debt, cash]:
                return None
            
            invested_capital = equity + total_debt - cash
            
            if invested_capital <= 0:
                return None
            
            nopat = ebit * (1 - tax_rate)
            roic = nopat / invested_capital
            
            return roic if -1 <= roic <= 3 else None
            
        except Exception:
            return None

    def calculate_piotroski(self, ticker_obj):
        """Calcula Piotroski Score (0-9)"""
        try:
            inc = ticker_obj.income_stmt
            bs = ticker_obj.balance_sheet
            cf = ticker_obj.cashflow
            
            if inc.empty or bs.empty or cf.empty:
                return None
            
            score = 0
            
            # 1. ROA positivo
            net_income = self._safe_get(inc.iloc[:, 0].to_dict(), ['Net Income'])
            total_assets = self._safe_get(bs.iloc[:, 0].to_dict(), ['Total Assets'])
            if net_income and total_assets and net_income > 0:
                score += 1
            
            # 2. Operating Cash Flow positivo
            ocf = self._safe_get(cf.iloc[:, 0].to_dict(), ['Operating Cash Flow'])
            if ocf and ocf > 0:
                score += 1
            
            # 3. ROA creciente (comparar 2 años)
            if len(bs.columns) >= 2 and len(inc.columns) >= 2:
                net_income_prev = self._safe_get(inc.iloc[:, 1].to_dict(), ['Net Income'])
                total_assets_prev = self._safe_get(bs.iloc[:, 1].to_dict(), ['Total Assets'])
                
                if all([net_income, total_assets, net_income_prev, total_assets_prev]):
                    roa_current = net_income / total_assets
                    roa_prev = net_income_prev / total_assets_prev
                    if roa_current > roa_prev:
                        score += 1
            
            # 4. OCF > Net Income (calidad de ganancias)
            if ocf and net_income and ocf > net_income:
                score += 1
            
            # 5. Deuda decreciente
            if len(bs.columns) >= 2:
                debt_current = self._safe_get(bs.iloc[:, 0].to_dict(), ['Total Debt'])
                debt_prev = self._safe_get(bs.iloc[:, 1].to_dict(), ['Total Debt'])
                if debt_current and debt_prev and debt_current < debt_prev:
                    score += 1
            
            # 6. Current Ratio creciente
            if len(bs.columns) >= 2:
                current_assets = self._safe_get(bs.iloc[:, 0].to_dict(), ['Current Assets'])
                current_liab = self._safe_get(bs.iloc[:, 0].to_dict(), ['Current Liabilities'])
                current_assets_prev = self._safe_get(bs.iloc[:, 1].to_dict(), ['Current Assets'])
                current_liab_prev = self._safe_get(bs.iloc[:, 1].to_dict(), ['Current Liabilities'])
                
                if all([current_assets, current_liab, current_assets_prev, current_liab_prev]):
                    if current_liab > 0 and current_liab_prev > 0:
                        ratio_current = current_assets / current_liab
                        ratio_prev = current_assets_prev / current_liab_prev
                        if ratio_current > ratio_prev:
                            score += 1
            
            # 7. Sin nuevas acciones emitidas
            if len(bs.columns) >= 2:
                shares = self._safe_get(bs.iloc[:, 0].to_dict(), ['Share Issued'])
                shares_prev = self._safe_get(bs.iloc[:, 1].to_dict(), ['Share Issued'])
                if shares and shares_prev and shares <= shares_prev:
                    score += 1
            
            # 8. Gross Margin creciente
            if len(inc.columns) >= 2:
                revenue = self._safe_get(inc.iloc[:, 0].to_dict(), ['Total Revenue'])
                cogs = self._safe_get(inc.iloc[:, 0].to_dict(), ['Cost Of Revenue'])
                revenue_prev = self._safe_get(inc.iloc[:, 1].to_dict(), ['Total Revenue'])
                cogs_prev = self._safe_get(inc.iloc[:, 1].to_dict(), ['Cost Of Revenue'])
                
                if all([revenue, cogs, revenue_prev, cogs_prev]):
                    if revenue > 0 and revenue_prev > 0:
                        margin = (revenue - cogs) / revenue
                        margin_prev = (revenue_prev - cogs_prev) / revenue_prev
                        if margin > margin_prev:
                            score += 1
            
            # 9. Asset Turnover creciente
            if len(inc.columns) >= 2 and len(bs.columns) >= 2:
                revenue = self._safe_get(inc.iloc[:, 0].to_dict(), ['Total Revenue'])
                assets = self._safe_get(bs.iloc[:, 0].to_dict(), ['Total Assets'])
                revenue_prev = self._safe_get(inc.iloc[:, 1].to_dict(), ['Total Revenue'])
                assets_prev = self._safe_get(bs.iloc[:, 1].to_dict(), ['Total Assets'])
                
                if all([revenue, assets, revenue_prev, assets_prev]):
                    if assets > 0 and assets_prev > 0:
                        turnover = revenue / assets
                        turnover_prev = revenue_prev / assets_prev
                        if turnover > turnover_prev:
                            score += 1
            
            return score
            
        except Exception:
            return None

    def dcf_2stage(self, ticker_obj, roic):
        """
        DCF 2-Stage Avanzado
        Stage 1: Crecimiento basado en ROIC (5 años)
        Stage 2: Valor terminal con crecimiento perpetuo del 3%
        """
        try:
            info = ticker_obj.info
            cf = ticker_obj.cashflow
            bs = ticker_obj.balance_sheet
            
            if cf.empty or bs.empty:
                return None, None
            
            # Free Cash Flow actual
            ocf = self._safe_get(cf.iloc[:, 0].to_dict(), ['Operating Cash Flow'])
            capex = self._safe_get(cf.iloc[:, 0].to_dict(), ['Capital Expenditure'])
            
            if not ocf or not capex:
                return None, None
            
            fcf = ocf + capex  # capex es negativo
            
            if fcf <= 0:
                return None, None
            
            # Estimación de crecimiento basada en ROIC
            # Crecimiento = ROIC * Tasa de Reinversión (asumimos 50%)
            growth_rate = min(roic * 0.5, 0.14)  # Cap al 14%
            
            # Stage 1: Valor presente de FCF (5 años)
            discount_rate = self.config['DISCOUNT_RATE']
            stage1_pv = 0
            
            for year in range(1, 6):
                future_fcf = fcf * ((1 + growth_rate) ** year)
                pv = future_fcf / ((1 + discount_rate) ** year)
                stage1_pv += pv
            
            # Stage 2: Valor terminal
            terminal_growth = 0.03
            fcf_year5 = fcf * ((1 + growth_rate) ** 5)
            terminal_value = (fcf_year5 * (1 + terminal_growth)) / (discount_rate - terminal_growth)
            terminal_pv = terminal_value / ((1 + discount_rate) ** 5)
            
            # Valor total de la empresa
            enterprise_value = stage1_pv + terminal_pv
            
            # Ajustar por deuda y cash
            total_debt = self._safe_get(bs.iloc[:, 0].to_dict(), ['Total Debt'])
            cash = self._safe_get(bs.iloc[:, 0].to_dict(), ['Cash And Cash Equivalents'])
            shares = self._fuzzy_find(info, ['sharesOutstanding'], 1)
            
            if not total_debt:
                total_debt = 0
            if not cash:
                cash = 0
            
            equity_value = enterprise_value + cash - total_debt
            
            if shares <= 0 or equity_value <= 0:
                return None, None
            
            intrinsic_value = equity_value / shares
            
            return intrinsic_value, growth_rate
            
        except Exception:
            return None, None

    def analyze_ticker(self, ticker):
        """Análisis completo de un ticker"""
        try:
            t = yf.Ticker(ticker)
            info = t.info
            
            # Precio actual
            price = info.get('currentPrice') or info.get('regularMarketPrice')
            if not price or price <= 0:
                return None
            
            # Sector
            sector = info.get('sector', 'Unknown')
            
            # ROIC
            roic = self.calculate_roic(t)
            if roic is None or roic < self.config['MIN_ROIC']:
                return None
            
            # Piotroski
            piotroski = self.calculate_piotroski(t)
            if piotroski is None or piotroski < self.config['MIN_PIOTROSKI']:
                return None
            
            # DCF
            intrinsic_value, growth_est = self.dcf_2stage(t, roic)
            if intrinsic_value is None or intrinsic_value <= 0:
                return None
            
            # Margen de Seguridad
            mos = (intrinsic_value - price) / intrinsic_value
            
            # Filtrar por MOS mínimo para watchlist
            if mos < self.config['MARGIN_OF_SAFETY_VIEW']:
                return None
            
            return {
                'Ticker': ticker,
                'Price': round(price, 2),
                'Intrinsic': round(intrinsic_value, 2),
                'MOS': round(mos, 4),
                'ROIC': round(roic, 4),
                'Piotroski': int(piotroski),
                'Growth_Est': round(growth_est, 4) if growth_est else None,
                'Sector': sector
            }
            
        except Exception as e:
            return None

    def run_parallel_analysis(self):
        """Ejecuta análisis paralelo sobre todo el universo"""
        self.log("\n" + "="*60)
        self.log("🔍 Iniciando Análisis Paralelo")
        self.log("="*60)
        self.log(f"Universo: {len(self.universe)} tickers")
        self.log(f"Workers: {self.config['MAX_WORKERS']}")
        self.log(f"Filtros: ROIC>={self.config['MIN_ROIC']:.0%}, Piotroski>={self.config['MIN_PIOTROSKI']}")
        self.log("="*60 + "\n")
        
        results = []
        
        with ThreadPoolExecutor(max_workers=self.config['MAX_WORKERS']) as executor:
            futures = {executor.submit(self.analyze_ticker, ticker): ticker 
                      for ticker in self.universe}
            
            with tqdm(total=len(futures), desc="Analizando", unit="ticker") as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        results.append(result)
                    pbar.update(1)
        
        self.results = results
        self.log(f"\n✅ Análisis completado: {len(results)} candidatos encontrados")
        return results

    def categorize_results(self):
        """Categoriza resultados en 3 zonas"""
        if not self.results:
            return {
                'buy_zone': [],
                'fair_zone': [],
                'watch_zone': []
            }
        
        df = pd.DataFrame(self.results)
        
        buy_zone = df[df['MOS'] > 0.10].sort_values('MOS', ascending=False)
        fair_zone = df[(df['MOS'] > 0) & (df['MOS'] <= 0.10)].sort_values('MOS', ascending=False)
        watch_zone = df[df['MOS'] <= 0].sort_values('MOS', ascending=False)
        
        self.log("\n" + "="*60)
        self.log("📊 CLASIFICACIÓN DE RESULTADOS")
        self.log("="*60)
        self.log(f"🟢 Zona de Compra (MOS > 10%): {len(buy_zone)}")
        self.log(f"🟡 Valor Justo (MOS 0-10%): {len(fair_zone)}")
        self.log(f"🔴 Watchlist (MOS < 0%): {len(watch_zone)}")
        self.log("="*60)
        
        return {
            'buy_zone': buy_zone.to_dict('records'),
            'fair_zone': fair_zone.to_dict('records'),
            'watch_zone': watch_zone.to_dict('records')
        }

    def analyze(self):
        """Pipeline completo de análisis"""
        start_time = datetime.now()
        
        # 1. Generar universo
        self.get_bulletproof_universe()
        
        # 2. Análisis paralelo
        self.run_parallel_analysis()
        
        # 3. Categorizar
        categorized = self.categorize_results()
        
        # 4. Estadísticas
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Top 30 por MOS
        df_all = pd.DataFrame(self.results) if self.results else pd.DataFrame()
        top_30 = df_all.nlargest(30, 'MOS').to_dict('records') if not df_all.empty else []
        
        result = {
            'total_analyzed': len(self.universe),
            'candidates_count': len(self.results),
            'buy_candidates': len(categorized['buy_zone']),
            'fair_value': len(categorized['fair_zone']),
            'watchlist': len(categorized['watch_zone']),
            'execution_time_seconds': round(execution_time, 2),
            'generated_at': datetime.now().isoformat(),
            'config': self.config,
            'results': self.results,
            'top_30': top_30,
            'buy_zone': categorized['buy_zone'],
            'fair_zone': categorized['fair_zone'],
            'watch_zone': categorized['watch_zone']
        }
        
        return result


# Función helper para uso directo
def analyze_portfolio(config=None):
    """
    Función de conveniencia para análisis completo
    
    Args:
        config: Dict opcional con configuración personalizada
        
    Returns:
        Dict con resultados completos del análisis
    """
    screener = WarrenScreener(config)
    return screener.analyze()


# Para uso standalone
if __name__ == "__main__":
    print("Warren Screener v8.0 - Portfolio Analyzer")
    print("Uso:")
    print("  from portfolio_analyzer import analyze_portfolio")
    print("  results = analyze_portfolio()")
    print("\nEjecutando análisis de ejemplo...")
    
    results = analyze_portfolio()
    
    print(f"\n{'='*60}")
    print("RESUMEN DE RESULTADOS")
    print(f"{'='*60}")
    print(f"Total analizado: {results['total_analyzed']}")
    print(f"Candidatos encontrados: {results['candidates_count']}")
    print(f"🟢 Zona de compra: {results['buy_candidates']}")
    print(f"🟡 Valor justo: {results['fair_value']}")
    print(f"🔴 Watchlist: {results['watchlist']}")
    print(f"⏱️  Tiempo: {results['execution_time_seconds']}s")
    print(f"{'='*60}")
