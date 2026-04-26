# Tramo PM API — Gateway Odoo 18 CE

Servicio FastAPI que media entre el frontend de Tramo PM
([`jseborga/project2026`](https://github.com/jseborga/project2026)) y Odoo 18 CE.

## Por qué existe

Por seguridad y por desacoplamiento: el frontend NO habla XML-RPC con Odoo
directamente (eso expondría API keys en el browser y haría imposible
multi-usuario / cache / orquestación). El gateway:

- **Auth**: valida credenciales contra Odoo, emite JWT cookie al frontend.
- **Multi-empresa**: maneja `allowed_company_ids` y filtra todas las queries.
- **Cache**: futura capa Redis para queries pesadas (catálogo APU, etc.).
- **Eventos de escritura**: convierte acciones del app (consumo de material,
  certificación de subcontrato) en operaciones Odoo idempotentes.

## Arquitectura

```
[Frontend React]  ──cookie JWT──→  [Tramo PM API]  ──XML-RPC──→  [Odoo 18 CE]
```

### Estructura

```
project2026-api/
├── app/
│   ├── main.py          # FastAPI app + CORS + routers
│   ├── api/
│   │   └── auth.py      # /auth/login, /auth/logout, /auth/me
│   └── core/
│       ├── config.py    # Settings vía env
│       ├── odoo.py      # Cliente XML-RPC
│       └── security.py  # JWT + dependency current_session
├── scripts/
│   └── discover_odoo.py # Introspección del schema Odoo (one-shot, dev)
├── tests/
├── pyproject.toml
├── Dockerfile           # python:3.12-slim + uvicorn
├── .env.example
└── README.md
```

## Cómo correrlo

### Local (dev)

```bash
cd project2026-api
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp .env.example .env       # editar con creds reales
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Test rápido:
```bash
curl http://localhost:8000/health
curl -c cookies.txt -H 'content-type: application/json' \
  -d '{"login":"tu@dominio.com","api_key":"AQUI_EL_KEY"}' \
  http://localhost:8000/auth/login
curl -b cookies.txt http://localhost:8000/auth/me
```

### Docker

```bash
docker build -t tramo-pm-api .
docker run --rm -p 8000:8000 --env-file .env tramo-pm-api
```

### Deploy en EasyPanel

1. Crear nuevo servicio **App** apuntando a `jseborga/project2026-api`, branch `main`.
2. Build: **Dockerfile** (auto-detectado).
3. Network: puerto interno **8000**.
4. **Environment**: pegar el contenido de `.env.example` editado con valores reales.
   Mínimo: `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_API_KEY`, `JWT_SECRET`,
   `FRONTEND_ORIGIN`.
5. Deploy.

## Introspección del schema Odoo

Antes de codear endpoints específicos, conviene mapear los modelos
(especialmente `construction_apu` y los core que vamos a tocar):

```bash
cp .env.example .env       # editar
set -a && source .env && set +a
python -m scripts.discover_odoo > schema.md
```

`schema.md` queda gitignored — es solo para diseño.

## Endpoints actuales (fase 0+1)

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/health` | — | Liveness check (200 ok) |
| POST | `/auth/login` | — | Body `{login, api_key, company_id?}` → setea cookie y devuelve sesión |
| POST | `/auth/logout` | — | Borra cookie |
| GET | `/auth/me` | cookie | Sesión actual |

Próximos (después de leer schema):

- `GET /catalog/items` — lista items APU
- `GET /catalog/categories` — lista rubros
- `GET /projects` — proyectos accesibles del usuario en empresa activa
- `GET /projects/{id}/contracts` — POs y SOs vinculadas

## Notas de seguridad

- El JWT actual incluye `key` (API key del usuario) en su payload. **Esto es OK
  para HS256 firmado y httpOnly cookie**, pero NO es ideal a largo plazo.
  Plan: mover a server-side session store (Redis) en fase 2 o 3. Hoy se prioriza
  cero infra extra.
- `JWT_SECRET` por defecto es `dev-not-for-prod` — **falla en producción si no se
  cambia**. Setear un string aleatorio largo en EasyPanel envs.
- CORS hardcoded a `FRONTEND_ORIGIN` — solo el frontend puede usar el gateway.
