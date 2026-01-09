#!/bin/bash

# =================================================================
# force_reanalysis.sh - Forzar nuevo análisis limpiando caché
# =================================================================

echo ""
echo "🔄 FORZANDO NUEVO ANÁLISIS"
echo "================================================================"
echo ""

# Obtener URL del servicio
if [ -z "$SERVICE_URL" ]; then
    echo "📍 Detectando URL del servicio..."
    SERVICE_URL=$(gcloud run services describe warren-screener \
        --region=us-central1 \
        --format="get(status.url)" 2>/dev/null)
    
    if [ -z "$SERVICE_URL" ]; then
        echo "❌ No se pudo detectar URL automáticamente"
        echo "   Por favor configura la variable SERVICE_URL:"
        echo "   export SERVICE_URL=https://tu-servicio-url"
        exit 1
    fi
fi

echo "🌐 URL: $SERVICE_URL"
echo ""

# Paso 1: Limpiar caché
echo "1️⃣  Limpiando caché..."
CLEAR_RESPONSE=$(curl -s "$SERVICE_URL/clear-cache")
echo "   $CLEAR_RESPONSE"
echo ""

# Paso 2: Esperar un momento
echo "2️⃣  Esperando 2 segundos..."
sleep 2
echo ""

# Paso 3: Ejecutar nuevo análisis
echo "3️⃣  Iniciando nuevo análisis..."
echo "   ⚠️  Esto tomará ~4 minutos..."
echo ""

START_TIME=$(date +%s)

# Llamar a /analyze y guardar respuesta
ANALYZE_RESPONSE=$(curl -s "$SERVICE_URL/analyze")

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "================================================================"
echo "✅ ANÁLISIS COMPLETADO en ${ELAPSED}s"
echo "================================================================"
echo ""

# Mostrar resultados clave
echo "📊 RESUMEN:"
echo "$ANALYZE_RESPONSE" | python3 -m json.tool | grep -E "(total_analyzed|candidates_count|buy_candidates|fair_value|watchlist|execution_time_seconds|from_cache)"

echo ""
echo "================================================================"
echo ""
echo "💡 Para ver resultados completos:"
echo "   curl $SERVICE_URL/analyze | jq '.'"
echo ""
echo "💡 Para ver top 30:"
echo "   curl $SERVICE_URL/analyze | jq '.top_30'"
echo ""
