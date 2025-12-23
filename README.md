# Warren Screener v8.0 - DCF 2-Stage + Quality Focus

## 🎯 Nueva Metodología

Esta versión implementa un enfoque más sofisticado basado en:
- ✅ **ROIC** (Return on Invested Capital) >= 8%
- ✅ **Piotroski Score** >= 5 (calidad financiera)
- ✅ **DCF 2-Stage** con tasa de descuento del 9%
- ✅ **Growth estimado** basado en ROIC y reinversión
- ✅ **Margen de seguridad** calculado vs precio actual
- ✅ **Caché de 24 horas** en Cloud Storage

## 🚀 Despliegue Rápido (3 minutos)

### 1. Edita el script de despliegue

```bash
nano deploy.sh
```

Cambia esta línea:
```bash
PROJECT_ID="tu-project-id"  # ← Pon tu PROJECT_ID aquí
```

### 2. Ejecuta el script

```bash
chmod +x deploy.sh
./deploy.sh
```

¡Eso es todo! El script hará:
- ✅ Crear el bucket de Cloud Storage
- ✅ Configurar permisos
- ✅ Build de la imagen Docker
- ✅ Deploy en Cloud Run

## 📊 Endpoints Disponibles

### 1. `/analyze` - Análisis principal
```bash
curl https://TU_URL/analyze
```

**Respuesta (primera vez, sin caché):**
```json
{
  "total_analyzed": 500,
  "candidates_count": 45,
  "buy_candidates": 12,
  "fair_value": 18,
  "watchlist": 15,
  "execution_time_seconds": 240.5,
  "from_cache": false,
  "top_30": [...],
  "buy_zone": [...],
  "fair_zone": [...],
  "watch_zone": [...]
}
```

**Siguientes veces (con caché):**
```json
{
  "total_analyzed": 500,
  "candidates_count": 45,
  "execution_time_seconds": 0.2,
  "from_cache": true,
  ...
}
```

### 2. `/cache-status` - Estado del caché
```bash
curl https://TU_URL/cache-status
```

### 3. `/clear-cache` - Forzar actualización
```bash
curl https://TU_URL/clear-cache
```

### 4. `/health` - Health check
```bash
curl https://TU_URL/health
```

## 🎓 Metodología Explicada

### 1. ROIC (Return on Invested Capital)
```
ROIC = EBIT * (1 - Tax Rate) / Invested Capital
Invested Capital = Equity + Debt - Cash
```
- **Objetivo:** >= 8%
- **Razón:** Empresas que generan alto retorno sobre el capital invertido

### 2. Piotroski Score
Sistema de puntuación de 9 puntos que evalúa:
- Rentabilidad (Net Income positivo, ROA creciente, etc.)
- Apalancamiento (Deuda decreciente)
- Eficiencia operativa (Margen creciente)

**Objetivo:** >= 5 puntos (calidad financiera sólida)

### 3. DCF 2-Stage (Discounted Cash Flow)

**Stage 1 - Crecimiento (5 años):**
- Tasa de crecimiento estimada: `min(ROIC * 0.5, 14%)`
- Descuento al 9% anual

**Stage 2 - Terminal:**
- Crecimiento perpetuo: 3%
- Valor terminal descontado

**Fórmula:**
```
Intrinsic Value = (Stage 1 PV + Terminal PV + Cash - Debt) / Shares
```

### 4. Margen de Seguridad (MOS)
```
MOS = (Intrinsic Value - Current Price) / Intrinsic Value
```

**Clasificación:**
- 🟢 **Zona de Compra:** MOS > 10%
- 🟡 **Valor Justo:** MOS entre 0-10%
- 🔴 **Watchlist:** MOS < 0% (sobrevalorada)

## 📈 Ventajas vs Versión Anterior

| Característica | Versión 3.0 | Versión 8.0 |
|---------------|-------------|-------------|
| Metodología | Múltiples métricas | ROIC + Piotroski + DCF |
| Valoración | Estática | DCF 2-Stage dinámico |
| Crecimiento | Fijo | Basado en ROIC real |
| Calidad | Score básico | Piotroski Score completo |
| Filtros | 6-7 parámetros | 3 filtros de alta calidad |
| Resultados | Lista única | 3 zonas (Compra/Justo/Watch) |
| Cache | ✅ 24h | ✅ 24h |

## 🧪 Testing

```bash
# Script automático de pruebas
chmod +x test_cache.sh
./test_cache.sh

# O manualmente:
export SERVICE_URL=$(gcloud run services describe warren-screener \
    --region=us-central1 --format="get(status.url)")

# Primera petición (creará caché, ~4 min)
time curl $SERVICE_URL/analyze

# Segunda petición (usará caché, ~0.2 seg)
time curl $SERVICE_URL/analyze

# Ver estado del caché
curl $SERVICE_URL/cache-status | jq '.'

# Limpiar caché
curl $SERVICE_URL/clear-cache
```

## 📝 Ver Logs

```bash
# Ver logs en tiempo real
gcloud run services logs tail warren-screener --region=us-central1

# Mensajes importantes:
# "✓ Usando datos del caché"
# "✓ Resultados guardados en caché"
# "⚠ Caché expirado"
# "🟢 Zona de Compra (MOS > 10%): X"
```

## 💰 Costo Estimado

- **Cloud Storage:** ~$0.10/mes
- **Cloud Run:** ~$5/mes
- **Total:** ~$5/mes

El caché reduce drásticamente el costo porque:
- Solo ejecuta análisis completo 1 vez al día
- Las demás peticiones son instantáneas (solo sirven JSON)

## 🔧 Configuración Avanzada

### Cambiar duración del caché

Edita `main.py`, línea 30:
```python
CACHE_TTL_HOURS = 24  # Cambiar a 12, 48, etc.
```

### Ajustar filtros de calidad

Edita `main.py`, líneas 42-47:
```python
CONFIG = {
    'MAX_WORKERS': 12,
    'MIN_ROIC': 0.08,              # 8% -> ajusta a 10%, 12%, etc.
    'MIN_PIOTROSKI': 5,            # 5 -> ajusta a 6, 7, etc.
    'DISCOUNT_RATE': 0.09,         # 9% -> ajusta según tu perfil
    'MARGIN_OF_SAFETY_VIEW': -0.20 # -20% -> más estricto: 0%
}
```

### Actualización automática diaria

Crear un Cloud Scheduler:
```bash
gcloud scheduler jobs create http warren-daily-update \
    --schedule="0 6 * * *" \
    --uri="https://TU_URL/clear-cache" \
    --http-method=GET \
    --location=us-central1
```

## 🐛 Troubleshooting

### Sin resultados o muy pocos

**Posibles causas:**
1. **Filtros muy estrictos** → Ajusta MIN_ROIC o MIN_PIOTROSKI
2. **Rate limiting de Yahoo Finance** → Espera 1 hora y reintenta
3. **Mercado muy caro** → Normal en bull markets

**Solución:**
```python
# En main.py, líneas 42-47, relaja filtros temporalmente:
'MIN_ROIC': 0.06,           # Baja a 6%
'MIN_PIOTROSKI': 4,         # Baja a 4
'MARGIN_OF_SAFETY_VIEW': -0.30  # Muestra hasta -30%
```

### Error de permisos en Cloud Storage

```bash
# Reconfigurar permisos
SERVICE_ACCOUNT=$(gcloud iam service-accounts list \
    --filter="displayName:Compute Engine default service account" \
    --format="value(email)")

gsutil iam ch serviceAccount:$SERVICE_ACCOUNT:objectAdmin \
    gs://warren-screener-cache
```

### Forzar nueva versión después de cambios

```bash
# Rebuild y redeploy
gcloud builds submit --tag gcr.io/TU_PROJECT_ID/warren-screener

gcloud run deploy warren-screener \
    --image gcr.io/TU_PROJECT_ID/warren-screener \
    --region us-central1
```

## 📁 Estructura de Archivos

```
.
├── main.py              # Código principal v8.0
├── requirements.txt     # Dependencias Python
├── Dockerfile          # Configuración Docker
├── deploy.sh           # Script de despliegue automático
├── test_cache.sh       # Script de pruebas
└── README.md           # Este archivo
```

## ✨ Características v8.0

- ✅ **DCF 2-Stage avanzado** con crecimiento dinámico
- ✅ **ROIC como filtro principal** de calidad
- ✅ **Piotroski Score** para salud financiera
- ✅ **3 zonas de inversión** (Compra/Justo/Watch)
- ✅ **Growth estimado** basado en ROIC real
- ✅ **Caché de 24h** en Cloud Storage
- ✅ **Análisis paralelo** con ThreadPoolExecutor
- ✅ **Fuzzy matching** para campos financieros
- ✅ **Fallback lists** para garantizar universo
- ✅ **Logs detallados** con emojis

## 🎯 Próximos Pasos Recomendados

1. **Monitoreo:** Configura alertas en Cloud Monitoring
2. **Scheduler:** Automatiza limpieza diaria del caché
3. **Custom Domain:** Asigna un dominio personalizado
4. **API Key:** Implementa autenticación si es público
5. **Rate Limiting:** Protege contra abuso

## 📞 Interpretando Resultados

### Buy Zone (MOS > 10%)
Empresas que:
- Tienen alta calidad (ROIC >= 8%, Piotroski >= 5)
- Están subvaloradas según DCF
- Ofrecen margen de seguridad > 10%

**Acción:** Candidatas para compra

### Fair Zone (MOS 0-10%)
Empresas de calidad pero:
- Precio cerca del valor intrínseco
- Margen de seguridad pequeño

**Acción:** Monitorear, esperar correcciones

### Watch Zone (MOS < 0%)
Empresas de calidad pero:
- Sobrevaloradas según DCF
- Precio > valor intrínseco

**Acción:** Watchlist para futuras oportunidades

## 🚀 ¿Listo para desplegar?

```bash
./deploy.sh
```

---

**Versión:** 8.0 - DCF 2-Stage + Quality Focus  
**Última actualización:** Diciembre 2024
