"""Introspección de modelos Odoo.

Uso:
    cd /home/coder/project2026-api
    cp .env.example .env  # editar con creds reales
    python -m scripts.discover_odoo > schema.md

Genera un reporte markdown con:
- Modelos cuyo nombre matchee `construction_apu*`, `apu*` o esté en la lista CORE
- Para cada modelo: campos clave (nombre, tipo, relación si aplica, label)
- Pensado para co-diseñar el mapeo app↔Odoo después de leerlo.
"""

from __future__ import annotations

import os
import sys
from xmlrpc.client import ServerProxy

URL = os.environ.get("ODOO_URL", "").rstrip("/")
DB = os.environ.get("ODOO_DB", "")
USER = os.environ.get("ODOO_USER", "")
KEY = os.environ.get("ODOO_API_KEY", "")

if not all([URL, DB, USER, KEY]):
    sys.stderr.write("Faltan ODOO_URL/ODOO_DB/ODOO_USER/ODOO_API_KEY en el entorno\n")
    sys.exit(1)

# Modelos core de Odoo que nos interesan para el integration map
CORE_MODELS = [
    "res.company", "res.users", "res.partner",
    "project.project", "project.task", "project.milestone",
    "purchase.order", "purchase.order.line",
    "sale.order", "sale.order.line",
    "account.move", "account.move.line",
    "account.analytic.account", "account.analytic.line",
    "stock.move", "stock.picking", "stock.location", "stock.warehouse",
    "product.product", "product.template", "product.category",
    "hr.employee", "hr.contract",
    "ir.module.module",
]

# Patrones para descubrir modelos custom relacionados a APU
PREFIXES = ("construction_apu", "construction.apu", "apu.", "construction.")


def main() -> None:
    common = ServerProxy(f"{URL}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(DB, USER, KEY, {})
    if not uid:
        sys.stderr.write("Authenticate falló — credenciales inválidas\n")
        sys.exit(2)
    obj = ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)

    def kw(model: str, method: str, args: list, kwargs: dict | None = None):
        return obj.execute_kw(DB, uid, KEY, model, method, args, kwargs or {})

    # 0) Versión + módulos APU instalados
    print("# Odoo schema discovery\n")
    print(f"- URL: `{URL}`")
    print(f"- DB: `{DB}`")
    print(f"- User: `{USER}` (uid={uid})")
    version = common.version()
    print(f"- Server: `{version.get('server_version')}` (`{version.get('server_serie')}`)\n")

    apu_modules = kw(
        "ir.module.module", "search_read",
        [[["name", "ilike", "apu"]]],
        {"fields": ["name", "shortdesc", "state", "summary"]}
    )
    print("## Módulos relacionados a APU\n")
    if not apu_modules:
        print("_(ninguno encontrado)_\n")
    for m in apu_modules:
        print(f"- **{m['name']}** ({m['state']}) — {m.get('shortdesc') or ''}")
    print()

    # 1) Modelos custom (no core) que matcheen los prefijos
    custom_models = kw(
        "ir.model", "search_read",
        [[["model", "=like", "%apu%"]]],
        {"fields": ["model", "name", "modules", "transient"]}
    )
    print(f"## Modelos custom matching apu* ({len(custom_models)})\n")
    for m in custom_models:
        flag = " (transient)" if m.get("transient") else ""
        print(f"- `{m['model']}` — {m['name']} _[{m.get('modules') or 'core'}]_{flag}")
    print()

    # 2) Detalle de campos para cada modelo (custom + core seleccionados)
    targets = sorted({m["model"] for m in custom_models} | set(CORE_MODELS))
    print(f"## Campos por modelo ({len(targets)} modelos)\n")
    for model in targets:
        try:
            fields = kw(model, "fields_get", [], {"attributes": ["string", "type", "relation", "required", "readonly", "help", "selection"]})
        except Exception as e:
            print(f"### `{model}`\n\n_(error leyendo campos: {e})_\n")
            continue
        # Filtrar solo lo útil (no _meta, no compute internos opacos)
        rows = []
        for fname, meta in sorted(fields.items()):
            if fname.startswith("_"):
                continue
            t = meta.get("type", "?")
            extra = ""
            if t in ("many2one", "one2many", "many2many") and meta.get("relation"):
                extra = f" → `{meta['relation']}`"
            elif t == "selection" and meta.get("selection"):
                opts = ", ".join(f"{k}" for k, _ in (meta["selection"] or [])[:6])
                extra = f" [{opts}]"
            req = " *required*" if meta.get("required") else ""
            ro = " *readonly*" if meta.get("readonly") else ""
            rows.append(f"  - `{fname}` ({t}{extra}){req}{ro} — {meta.get('string','')}")

        print(f"### `{model}` — {len(rows)} campos\n")
        # Limitamos a 60 filas por modelo para que no explote
        for r in rows[:60]:
            print(r)
        if len(rows) > 60:
            print(f"  - _… ({len(rows)-60} campos más omitidos)_")
        print()


if __name__ == "__main__":
    main()
