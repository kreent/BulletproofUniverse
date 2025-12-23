#!/bin/bash

# ============================================================================
# Script de Verificación Pre-Deploy
# Verifica que todos los archivos necesarios estén presentes
# ============================================================================

echo "🔍 Verificando archivos necesarios para deploy..."
echo ""

# Lista de archivos requeridos
REQUIRED_FILES=(
    "main.py"
    "portfolio_refiner.py"
    "post_processor.py"
    "requirements.txt"
    "Dockerfile"
    "deploy.sh"
)

ALL_OK=true

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "✅ $file"
    else
        echo "❌ $file - FALTA!"
        ALL_OK=false
    fi
done

echo ""

if [ "$ALL_OK" = true ]; then
    echo "✅ Todos los archivos están presentes"
    echo ""
    echo "Archivos que se desplegarán:"
    echo "  📄 main.py - Servicio principal"
    echo "  📄 portfolio_refiner.py - Portfolio Manager Review"
    echo "  📄 post_processor.py - Post-procesamiento"
    echo "  📄 requirements.txt - Dependencias"
    echo "  📄 Dockerfile - Configuración de contenedor"
    echo ""
    echo "🚀 Listo para desplegar con ./deploy.sh"
    exit 0
else
    echo ""
    echo "❌ Faltan archivos requeridos"
    echo "   Descarga todos los archivos antes de desplegar"
    exit 1
fi
