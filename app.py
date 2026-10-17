from flask import Flask, send_file
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route("/")
def home():
    return send_file(os.path.join(BASE_DIR, "ina-homepage-v2.html"))

if __name__ == "__main__":
    print("\n✅  INA Homepage running at → http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
