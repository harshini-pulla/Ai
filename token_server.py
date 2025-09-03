from flask import Flask, jsonify, request
from flask_cors import CORS
from livekit import api
import os
from dotenv import load_dotenv

load_dotenv()

LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
PORT = int(os.getenv("PORT", 5000))
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "http://localhost:5173")

app = Flask(__name__)
CORS(app, origins=[CORS_ORIGIN])

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "server": "livekit-token-python"})

@app.route("/token", methods=["GET"])
def get_token():
    room_name = request.args.get("roomName")
    participant_name = request.args.get("participantName")

    if not room_name or not participant_name:
        return jsonify({"error": "roomName and participantName are required"}), 400
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        return jsonify({"error": "Server missing LiveKit credentials"}), 500

    # Build token
    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(participant_name)
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )

    return jsonify({"token": token, "url": LIVEKIT_URL})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)