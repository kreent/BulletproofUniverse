# 🔧 Solución de Problemas - Warren Screener

## ❌ Error: "Portfolio Refiner not available"

### Causa
El archivo `portfolio_refiner.py` no está incluido en el contenedor Docker.

### Solución

#### Paso 1: Verificar archivos locales
```bash
chmod +x verify_files.sh
./verify_files.sh
```

Debes tener estos archivos en el mismo directorio:
- ✅ main.py
- ✅ portfolio_refiner.py
- ✅ post_processor.py
- ✅ requirements.txt
- ✅ Dockerfile
- ✅ deploy.sh

#### Paso 2: Verificar Dockerfile
Abre `Dockerfile` y asegúrate que tenga estas líneas:

```dockerfile
# Copiar el código fuente
COPY main.py .
COPY portfolio_refiner.py .
COPY post_processor.py .
```

#### Paso 3: Re-desplegar
```bash
./deploy.sh
```

#### Paso 4: Verificar
```bash
curl https://TU_URL/health
```

Debe responder:
```json
{
  "status": "healthy",
  "portfolio_refiner_available": true,
  "post_processor_available": true
}
```

---

## ❌ Error: "No analysis results available"

### Causa
No hay datos en caché para refinar.

### Solución
```bash
# 1. Ejecutar análisis primero
curl https://TU_URL/analyze

# 2. Luego refinar
curl https://TU_URL/refine
```

---

## ❌ Solo analiza 90 empresas

### Causa
GitHub está bloqueado en Cloud Run.

### Solución
Ya incluida - el sistema usa una lista de respaldo de 350+ empresas.

Ver: `SOLUCION_RED.md`

---

## ❌ Error: "Cache not available"

### Causa
Cloud Storage no está configurado correctamente.

### Solución
```bash
# Verificar bucket
gsutil ls gs://warren-screener-cache

# Verificar permisos
gsutil iam get gs://warren-screener-cache

# Si no existe, crear
gsutil mb -l us-central1 gs://warren-screener-cache
```

---

## 🔍 Verificación Paso a Paso

### 1. Health Check
```bash
curl https://TU_URL/health | jq
```

Verifica que responda:
```json
{
  "status": "healthy",
  "cache_available": true,
  "post_processor_available": true,
  "portfolio_refiner_available": true
}
```

### 2. Cache Status
```bash
curl https://TU_URL/cache-status | jq
```

### 3. Ejecutar Análisis
```bash
curl https://TU_URL/analyze | jq '.candidates_count'
```

Debe retornar un número (ej: 24)

### 4. Ejecutar Refine
```bash
curl https://TU_URL/refine | jq '.refined_data.summary'
```

Debe retornar estadísticas.

---

## 📋 Checklist de Deploy

Antes de desplegar, verifica:

- [ ] Tienes los 3 archivos Python:
  - [ ] main.py
  - [ ] portfolio_refiner.py  
  - [ ] post_processor.py

- [ ] Dockerfile tiene las 3 líneas COPY

- [ ] requirements.txt existe

- [ ] Has configurado PROJECT_ID en deploy.sh

- [ ] Tienes permisos en GCP

Luego ejecuta:
```bash
./verify_files.sh  # Verificar archivos
./deploy.sh        # Desplegar
```

---

## 🚨 Si Nada Funciona

### Opción 1: Re-deploy desde cero
```bash
# 1. Descargar todos los archivos de nuevo
# 2. Verificar archivos
./verify_files.sh

# 3. Limpiar despliegue anterior
gcloud run services delete warren-screener --region=us-central1

# 4. Desplegar de nuevo
./deploy.sh
```

### Opción 2: Verificar logs
```bash
gcloud run services logs tail warren-screener --region=us-central1
```

Busca errores como:
- `ImportError: No module named 'portfolio_refiner'`
- `ModuleNotFoundError: No module named 'post_processor'`

Si ves estos errores → Falta copiar archivos en Dockerfile

---

## 💡 Comandos Útiles

```bash
# Ver URL del servicio
gcloud run services describe warren-screener \
  --region=us-central1 \
  --format="get(status.url)"

# Ver configuración
gcloud run services describe warren-screener \
  --region=us-central1

# Ver revisiones
gcloud run revisions list \
  --service=warren-screener \
  --region=us-central1

# Forzar nueva revisión
gcloud run deploy warren-screener \
  --image gcr.io/PROJECT_ID/warren-screener \
  --region us-central1
```

---

## 📞 Debug Remoto

```bash
# 1. Conectar a Cloud Shell
gcloud cloud-shell ssh

# 2. Clonar imagen
docker pull gcr.io/PROJECT_ID/warren-screener

# 3. Ejecutar localmente
docker run -p 8080:8080 gcr.io/PROJECT_ID/warren-screener

# 4. En otra terminal, probar
curl localhost:8080/health
```

---

## ✅ Verificación Final

Después de desplegar correctamente, debes poder ejecutar:

```bash
# 1. Health check
curl https://TU_URL/health

# 2. Análisis
curl https://TU_URL/analyze

# 3. Refine
curl https://TU_URL/refine

# 4. Ver joyas
curl https://TU_URL/refine | jq '.refined_data.gems[]'
```

Si todos estos comandos funcionan → ✅ Deploy exitoso!
