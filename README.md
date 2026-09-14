# Fondo del Bebé — Proyecto completo (frontend + backend + Wompi)

## Qué hay en este proyecto
```
fondo-del-bebe.html        <- la página que ve la gente (frontend)
fondo-bebe-backend/
  app.py                   <- servidor Flask (crea cobros y verifica pagos)
  requirements.txt         <- dependencias de Python
  .env.example             <- plantilla de llaves (cópiala como .env)
  .gitignore                <- evita subir el .env y datos sensibles a git
  Procfile                 <- para desplegar en Railway/Render
  README.md                <- este archivo
```

## ✅ Checklist — lo único que tienes que hacer

### 1. Conseguir tus llaves de Wompi
Dashboard de Wompi → Comercio → Configuración → Llaves API / Secretos:
- Llave pública (`pub_...`)
- Llave privada (`prv_...`)
- Secreto de integridad
- Secreto de eventos

Empieza con las llaves de **sandbox** (pruebas) — así puedes probar todo el flujo sin cobrar plata real.

### 2. Configurar el backend
```bash
cd fondo-bebe-backend
cp .env.example .env
```
Abre `.env` y pega tus 4 llaves reales ahí (nunca en el HTML, nunca en git).

### 3. Probarlo local (opcional pero recomendado)
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```
Se levanta en `http://localhost:5000`. Para que Wompi le pueda mandar el webhook a tu computador mientras pruebas, usa `ngrok http 5000` y copia la URL que te da.

### 4. Desplegar el backend (Railway es lo más simple)
1. Sube la carpeta `fondo-bebe-backend/` a un repo de GitHub (el `.gitignore` ya protege tu `.env`).
2. En Railway: "New Project" → "Deploy from GitHub repo" → selecciona el repo.
3. En "Variables" del proyecto, agrega las mismas 4 llaves que pusiste en `.env`.
4. Railway te da una URL pública, ej: `https://fondo-bebe-production.up.railway.app`.

### 5. Conectar el frontend
Abre `fondo-del-bebe.html`, busca el comentario:
```
⚠️ ÚNICO CAMBIO NECESARIO
```
y reemplaza la URL de ejemplo por la URL real que te dio Railway.

### 6. Configurar el webhook en Wompi
En el dashboard de Wompi, en "URL de eventos" pon:
```
https://TU-BACKEND-REAL.up.railway.app/webhook/wompi
```

### 7. Probar de punta a punta
- Abre `fondo-del-bebe.html` en el navegador (o súbelo a cualquier hosting estático: Netlify, Vercel, GitHub Pages, tu propio dominio).
- Haz un aporte de prueba con una tarjeta de pruebas de Wompi (están en su documentación de sandbox).
- Verifica que aparezca en la sección "Registro de aportes" después de unos segundos (tarda en llegar el webhook).

### 8. Pasar a producción
Cuando todo funcione en sandbox, repite el proceso con tus llaves **reales** de Wompi (las de producción, no las de prueba) y actualiza las variables de entorno en Railway.

## Endpoints del backend
- `GET /config` → llave pública para el widget.
- `POST /crear-cobro` → `{ amount, name, message }` → referencia + firma para abrir el widget.
- `POST /webhook/wompi` → lo llama Wompi automáticamente, no lo llames tú.
- `GET /donantes` → `{ donors: [...], total, count }`, solo pagos confirmados.

## Notas importantes
- El total y la lista de donantes **solo se actualizan cuando Wompi confirma el pago** — nadie puede inflar la lista escribiendo en la consola del navegador.
- Este backend guarda los datos en archivos JSON planos (`donantes.json`, `pendientes.json`) que se crean solos la primera vez que corre. Si esperas mucho tráfico o quieres algo más robusto a futuro, se puede migrar a una base de datos real.
- El dinero confirmado en Wompi se gira automáticamente a la cuenta bancaria que registres en tu comercio de Wompi (puede ser tu cuenta Nu o Ualá) en los ciclos que defina Wompi.
