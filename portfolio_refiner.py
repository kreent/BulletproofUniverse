"""
portfolio_refiner.py - The Analyst AI V7 (FULL)
Target 6M/12M + Trim/Stop + Filtro de Oportunidad
Selección institucional de JOYAS con gates estrictos
"""

import pandas as pd
import numpy as np
import json

# ==========================================
# CONFIGURACIÓN INSTITUCIONAL
# ==========================================
ANALYST_CONFIG = {
    "MIN_PIO_BUY": 6, 
    "MIN_PIO_STRONG": 7,
    "MIN_ROIC_BUY": 0.10, 
    "MIN_ROIC_STRONG": 0.12,
    "MAX_TVW_BUY": 0.80, 
    "MAX_TVW_STRONG": 0.77,
    "MAX_DTM_BUY": 1.0, 
    "MAX_DTM_STRONG": 0.9,
    
    # Ajustado para ser realista con blue chips
    "MOS_BUY":    {"DEFENSIVE": 0.15, "CYCLICAL": 0.20, "GROWTH": 0.20, "OTHER": 0.20},
    "MOS_STRONG": {"DEFENSIVE": 0.25, "CYCLICAL": 0.30, "GROWTH": 0.30, "OTHER": 0.30},
    
    # FCF Yield ajustado por bucket
    "FCFY_BUY":    {"DEFENSIVE": 0.04, "CYCLICAL": 0.05, "GROWTH": 0.03, "OTHER": 0.04},
    "FCFY_STRONG": {"DEFENSIVE": 0.06, "CYCLICAL": 0.07, "GROWTH": 0.05, "OTHER": 0.06},
    
    "UP_BUY": 0.20,
    "UP_STRONG": 0.40,
    "REQUIRE_POSITIVE_FCF": True,
}

# Buckets sectoriales
DEFENSIVE_SECTORS = {"Consumer Defensive", "Utilities", "Healthcare"}
CYCLICAL_SECTORS = {"Consumer Cyclical", "Industrials", "Basic Materials", "Energy", "Real Estate"}
GROWTH_SECTORS = {"Technology", "Communication Services"}


def sector_bucket(sector: str) -> str:
    """Clasifica sector en bucket"""
    if sector in DEFENSIVE_SECTORS:
        return "DEFENSIVE"
    if sector in CYCLICAL_SECTORS:
        return "CYCLICAL"
    if sector in GROWTH_SECTORS:
        return "GROWTH"
    return "OTHER"


def issuer_key(ticker: str) -> str:
    """Normaliza ticker para dedup por emisor (clases A/B/C)"""
    t = ticker.upper()
    for suf in ["-A", "-B", "-C", ".A", ".B", ".C"]:
        if t.endswith(suf):
            t = t[: -len(suf)]
    if t in {"FOXA", "FOX"}:
        return "FOX"
    if t in {"GOOGL", "GOOG"}:
        return "GOOG"
    return t


def mos_penalty(dtm, tvw):
    """Penalización de MOS por riesgo de deuda y fragilidad DCF (v3.8)"""
    pen = 0.0
    if not pd.isna(dtm) and dtm >= 1.0:
        pen += 0.05
    if not pd.isna(tvw) and tvw >= 0.80:
        pen += 0.05
    return pen


def analyst_ai_v38(df_input: pd.DataFrame, return_all: bool = False) -> pd.DataFrame:
    """
    Analyst AI V3.8: Selecciona SOLO oportunidades de alta convicción ("JOYAS")
    Integrando WACC dinámico y gates Blue Chip realistas.
    """
    required_cols = [
        "Ticker", "Price", "Sector", "ROIC", "Piotroski", "Growth_Est", "Terminal_g",
        "Intrinsic", "MOS", "FCF", "Debt", "Cash", "MarketCap", "Debt_to_MCap", 
        "FCF_Yield", "DCF_TV_Weight", "WACC"
    ]
    
    # Asegurar columnas (especialmente WACC)
    for c in required_cols:
        if c not in df_input.columns:
            df_input[c] = np.nan
    
    df = df_input.copy()
    
    # Normalización numérica
    num_cols = [
        "Price", "ROIC", "Piotroski", "Growth_Est", "Terminal_g", "Intrinsic", "MOS",
        "FCF", "Depth", "Cash", "MarketCap", "Debt_to_MCap", "FCF_Yield", "DCF_TV_Weight", "WACC"
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
    
    df["Sector"] = df["Sector"].fillna("N/A").astype(str)
    df["Ticker"] = df["Ticker"].astype(str)
    
    cfg = ANALYST_CONFIG
    out = []
    
    for _, r in df.iterrows():
        ticker = r["Ticker"]
        sector = r["Sector"]
        bucket = sector_bucket(sector)
        
        price = r["Price"]
        fair = r["Intrinsic"]
        roic = r["ROIC"]
        pio = r["Piotroski"]
        fcf = r["FCF"]
        fcfy = r["FCF_Yield"]
        dtm = r["Debt_to_MCap"]
        tvw = r["DCF_TV_Weight"]
        g_est = r["Growth_Est"]
        t_g = r["Terminal_g"]
        wacc = r.get("WACC", 0.09)
        
        # Financieras fuera de DCF
        if sector == "Financial Services":
            continue
        
        if pd.isna(price) or pd.isna(fair) or price <= 0 or fair <= 0:
            continue
        
        upside = (fair - price) / price
        real_mos = (fair - price) / fair
        
        flags = []
        if cfg["REQUIRE_POSITIVE_FCF"] and (pd.isna(fcf) or fcf <= 0):
            flags.append("FCF_NEG")
        
        mos_req_buy = cfg["MOS_BUY"][bucket] + mos_penalty(dtm, tvw)
        mos_req_strong = cfg["MOS_STRONG"][bucket] + mos_penalty(dtm, tvw)
        
        fcfy_req_buy = cfg["FCFY_BUY"][bucket]
        fcfy_req_strong = cfg["FCFY_STRONG"][bucket]
        
        # Anti-trampa defensivos
        defensive_trap = False
        if bucket == "DEFENSIVE":
            if (not pd.isna(g_est)) and (g_est > 0.12):
                defensive_trap = True
                flags.append("GROWTH_IMPLAUSIBLE")
            if (not pd.isna(pio)) and (pio <= 5):
                defensive_trap = True
                flags.append("LOW_PIO")
        
        # Fragilidad DCF
        if (not pd.isna(tvw)) and (tvw > 0.85):
            flags.append("TV_HEAVY")
        
        # Gates BUY
        base_ok_buy = (
            (not pd.isna(pio)) and (pio >= cfg["MIN_PIO_BUY"]) and
            (not pd.isna(roic)) and (roic >= cfg["MIN_ROIC_BUY"]) and
            (not pd.isna(fcfy)) and (fcfy >= fcfy_req_buy) and
            (not pd.isna(dtm)) and (dtm <= cfg["MAX_DTM_BUY"]) and
            (not pd.isna(tvw)) and (tvw <= cfg["MAX_TVW_BUY"]) and
            (not defensive_trap) and
            (real_mos >= mos_req_buy)
        )
        
        # Gates STRONG BUY
        base_ok_strong = (
            (not pd.isna(pio)) and (pio >= cfg["MIN_PIO_STRONG"]) and
            (not pd.isna(roic)) and (roic >= cfg["MIN_ROIC_STRONG"]) and
            (not pd.isna(fcfy)) and (fcfy >= fcfy_req_strong) and
            (not pd.isna(dtm)) and (dtm <= cfg["MAX_DTM_STRONG"]) and
            (not pd.isna(tvw)) and (tvw <= cfg["MAX_TVW_STRONG"]) and
            (not defensive_trap) and
            (real_mos >= mos_req_strong)
        )
        
        action, cat = "AVOID", "❌ No pasa filtros"
        
        # Narrative Building
        narrative = []
        if upside >= 0.80: narrative.append("descuento masivo")
        elif upside >= 0.50: narrative.append("claramente subvaluada")
        elif upside >= 0.25: narrative.append("precio atractivo")
        else: narrative.append("precio razonable")
        
        if roic >= 0.18: narrative.append("alta eficiencia de capital")
        elif roic >= 0.12: narrative.append("rentabilidad sólida")
        if pio >= 8: narrative.append("salud financiera robusta")
        
        if dtm <= 0.2: narrative.append("balance muy limpio")
        if wacc < 0.08: narrative.append("perfil de bajo riesgo (WACC bajo)")
        
        why_text = " + ".join(narrative).capitalize() + "."
        
        if base_ok_strong:
            action, cat = "STRONG BUY", "💎 JOYA"
            final_why = f"Convencimiento Alto: {why_text}"
        elif base_ok_buy:
            action, cat = "BUY", "✅ Oportunidad"
            final_why = f"Tesis Sólida: {why_text}"
        else:
            if (real_mos >= 0.15) and (upside >= 0.20):
                action, cat = "WATCH", "⚖️ Casi"
                final_why = "Barata, pero falta confirmar calidad o reducir deuda."
            else:
                final_why = "No cumple criterios de seguridad o precio."
        
        if (not return_all) and (action not in {"STRONG BUY", "BUY"}):
            continue
        
        out.append({
            "Ticker": ticker,
            "Issuer": issuer_key(ticker),
            "Sector": sector,
            "Bucket": bucket,
            "Price": price,
            "Target_Fair": fair,
            "Upside": upside,
            "Real_MOS": real_mos,
            "Piotroski": pio,
            "ROIC": roic,
            "FCF_Yield": fcfy,
            "Debt_to_MCap": dtm,
            "DCF_TV_Weight": tvw,
            "Growth_Est": g_est,
            "Terminal_g": t_g,
            "WACC": wacc,
            "Action": action,
            "Cat": cat,
            "Flags": ",".join(sorted(set(flags))),
            "Why": final_why
        })
    
    res = pd.DataFrame(out)
    if res.empty:
        return res
    
    # Dedup por issuer
    action_rank = {"STRONG BUY": 0, "BUY": 1, "WATCH": 2, "AVOID": 3}
    res["_ar"] = res["Action"].map(action_rank).fillna(99)
    res = res.sort_values(by=["_ar", "Upside"], ascending=[True, False])
    res = res.drop_duplicates(subset=["Issuer"], keep="first").drop(columns=["_ar"])
    
    return res


def add_exit_plan(df_rec: pd.DataFrame) -> pd.DataFrame:
    """
    Construye targets de salida realistas (6M y 12M) usando convergencia parcial
    al fair value, penalizando fragilidad del DCF. Agrega Trim y Stop.
    
    Args:
        df_rec: DataFrame con recomendaciones del Analyst AI
        
    Returns:
        DataFrame con columnas de exit plan añadidas
    """
    if df_rec is None or df_rec.empty:
        return df_rec
    
    dfp = df_rec.copy()
    
    price = pd.to_numeric(dfp["Price"], errors="coerce")
    fair = pd.to_numeric(dfp["Target_Fair"], errors="coerce")
    tvw = pd.to_numeric(dfp.get("DCF_TV_Weight", pd.Series([np.nan] * len(dfp))), errors="coerce")
    
    # Penalización por TV weight (v3.8)
    tv_penalty = np.where(tvw >= 0.75, 0.90, 1.00)
    dfp["TV_Penalty"] = tv_penalty
    
    gap = (fair - price).clip(lower=0)
    
    # Convergencia parcial (v3.8)
    conv6 = np.where(dfp["Action"] == "STRONG BUY", 0.50, 0.35)
    conv12 = np.where(dfp["Action"] == "STRONG BUY", 0.80, 0.60)
    
    dfp["Conv_6M"] = conv6
    dfp["Conv_12M"] = conv12
    
    # Targets base
    tgt6 = price + gap * conv6 * tv_penalty
    tgt12 = price + gap * conv12 * tv_penalty
    
    # Caps operativos
    cap6 = np.where(dfp["Action"] == "STRONG BUY", 1.20, 0.90)
    
    dfp["Target_6M"] = np.minimum(tgt6, price * (1 + cap6))
    dfp["Target_12M"] = tgt12 # Sin cap a 12m
    
    dfp["Upside_6M"] = (dfp["Target_6M"] - price) / price
    dfp["Upside_12M"] = (dfp["Target_12M"] - price) / price
    
    # Trim: toma parcial al 70% del camino al Target_6M
    dfp["Trim_6M"] = price + (dfp["Target_6M"] - price) * 0.70
    
    # Stop: STRONG -12%, BUY -10%
    stop_pct = np.where(dfp["Action"].eq("STRONG BUY"), 0.12, 0.10)
    dfp["Stop_Price"] = price * (1 - stop_pct)
    
    # Reordenar columnas principales
    cols_front = [
        "Ticker", "Action", "Cat", "Bucket",
        "Price", "Target_Fair", "Target_6M", "Target_12M",
        "Upside", "Upside_6M", "Upside_12M", "Real_MOS",
        "Trim_6M", "Stop_Price",
        "Piotroski", "ROIC", "FCF_Yield", "Debt_to_MCap", "DCF_TV_Weight",
        "Conv_6M", "Conv_12M", "TV_Penalty",
        "Flags", "Why"
    ]
    cols_front = [c for c in cols_front if c in dfp.columns]
    cols_rest = [c for c in dfp.columns if c not in cols_front]
    
    return dfp[cols_front + cols_rest]


class PortfolioRefiner:
    """
    The Analyst AI V7 - Wrapper para endpoint /refine
    Selección institucional de JOYAS con gates estrictos + Exit Plan
    """
    
    def __init__(self, results_data, return_all: bool = False):
        """
        Args:
            results_data: Dict con los resultados del Oracle Screener
            return_all: Si True, incluye WATCH/AVOID además de BUY/STRONG BUY
        """
        self.raw_data = results_data
        self.return_all = return_all
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
        """Pipeline completo de refinamiento con Analyst AI V7"""
        print("=" * 60)
        print("🎩 The Analyst AI V7 (FULL)")
        print("   Target 6M/12M + Trim/Stop + Filtro Oportunidad")
        print("=" * 60)
        
        if not self.load_data():
            return None
        
        # Paso 1: Analyst AI V3.8 (selección de JOYAS)
        print("\n🧠 Ejecutando Analyst AI V3.8: Joyas-only (WACC Aware)...")
        self.refined_df = analyst_ai_v38(self.df, return_all=self.return_all)
        
        if self.refined_df is None or self.refined_df.empty:
            print("⚠️ No se encontraron oportunidades que pasen los filtros estrictos")
            return self.export_to_dict()
        
        # Paso 2: Exit Plan (Target 6M/12M + Trim/Stop)
        print("📊 Calculando Exit Plan (Target 6M/12M + Trim/Stop)...")
        self.refined_df = add_exit_plan(self.refined_df)
        
        # Generar estadísticas
        stats = self.get_summary_stats()
        
        print("\n" + "=" * 60)
        print("✅ Analyst AI V7 Completado")
        print("=" * 60)
        print(f"\n📊 Resultados:")
        print(f"   💎 STRONG BUY: {stats['strong_buy_count']}")
        print(f"   ✅ BUY: {stats['buy_count']}")
        if self.return_all:
            print(f"   ⚖️ WATCH: {stats['watch_count']}")
            print(f"   🏦 Bancos: {stats['banks_count']}")
        print("=" * 60)
        
        return self.export_to_dict()
    
    def get_summary_stats(self):
        """Genera estadísticas del refinamiento"""
        if self.refined_df is None or self.refined_df.empty:
            return {
                'total_reviewed': 0,
                'strong_buy_count': 0,
                'buy_count': 0,
                'watch_count': 0,
                'banks_count': 0,
                'by_action': {},
                'by_bucket': {}
            }
        
        stats = {
            'total_reviewed': len(self.refined_df),
            'by_action': self.refined_df['Action'].value_counts().to_dict(),
            'by_bucket': self.refined_df['Bucket'].value_counts().to_dict() if 'Bucket' in self.refined_df.columns else {},
            'strong_buy_count': len(self.refined_df[self.refined_df['Action'] == 'STRONG BUY']),
            'buy_count': len(self.refined_df[self.refined_df['Action'] == 'BUY']),
            'watch_count': len(self.refined_df[self.refined_df['Action'] == 'WATCH']),
            'banks_count': len(self.refined_df[self.refined_df['Action'] == 'VALUAR P/B']),
        }
        
        # Métricas promedio para recomendaciones de compra
        buys = self.refined_df[self.refined_df['Action'].isin(['STRONG BUY', 'BUY'])]
        if not buys.empty:
            stats['avg_upside'] = float(buys['Upside'].mean()) if 'Upside' in buys.columns else None
            stats['avg_upside_6m'] = float(buys['Upside_6M'].mean()) if 'Upside_6M' in buys.columns else None
            stats['avg_upside_12m'] = float(buys['Upside_12M'].mean()) if 'Upside_12M' in buys.columns else None
            stats['avg_mos'] = float(buys['Real_MOS'].mean()) if 'Real_MOS' in buys.columns else None
            stats['avg_wacc'] = float(buys['WACC'].mean()) if 'WACC' in buys.columns else None
        
        return stats
    
    def export_to_dict(self):
        """Exporta todos los datos refinados"""
        if self.refined_df is None or self.refined_df.empty:
            return {
                'refined_results': [],
                'summary': self.get_summary_stats(),
                'strong_buys': [],
                'buys': [],
                'watch': [],
                'banks': []
            }
        
        # Reemplazar NaN con None para JSON
        df_clean = self.refined_df.replace({np.nan: None})
        
        return {
            'refined_results': df_clean.to_dict('records'),
            'summary': self.get_summary_stats(),
            'strong_buys': df_clean[df_clean['Action'] == 'STRONG BUY'].to_dict('records'),
            'buys': df_clean[df_clean['Action'] == 'BUY'].to_dict('records'),
            'watch': df_clean[df_clean['Action'] == 'WATCH'].to_dict('records') if 'WATCH' in df_clean['Action'].values else [],
            'banks': df_clean[df_clean['Action'] == 'VALUAR P/B'].to_dict('records') if 'VALUAR P/B' in df_clean['Action'].values else []
        }


# Función de conveniencia
def refine_portfolio(results_data, return_all: bool = False):
    """
    Función de conveniencia para refinar resultados
    
    Args:
        results_data: Dict/DataFrame con resultados del Oracle Screener
        return_all: Si incluir WATCH/AVOID (default: solo BUY/STRONG BUY)
        
    Returns:
        Dict con resultados refinados
    """
    refiner = PortfolioRefiner(results_data, return_all=return_all)
    return refiner.refine_all()


# Para uso standalone
if __name__ == "__main__":
    print("=" * 60)
    print("🎩 The Analyst AI V7 (FULL)")
    print("   Target 6M/12M + Trim/Stop + Filtro Oportunidad")
    print("=" * 60)
    print("")
    print("Uso:")
    print("  from portfolio_refiner import PortfolioRefiner")
    print("  refiner = PortfolioRefiner(results_data)")
    print("  refined = refiner.refine_all()")
    print("")
    print("  # O con función de conveniencia:")
    print("  from portfolio_refiner import refine_portfolio")
    print("  refined = refine_portfolio(results_data)")
    print("")
    print("Configuración institucional:")
    print(f"  MIN_PIO_STRONG: {ANALYST_CONFIG['MIN_PIO_STRONG']}/9")
    print(f"  MIN_ROIC_STRONG: {ANALYST_CONFIG['MIN_ROIC_STRONG']*100}%")
    print(f"  MAX_TVW_STRONG: {ANALYST_CONFIG['MAX_TVW_STRONG']*100}%")
    print(f"  UP_STRONG: {ANALYST_CONFIG['UP_STRONG']*100}% upside mínimo")
