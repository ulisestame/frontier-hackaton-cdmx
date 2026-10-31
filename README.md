# Kipu Pay · corpus anonimizado (Reto PII)

Servicio HTTP que regenera, desde el API de fuentes, una versión seudonimizada del corpus de soporte de Kipu Pay: chats, documentos y tablas. La publica en cuatro archivos: `chats.jsonl`, `docs.jsonl`, `tables.jsonl` y `entities.json`.
- Cada persona recibe un seudónimo consistente en todas las fuentes y entre corridas, de la misma categoría que el original: un nombre por un nombre del mismo género, un correo por un correo, una cédula con formato válido.
- Las organizaciones, marcas, lugares y figuras públicas se conservan.
- El mismo servicio anonimiza en vivo registros nuevos con los seudónimos ya publicados (`POST /v1/anonymize`).

El porqué de cada decisión está en [DECISIONS.md](DECISIONS.md). El documento de diseño y el diagrama de arquitectura están en [`design-site/`](design-site/), publicados en <https://ulisestame-frontier-hackaton-cdmx.vercel.app/>.

## Arquitectura

- **Ingesta** (`src/anon/sources.py`, `src/anon/parse.py`).
  - Descarga el API de fuentes bajo su límite de 600 peticiones por minuto, en una carpeta temporal que se mueve de forma atómica.
  - Normaliza chats, documentos (md, html, pdf) y tablas (CSV y XML) al esquema de salida, y reconcilia los ids con `record_index`.
- **Registro de identidades** (`src/anon/core/engine.py`). Las tablas son el ancla. Una persona se reconoce por sus identificadores duros (cédula, correo, celular, llaves `CL-`, `KP-`, `PQR-`, `TX-`, `PG-`). Dos homónimos nunca se funden por el nombre.
- **Detección** (`engine.py`).
  - Reglas para nombres conocidos y desconocidos, correos (también deletreados), celulares, cédulas, direcciones, fechas de nacimiento, placas, pasaportes, tarjetas y cuentas, handles y slugs en nombres de archivo.
  - Una lista de organizaciones, marcas, lugares y figuras públicas se conserva.
- **Seudónimos** (`src/anon/fakes.py`). HMAC(secreto, persona) decide cada valor, con el formato y la categoría del original. El mapa se persiste: una persona ya publicada conserva su seudónimo cuando las fuentes crecen.
- **Autoverificación y salida** (`src/anon/core/pipeline.py`).
  - Antes de publicar, cada forma real se busca en toda la salida con el criterio del validador oficial.
  - Los cuatro archivos se escriben aparte y se publican de golpe.
- **Corrida en un proceso aparte, estado en un volumen** (`src/anon/api.py`, `jobs.py`, `cli.py`).
  - `POST /v1/run` lanza el pipeline en un proceso supervisado: se relanza si muere y se corta a los 115 minutos.
  - Todo el estado vive en disco (`STATE_DIR`): trabajos, salidas publicadas y el mapa de seudónimos. Así `/health` y `/run/{id}` responden siempre.

## Correr localmente

Requisitos: Python 3.12 y [uv](https://docs.astral.sh/uv/). Node 20 o más nuevo solo hace falta para el validador oficial.

```bash
uv sync
./run.sh                                   # http://localhost:9000/v1
curl http://localhost:9000/v1/health
```

Una corrida contra el API de fuentes:

```bash
curl -X POST http://localhost:9000/v1/run -H 'Content-Type: application/json' \
  -d '{"sources_url": "<url del API de fuentes>/v1", "token": "<token de equipo>"}'
curl http://localhost:9000/v1/run/<job_id>          # repetir hasta "status": "done"
curl -O http://localhost:9000/v1/output/chats.jsonl
```

Sin servidor, una corrida directa a una carpeta. Toma la URL y el token de `FUENTES_URL` y `FUENTES_TOKEN`:

```bash
uv run --env-file .env python -m anon.cli once --out output/
```

### Variables de entorno

| Variable | Para qué | Por defecto |
| --- | --- | --- |
| `ANON_SECRET` | Secreto de los seudónimos deterministas. Se fija una vez y no se cambia: cambiarlo cambia todos los seudónimos. | uno de desarrollo; en producción, siempre uno propio |
| `STATE_DIR` | Estado del servicio y del pipeline. | `./state` (en Docker, `/data/state`) |
| `PORT` | Puerto HTTP. | `9000` |
| `FUENTES_URL`, `FUENTES_TOKEN` | API de fuentes para los scripts locales y `anon.cli once`. El servicio los recibe en `POST /v1/run`. | — |
| `TEAM_NAME`, `LLM_MODELS`, `APP_VERSION` | Lo que reporta `/v1/health`. | `ulisestame`, vacío, sha de git o `0.1.0` |

Ajustes avanzados:
- `RUN_TIMEOUT_SECONDS`: 6900.
- `MAX_RELAUNCHES`: 2.
- `ANONYMIZE_TIMEOUT_SECONDS`: 55.
- `ANONYMIZE_CONCURRENCY`: 4.
- `OUTPUT_KEEP`: 3.

`.env` y `data/` están en `.gitignore`: los secretos y los datos del reto nunca se versionan.

## Validar localmente

1. **Datos del reto.** Quedan en `data/`, que git ignora.

   ```bash
   uv run --env-file .env python scripts/fetch_sources.py data/fuentes/raw   # fuentes, record_index y tests públicos
   unzip sample.zip -d data/sample                                           # GET /sample.zip del API de fuentes
   ```

2. **Validador oficial.** `validar.mjs` viene en el paquete del reto y no se incluye aquí. Va en `material-reto/validar.mjs`, una carpeta ignorada por git.
3. **Calificar una corrida local** como lo haría el jurado: validador oficial más el runner de tests.

   ```bash
   uv run python scripts/check_local.py sample   # muestra: validador + 13 tests de muestra
   uv run python scripts/check_local.py real     # corpus real: validador + 5 tests públicos
   ```

Resultados de esta versión:
- **Real:** validador OK y 5/5 tests públicos.
- **Muestra:** validador OK y 12/13. `sample_01` también falla con la salida ideal, porque el runner local solo acepta el nombre completo del seudónimo.

`scripts/watch_sources.py` vigila el API de fuentes y termina con un diff en cuanto el corpus crece.

## API

Raíz `/v1`, todo en UTF-8 y sin autenticación, como pide el contrato del reto. Si llega un header `Authorization`, se acepta.

| Método y ruta | Qué hace |
| --- | --- |
| `GET /v1/health` | `{status, team, version, models}`. |
| `POST /v1/run` | Recibe `{sources_url, token}`, lanza una corrida y responde 202 con `job_id`. Si ya hay una en curso, devuelve esa. |
| `GET /v1/run/{job_id}` | Estado (`queued`, `running`, `done`, `failed`), registros por fuente, costo en tokens y segundos, y el error si falló. |
| `GET /v1/output/{archivo}` | `chats.jsonl`, `docs.jsonl`, `tables.jsonl` o `entities.json` de la última corrida terminada. Responde 404 antes de la primera. |
| `POST /v1/anonymize` | `{source, records}` con hasta 50 registros del esquema normalizado. Devuelve los mismos ids anonimizados y las entidades usadas. Responde 422 si un registro está fuera de esquema y 504 si pasan 55 s. |
| `GET /v1/entities` | El diccionario completo de la última corrida (solo para el jurado). |

## Despliegue

- **Dockerfile:** `python:3.12-slim` con uv, dependencias congeladas por `uv.lock`, estado en `/data/state`.
- **`railway.toml`:** build con el Dockerfile, healthcheck en `/v1/health`, reinicio ante fallo y una sola réplica.
- **En Railway:**
  - un volumen montado en `/data`;
  - `ANON_SECRET`, fijado una vez y nunca cambiado;
  - `PORT`, en el que el contenedor escucha (9000 por defecto).
- **`run.sh` es el punto de entrada:** arranca uvicorn con un solo worker, lo reinicia si se cae y reenvía SIGTERM al apagar.
- **Nunca redesplegar durante una corrida de evaluación.** El contenedor se reinicia y la corrida vuelve a empezar. El servicio la relanza con el mismo `job_id`, pero consume parte de las dos horas.

## Tests

```bash
uv run pytest -q
```

Los tests que necesitan los datos del reto (`data/`, nunca versionado) se saltan si no están. El resto usa solo valores inventados.

## Estructura del repositorio

```
src/anon/
  api.py              API HTTP /v1
  jobs.py             corridas: estado en disco, proceso aparte, salida atómica, relanzamiento y watchdog
  cli.py              python -m anon.cli run | once
  sources.py          descarga del API de fuentes
  parse.py            normalización de chats, documentos y tablas
  fakes.py            fábrica de seudónimos deterministas
  lexicon/            nombres, apellidos, lugares, ocupaciones
  core/engine.py      registro de identidades, detección y render
  core/pipeline.py    corrida completa, entities.json, autoverificación y /anonymize en vivo
  core/textnorm.py    normalización de texto para las búsquedas
scripts/              fetch_sources.py, check_local.py, watch_sources.py
tests/                pytest
design-site/          documento de diseño y diagrama de arquitectura (sitio estático)
tools/design-export/  exportación del diagrama a PNG
Dockerfile, railway.toml, run.sh, pyproject.toml, uv.lock
```
