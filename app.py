import subprocess
from threading import Thread
from flask import Flask, request, jsonify, send_file, after_this_request
from flask_cors import CORS
import io

app = Flask(__name__)
CORS(app)

app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024

in_memory_chunks = {}
progress_db = {}
final_outputs = {}

@app.route("/upload_chunk", methods=["POST"])
def upload_chunk():
    chunk = request.files.get("chunk")
    file_id = request.form.get("file_id")
    index = int(request.form.get("index"))

    if not chunk or not file_id or index is None:
        return jsonify({"error": "Missing parameters"}), 400

    if file_id not in in_memory_chunks:
        in_memory_chunks[file_id] = {}
    
    in_memory_chunks[file_id][index] = chunk.read()
    return jsonify({"status": "ok"})

def extract_worker(file_id, config):
    fmt = config.get('format', 'mp3')
    progress_db[file_id] = 0
    
    try:
        chunks_dict = in_memory_chunks.get(file_id, {})
        sorted_indices = sorted(chunks_dict.keys())
        full_data = b"".join(chunks_dict[i] for i in sorted_indices)
        
        in_memory_chunks.pop(file_id, None)

        cmd = [
            "ffmpeg", "-i", "pipe:0",
            "-vn",
            "-ab", config.get('bitrate', '256k'),
            "-ar", config.get('sample_rate', '44100'),
            "-f", fmt,
            "-y",
            "pipe:1"
        ]

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        stdout_data, stderr_data = process.communicate(input=full_data)
        
        final_outputs[file_id] = io.BytesIO(stdout_data)
        progress_db[file_id] = 100
        
    except Exception:
        progress_db[file_id] = -1

@app.route("/extract", methods=["POST"])
def extract():
    data = request.json
    file_id = data.get("file_id")
    
    if file_id not in in_memory_chunks:
        return jsonify({"error": "No data in memory"}), 404

    Thread(target=extract_worker, args=(file_id, data)).start()
    return jsonify({"status": "started"})

@app.route("/progress/<file_id>")
def get_progress(file_id):
    return jsonify({"progress": progress_db.get(file_id, 0)})

@app.route("/download/<file_id>.<fmt>")
def download(file_id, fmt):
    if file_id not in final_outputs:
        return jsonify({"error": "File not found"}), 404

    buffer = final_outputs[file_id]
    buffer.seek(0)

    @after_this_request
    def cleanup(response):
        final_outputs.pop(file_id, None)
        progress_db.pop(file_id, None)
        return response

    return send_file(
        buffer,
        mimetype=f"audio/{fmt}",
        as_attachment=True,
        download_name=f"extracted_audio.{fmt}"
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)