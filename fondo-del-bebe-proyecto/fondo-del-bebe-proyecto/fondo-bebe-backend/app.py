"""
Backend del Fondo del Bebé — integración con Wompi + Supabase.

Flujo:
1. El frontend pide una "referencia + firma" para un monto/donante (POST /crear-cobro).
2. El frontend abre el Widget de Wompi con esos datos (el pago ocurre en Wompi, no aquí).
3. Wompi le avisa a este servidor cuando el pago es aprobado (POST /webhook/wompi).
4. Solo ahí se guarda el donante como confirmado y se suma al total.
5. El frontend consulta GET /donantes para pintar la lista y el total, ya verificados.

Los datos se guardan en Supabase (Postgres), no en archivos locales, porque
el disco de Render (plan gratis) es efímero y se borra en cada sleep/redeploy.

Variables de entorno necesarias (nunca las pongas en el HTML ni en el repo):
  WOMPI_PRIVATE_KEY       -> prv_...
  WOMPI_INTEGRITY_SECRET  -> secreto de integridad (para firmar transacciones)
  WOMPI_EVENTS_SECRET     -> secreto de eventos (para verificar el webhook)
  WOMPI_PUBLIC_KEY        -> pub_... (se expone al frontend, no es secreta)
  SUPABASE_URL            -> https://xxxxx.supabase.co
  SUPABASE_SERVICE_KEY    -> la service_role key (o sb_secret_...) de Supabase
"""

import os
import hashlib
import hmac
import time
import uuid

from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client

try:
    from dotenv import load_dotenv
    load_dotenv()  # carga variables desde .env si existe (solo en desarrollo local)
except ImportError:
    pass

app = Flask(__name__)
CORS(app)  # en producción, restringe esto al dominio de tu página

WOMPI_PUBLIC_KEY = os.environ.get("WOMPI_PUBLIC_KEY", "")
WOMPI_PRIVATE_KEY = os.environ.get("WOMPI_PRIVATE_KEY", "")
WOMPI_INTEGRITY_SECRET = os.environ.get("WOMPI_INTEGRITY_SECRET", "")
WOMPI_EVENTS_SECRET = os.environ.get("WOMPI_EVENTS_SECRET", "")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


@app.route("/config", methods=["GET"])
def config():
    """El frontend necesita la llave pública para abrir el widget de Wompi."""
    return jsonify({"publicKey": WOMPI_PUBLIC_KEY})


@app.route("/crear-cobro", methods=["POST"])
def crear_cobro():
    """
    Genera una referencia única y la firma de integridad que exige Wompi
    para poder abrir el widget de pago con un monto que nadie pueda alterar.
    """
    body = request.get_json(force=True) or {}
    amount_cop = int(body.get("amount", 0))
    name = (body.get("name") or "Anónimo").strip()[:80]
    message = (body.get("message") or "").strip()[:200]

    if amount_cop < 1000:
        return jsonify({"error": "Monto inválido"}), 400

    amount_in_cents = amount_cop * 100
    currency = "COP"
    reference = f"bebe-{uuid.uuid4().hex[:12]}"

    # Firma de integridad exigida por Wompi:
    # sha256(referencia + monto_en_centavos + moneda + secreto_integridad)
    raw = f"{reference}{amount_in_cents}{currency}{WOMPI_INTEGRITY_SECRET}"
    signature = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # Guardamos el aporte como "pendiente" hasta que llegue el webhook confirmando el pago
    supabase.table("pendientes").insert({
        "reference": reference,
        "name": name,
        "message": message,
        "amount": amount_cop,
        "ts": int(time.time() * 1000),
    }).execute()

    return jsonify({
        "reference": reference,
        "amountInCents": amount_in_cents,
        "currency": currency,
        "signature": signature,
        "publicKey": WOMPI_PUBLIC_KEY,
    })


@app.route("/webhook/wompi", methods=["POST"])
def webhook_wompi():
    """
    Wompi llama aquí cuando el estado de una transacción cambia.
    Verificamos la firma del evento para asegurarnos de que es realmente Wompi
    quien nos está avisando, no cualquiera enviando un POST falso.
    """
    payload = request.get_json(force=True)

    event_signature = payload.get("signature", {})
    properties = event_signature.get("properties", [])
    checksum_received = event_signature.get("checksum", "")
    timestamp = payload.get("timestamp", "")

    def get_nested(d, path):
        cur = d
        for part in path.split("."):
            cur = cur.get(part, {})
        return cur

    concatenated = ""
    for prop_path in properties:
        value = get_nested(payload.get("data", {}), prop_path)
        concatenated += str(value)
    concatenated += str(timestamp) + WOMPI_EVENTS_SECRET

    checksum_calculated = hashlib.sha256(concatenated.encode("utf-8")).hexdigest()

    if not hmac.compare_digest(checksum_calculated.lower(), str(checksum_received).lower()):
        return jsonify({"error": "Firma inválida"}), 400

    transaction = payload.get("data", {}).get("transaction", {})
    status = transaction.get("status")
    reference = transaction.get("reference")
    amount_in_cents = transaction.get("amount_in_cents", 0)

    if status == "APPROVED" and reference:
        pending_res = supabase.table("pendientes").select("*").eq("reference", reference).execute()
        match = pending_res.data[0] if pending_res.data else None

        if match:
            # Evita duplicados si Wompi reintenta el webhook (reference es UNIQUE en la tabla)
            existing = supabase.table("donantes").select("id").eq("reference", reference).execute()
            if not existing.data:
                supabase.table("donantes").insert({
                    "reference": reference,
                    "name": match["name"],
                    "message": match["message"],
                    "amount": amount_in_cents // 100,
                    "ts": match["ts"],
                }).execute()

            supabase.table("pendientes").delete().eq("reference", reference).execute()

    return jsonify({"ok": True})


@app.route("/donantes", methods=["GET"])
def donantes():
    """Lista pública de aportes ya confirmados, para pintar en la página."""
    res = supabase.table("donantes").select("*").order("ts", desc=True).execute()
    print("DEBUG supabase response:", res, flush=True)
    confirmed = res.data or []
    total = sum(d["amount"] for d in confirmed)
    return jsonify({
        "donors": confirmed,
        "total": total,
        "count": len(confirmed),
    })


@app.route("/debug-supabase", methods=["GET"])
def debug_supabase():
    """Ruta temporal para diagnosticar la conexión a Supabase. Bórrala después."""
    info = {
        "supabase_url_set": bool(SUPABASE_URL),
        "supabase_url_value": SUPABASE_URL,
        "service_key_set": bool(SUPABASE_SERVICE_KEY),
        "service_key_length": len(SUPABASE_SERVICE_KEY) if SUPABASE_SERVICE_KEY else 0,
        "service_key_prefix": SUPABASE_SERVICE_KEY[:15] if SUPABASE_SERVICE_KEY else None,
    }
    try:
        res = supabase.table("donantes").select("*").execute()
        info["query_ok"] = True
        info["raw_data"] = res.data
        info["raw_count"] = getattr(res, "count", None)
    except Exception as e:
        info["query_ok"] = False
        info["error"] = str(e)
        info["error_type"] = type(e).__name__
    return jsonify(info)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
