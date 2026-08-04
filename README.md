# QA Test Dashboard — Guía de instalación

## Estructura del proyecto

```
qa-dashboard/
├── watcher.py          # Vigilante: detecta cambios y genera results.json
├── publisher.py        # Publicador: hace git push automático a GitHub
├── test_results/       # Carpeta compartida: coloca aquí output.xml y .csv
│   ├── output.xml      ← PC 1 (Robot Framework)
│   └── *.csv           ← PC 2 (Python)
└── dashboard/
    ├── index.html      # El dashboard
    └── results.json    # Generado automáticamente (no editar)
```

---

## Paso 1 — Instalar dependencia

```bash
pip install watchdog
```

---

## Paso 2 — Configurar carpeta compartida

Comparte la carpeta `test_results/` en red local para que ambas PCs puedan escribir ahí:

- **Windows**: Clic derecho → Propiedades → Compartir
- **Linux/Mac**: Usar NFS o simplemente montar con `smbmount`

O si están en la misma máquina, simplemente usa la misma carpeta.

Ajusta la ruta `WATCH_FOLDER` en `watcher.py` si es diferente.

---

## Paso 3 — Opción A: Dashboard en red local

1. Abre una terminal y ejecuta:
   ```bash
   python watcher.py
   ```

2. En otra terminal, sirve el dashboard:
   ```bash
   cd dashboard
   python -m http.server 8080
   ```

3. Abre en cualquier PC de tu red:
   ```
   http://IP-DE-TU-PC:8080
   ```

El dashboard se recarga automáticamente cada 15 segundos.

---

## Paso 4 — Opción B: Dashboard público en Netlify (auto-deploy)

### 4.1 Crear repo en GitHub

```bash
cd qa-dashboard
git init
git add .
git commit -m "init: qa dashboard"
git remote add origin https://github.com/TU_USUARIO/qa-dashboard.git
git push -u origin main
```

### 4.2 Conectar Netlify

1. Ve a [netlify.com](https://netlify.com) → "Add new site" → "Import from Git"
2. Selecciona tu repo
3. Configura:
   - **Base directory**: `dashboard`
   - **Publish directory**: `dashboard`
   - Build command: *(dejar vacío)*
4. Haz clic en "Deploy"

Netlify te dará una URL como `https://tu-sitio.netlify.app`

### 4.3 Activar publisher automático

Con el watcher ya corriendo, abre otra terminal:

```bash
python publisher.py
```

Cada vez que `results.json` cambie, se hará un `git push` y Netlify desplegará automáticamente en ~15 segundos.

---

## Ejecutar todo junto (recomendado)

Crea un script `run_all.py` o usa terminales separadas:

**Terminal 1:**
```bash
python watcher.py
```

**Terminal 2 (solo si usas Netlify):**
```bash
python publisher.py
```

---

## Formato esperado de los CSV

El parser detecta columnas automáticamente. Los nombres recomendados son:

| Columna        | Alternativas aceptadas                  |
|----------------|-----------------------------------------|
| `test_name`    | `name`, `prueba`, `caso`                |
| `status`       | `estado`, `result`, `resultado`         |
| `error_message`| `message`, `msg`, `falla`, `error`      |
| `module`       | `suite`, `clase`, `class`, `archivo`    |
| `timestamp`    | `time`, `fecha`, `date`, `hora`         |

Valores aceptados en `status`: `PASS`, `OK`, `1`, `TRUE` → PASS  /  `FAIL`, `ERROR`, `0`, `FALSE` → FAIL

Si no hay columna `status`, se infiere: si hay mensaje de error → FAIL, si no → PASS.

---

## Personalización

- **Intervalo de recarga**: Cambia `REFRESH_MS = 15000` en `index.html` (en milisegundos)
- **Carpeta de resultados**: Cambia `WATCH_FOLDER` en `watcher.py`
- **Rama de GitHub**: Cambia `GIT_BRANCH` en `publisher.py`
