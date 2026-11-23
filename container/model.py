"""Local English-to-Turkish CPU inference. Weights are mounted read-only."""

import os
import threading
from pathlib import Path

import ctranslate2
import sentencepiece
from flask import Flask, abort, jsonify, request
from waitress import serve

directory = Path(os.getenv("MODEL_DIR", "/models/opus-int8"))
source = sentencepiece.SentencePieceProcessor(model_file=str(directory / "source.spm"))
target = sentencepiece.SentencePieceProcessor(model_file=str(directory / "target.spm"))
engine = ctranslate2.Translator(
    str(directory), device="cpu", compute_type="int8", inter_threads=1, intra_threads=2
)
slot = threading.Lock()
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32768


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/translate")
def translate():
    text = (request.get_json() or {}).get("text")
    if not isinstance(text, str) or not text or len(text) > 8000:
        abort(400)
    pieces = source.encode(text, out_type=str)
    if len(pieces) > 510:
        abort(422)
    with slot:
        result = engine.translate_batch(
            [pieces + ["</s>"]], beam_size=4, max_decoding_length=512
        )[0]
    tokens = result.hypotheses[0]
    if len(tokens) >= 511:
        abort(422)
    return jsonify(text=target.decode(tokens))


if __name__ == "__main__":
    serve(
        app,
        host=os.getenv("BIND", "0.0.0.0"),
        port=int(os.getenv("PORT", "18081")),
        threads=3,
    )
