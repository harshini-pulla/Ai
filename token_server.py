from flask import Flask, jsonify, request
from flask_cors import CORS
from livekit import api
import os
import json
from dotenv import load_dotenv

load_dotenv()

LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
PORT = int(os.getenv("PORT", 5000))
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "http://localhost:5173")

app = Flask(__name__)
CORS(app)

def load_job_data():
    """Load job data from JSON file"""
    try:
        # Get the directory where the script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(script_dir, 'job_data.json')
        
        with open(json_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        print("Warning: job_data.json not found. Using fallback data.")
        return {
            "title": "Software Developer",
            "description": "Job description file not found. Please contact HR for details.",
            "department": "Technology",
            "location": "Remote",
            "experience_level": "Mid-level",
            "employment_type": "Full-time"
        }
    except json.JSONDecodeError as e:
        print(f"Error parsing job_data.json: {e}")
        return {
            "title": "Position Available",
            "description": "Error loading job description. Please contact HR for details.",
            "department": "Various",
            "location": "TBD",
            "experience_level": "Various",
            "employment_type": "Full-time"
        }
    except Exception as e:
        print(f"Unexpected error loading job data: {e}")
        return {
            "title": "Open Position",
            "description": "Unable to load job details at this time. Please try again later.",
            "department": "Various",
            "location": "TBD",
            "experience_level": "Various",
            "employment_type": "Full-time"
        }

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

@app.route("/job", methods=["GET"])
def get_job():
    """Get job title and description from JSON file"""
    try:
        job_data = load_job_data()
        return jsonify({
            "ok": True,
            "job": job_data
        })
    except Exception as e:
        print(f"Error in /job endpoint: {e}")
        return jsonify({
            "ok": False,
            "error": "Failed to load job data",
            "job": {
                "title": "Position Available",
                "description": "Error loading job details. Please contact HR for more information.",
                "department": "Various",
                "location": "TBD"
            }
        }), 500

@app.route("/job/reload", methods=["POST"])
def reload_job():
    """Reload job data from JSON file (useful for updates without server restart)"""
    try:
        job_data = load_job_data()
        return jsonify({
            "ok": True,
            "message": "Job data reloaded successfully",
            "job": job_data
        })
    except Exception as e:
        print(f"Error reloading job data: {e}")
        return jsonify({
            "ok": False,
            "error": "Failed to reload job data"
        }), 500

if __name__ == "__main__":
    # Load job data on startup to verify JSON file
    print("Loading job data...")
    job_data = load_job_data()
    print(f"Loaded job: {job_data['title']} - {job_data['department']}")
    
    app.run(host="0.0.0.0", port=PORT, debug=True)