# 🚀 Warren Screener v8 - Sistema Completo

## 📋 Descripción

Sistema completo de análisis de acciones con 3 capas:
1. **Análisis Base** (`/analyze`) - DCF 2-Stage + ROIC + Piotroski
2. **Post-Procesamiento** (automático) - Métricas, alertas, watchlists
3. **Portfolio Manager Review** (`/refine`) - Ajustes realistas por sector

---

## 🎯 Pipeline Completo

```
1. /analyze
   ↓
   • Análisis de 500 empresas
   • DCF 2-Stage
   • ROIC + Piotroski
   • Post-procesamiento automático
   ↓
   RESULTADO: 20-40 candidatos

2. /refine (TOMA DATOS DE /analyze)
   ↓
   • Ajusta crecimientos por sector
   • Recalcula valores intrínsecos
   • Clasifica en categorías
   • Detecta trampas de valor
   ↓
   RESULTADO: 💎 Joyas + ✅ Oportunidades
```

---

## 🚀 Despliegue Rápido

### 1. Configurar PROJECT_ID
```bash
nano deploy.sh
# Cambiar: PROJECT_ID="tu-project-id"
```

### 2. Desplegar
```bash
chmod +x deploy.sh
./deploy.sh
```

### 3. Esperar 3-4 minutos
El script:
- ✅ Crea bucket de Cloud Storage
- ✅ Configura permisos
- ✅ Build de imagen Docker
- ✅ Deploy en Cloud Run

---

## 📊 Uso del Sistema

### Paso 1: Ejecutar Análisis
```bash
# Primera vez (tarda ~4 minutos)
curl https://TU_URL/analyze

# Siguientes veces (200ms desde caché)
curl https://TU_URL/analyze
```

**Resultado:** Análisis de ~500 empresas con 20-40 candidatos

### Paso 2: Refinar Resultados
```bash
# Toma automáticamente los datos del paso 1
curl https://TU_URL/refine
```

**Resultado:** Clasificación en categorías + ajustes realistas

---

## 🎓 Endpoints Disponibles

### `/analyze` - Análisis Principal
```bash
curl https://TU_URL/analyze
```

**Respuesta:**
```json
{
  "total_analyzed": 500,
  "candidates_count": 24,
  "results": [...],
  "post_processed": {
    "sector_analysis": {...},
    "alerts": [...],
    "watchlist_aggressive": [...]
  }
}
```

### `/refine` - Portfolio Manager Review
```bash
curl https://TU_URL/refine
```

**Respuesta:**
```json
{
  "status": "success",
  "refined_data": {
    "refined_results": [...],
    "summary": {
      "gems_count": 3,
      "opportunities_count": 5,
      "value_traps_count": 2
    },
    "gems": [...],
    "opportunities": [...],
    "value_traps": [...]
  }
}
```

### `/cache-status` - Estado del Caché
```bash
curl https://TU_URL/cache-status
```

### `/clear-cache` - Limpiar Caché
```bash
curl https://TU_URL/clear-cache
```

### `/health` - Health Check
```bash
curl https://TU_URL/health
```

---

## 💻 Uso desde Python

### Ejemplo Completo
```python
import requests

SERVICE_URL = "https://TU_URL"

# 1. Ejecutar análisis
print("🔍 Analizando...")
analysis = requests.get(f"{SERVICE_URL}/analyze").json()

print(f"Candidatos encontrados: {analysis['candidates_count']}")

# 2. Refinar resultados (usa datos del paso 1 automáticamente)
print("🧠 Refinando...")
refined = requests.get(f"{SERVICE_URL}/refine").json()

# 3. Obtener solo las joyas
gems = refined['refined_data']['gems']

print(f"\n💎 {len(gems)} Joyas Reales encontradas:")
for gem in gems:
    print(f"  {gem['Ticker']} ({gem['Sector']})")
    print(f"    MOS: {gem['Adjusted_MOS']*100:.1f}%")
    print(f"    ROIC: {gem['ROIC']*100:.1f}%")
```

---

## 🧪 Testing

### Test Completo
```bash
# 1. Ejecutar test del refine
chmod +x test_refine.py
python test_refine.py https://TU_URL

# 2. O manualmente:
# Primero ejecuta análisis
curl https://TU_URL/analyze

# Luego refina
curl https://TU_URL/refine | jq '.refined_data.summary'
```

### Ver Logs
```bash
gcloud run services logs tail warren-screener --region=us-central1
```

Busca:
```
🧠 Portfolio Manager Review
📂 Buscando datos en caché...
✅ Datos encontrados en caché
🔍 Refinando 24 candidatos...
✅ Refinamiento completado exitosamente
```

---

## 📋 Categorías del Refine

| Categoría | Criterio | Acción |
|-----------|----------|--------|
| 💎 JOYA REAL | MOS>15% + ROIC>15% + Piotroski≥6 | BUY STRONG |
| ✅ Oportunidad | MOS>15% + ROIC>10% | BUY |
| ⚖️ Precio Justo | MOS 0-15% | HOLD/WATCH |
| ⚠️ Trampa Valor? | MOS>60% (no Tech/Health) | RESEARCH |
| ⚠️ Trampa Valor | MOS>15% pero ROIC<10% | AVOID |
| 🏦 Banco/Seguro | Sector Financiero | Use P/B |
| ❌ Cara/Ajustada | MOS<0% | PASS |

---

## 🔧 Límites de Crecimiento por Sector

El `/refine` aplica estos límites:

| Sector | Límite |
|--------|--------|
| Technology | 15% |
| Healthcare | 12% |
| Consumer Defensive | 6% |
| Utilities | 5% |
| Energy | 5% |

**Ejemplo:**
```
Clorox (Consumer Defensive)
Original: Growth 14% → Intrinsic $196 → MOS 50%
Ajustado: Growth 6% → Intrinsic $107 → MOS 9%
```

---

## 🐛 Troubleshooting

### Error: "No analysis results available"
```bash
# Ejecuta primero /analyze
curl https://TU_URL/analyze

# Luego /refine
curl https://TU_URL/refine
```

### Error: "Portfolio Refiner not available"
```bash
# Verifica que portfolio_refiner.py esté desplegado
# Re-despliega:
./deploy.sh
```

### Solo analiza 90 empresas en lugar de 500
```bash
# Ver SOLUCION_RED.md
# Problema: GitHub bloqueado por red de Cloud Run
# Solución: Lista de respaldo de 350+ tickers incluida
```

---

## 📁 Estructura de Archivos

```
.
├── main.py                    # Servicio principal
├── portfolio_refiner.py       # Motor de refinamiento
├── post_processor.py          # Post-procesamiento
├── Dockerfile                 # Configuración Docker
├── requirements.txt           # Dependencias
├── deploy.sh                  # Script de despliegue
├── test_refine.py            # Script de prueba
├── example_refine.py         # Ejemplos de uso
└── REFINE_GUIDE.md           # Documentación completa
```

---

## 💰 Costos

- **Cloud Storage:** ~$0.10/mes
- **Cloud Run:** ~$5/mes
- **Total:** ~$5/mes

El caché reduce drásticamente costos:
- Sin caché: Análisis cada vez (4 min CPU)
- Con caché: Solo leer JSON (200ms)

---

## 🎯 Workflow Recomendado

### Diario (Automatizado)
```bash
# Limpiar caché cada mañana (6 AM)
0 6 * * * curl https://TU_URL/clear-cache

# Ejecutar análisis (6:05 AM)
5 6 * * * curl https://TU_URL/analyze
```

### Cuando Necesites Decisión
```bash
# 1. Ver estado actual (usa caché del análisis matutino)
curl https://TU_URL/refine

# 2. Obtener solo joyas
curl https://TU_URL/refine | jq '.refined_data.gems[]'

# 3. Ver ajustes realizados
curl https://TU_URL/refine | jq '.refined_data.summary'
```

---

## 🚀 Próximos Pasos

1. **Despliega:** `./deploy.sh`
2. **Analiza:** `curl https://TU_URL/analyze`
3. **Refina:** `curl https://TU_URL/refine`
4. **Integra:** Usa `example_refine.py` como base

---

## 📞 Verificación Rápida

```bash
# Obtener tu URL
export SERVICE_URL=$(gcloud run services describe warren-screener \
    --region=us-central1 --format="get(status.url)")

# Test completo
echo "1. Análisis..."
curl $SERVICE_URL/analyze > /dev/null
echo "✅"

echo "2. Refine..."
curl $SERVICE_URL/refine | jq '.refined_data.summary'
echo "✅"
```

---

**¡Listo para usar! 🎉**

Para más detalles:
- `REFINE_GUIDE.md` - Guía completa del refinamiento
- `POST_PROCESSING_GUIDE.md` - Guía del post-procesamiento
- `SOLUCION_RED.md` - Solución al problema de red
