#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  IEAS Full-Stack Launcher — LAN Edition
#  Starts: Flask homepage (port 5000) + Streamlit login (port 8501)
# ─────────────────────────────────────────────────────────────

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Detect LAN IP ─────────────────────────────────────────────
LAN_IP=$(hostname -I | awk '{print $1}')
if [ -z "$LAN_IP" ]; then
    LAN_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
fi
if [ -z "$LAN_IP" ]; then
    LAN_IP="<your-server-ip>"
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        Indian Naval Academy — IEAS Launcher          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Check dependencies ────────────────────────────────────────
if ! python3 -c "import flask" &>/dev/null; then
    echo "⚠  Flask not found. Installing..."
    pip install flask --quiet
fi

if ! command -v streamlit &>/dev/null; then
    echo "⚠  Streamlit not found. Installing..."
    pip install streamlit --quiet
fi

# ── Start Flask homepage ──────────────────────────────────────
python3 "$DIR/app.py" &
FLASK_PID=$!
sleep 1

# ── Start Streamlit ───────────────────────────────────────────
streamlit run "$DIR/login.py" \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    --browser.gatherUsageStats false \
    &
STREAMLIT_PID=$!
sleep 2

# ── Print access URLs ─────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                  IEAS IS RUNNING                     ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║                                                      ║"
echo "║  🖥  THIS MACHINE (localhost)                         ║"
echo "║      Homepage  →  http://localhost:5000               ║"
echo "║      Login     →  http://localhost:8501               ║"
echo "║                                                      ║"
echo "║  🌐  LAN ACCESS (share with others on same network)   ║"
echo "║      Homepage  →  http://$LAN_IP:5000          ║"
echo "║      Login     →  http://$LAN_IP:8501          ║"
echo "║                                                      ║"
echo "║  📱  Any device on the same Wi-Fi/LAN can use above  ║"
echo "║                                                      ║"
echo "║  Press  Ctrl+C  to stop                              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Graceful shutdown ─────────────────────────────────────────
trap "echo ''; echo '🛑  Shutting down IEAS...'; kill $FLASK_PID $STREAMLIT_PID 2>/dev/null; exit 0" INT TERM

wait
