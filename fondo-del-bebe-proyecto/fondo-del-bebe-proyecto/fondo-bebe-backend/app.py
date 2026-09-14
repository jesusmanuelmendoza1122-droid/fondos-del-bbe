"""
Backend del Fondo del Bebé — integración con Wompi.

Flujo:
1. El frontend pide una "referencia + firma" para un monto/donante (POST /crear-cobro).
2. El frontend abre el Widget de Wompi con esos datos (el pago ocurre en Wompi, no aquí).
3. Wompi le avisa a este servidor cuando el pago es aprobado (POST /webhook/wompi).
4. Solo ahí se guarda el donante como confirmado y se suma al total.
5. El frontend consulta GET /donantes para pintar la lista y el total, ya verificados.

Variables de entorno necesarias (nunca las pongas en el HTML):
  WOMPI_PRIVATE_KEY       -> prv_...
  WOMPI_INTEGRITY_SECRET  -> secreto de integridad (para firmar transacciones)
  WOMPI_EVENTS_SECRET     -> secreto de eventos (para verificar el webhook)
  WOMPI_PUBLIC_KEY        -> pub_... (se expone al frontend, no es secreta)
"""

import os
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS

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

DATA_FILE = Path(__file__).parent / "donantes.json"
PENDING_FILE = Path(__file__).parent / "pendientes.json"


def _load(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _save(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    pending = _load(PENDING_FILE)
    pending.append({
        "reference": reference,
        "name": name,
        "message": message,
        "amount": amount_cop,
        "ts": int(time.time() * 1000),
    })
    _save(PENDING_FILE, pending)

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

    # Construimos el string a partir de las propiedades que Wompi indica, en orden
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

    if status == "APPROVED":
        pending = _load(PENDING_FILE)
        match = next((p for p in pending if p["reference"] == reference), None)

        if match:
            confirmed = _load(DATA_FILE)
            # Evita duplicados si Wompi reintenta el webhook
            if not any(d["reference"] == reference for d in confirmed):
                confirmed.append({
                    "reference": reference,
                    "name": match["name"],
                    "message": match["message"],
                    "amount": amount_in_cents // 100,
                    "ts": match["ts"],
                })
                _save(DATA_FILE, confirmed)

            pending = [p for p in pending if p["reference"] != reference]
            _save(PENDING_FILE, pending)

    return jsonify({"ok": True})


@app.route("/donantes", methods=["GET"])
def donantes():
    """Lista pública de aportes ya confirmados, para pintar en la página."""
    confirmed = _load(DATA_FILE)
    confirmed.sort(key=lambda d: d["ts"], reverse=True)
    total = sum(d["amount"] for d in confirmed)
    return jsonify({
        "donors": confirmed,
        "total": total,
        "count": len(confirmed),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
