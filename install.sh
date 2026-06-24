#!/bin/bash
# Kvitto-appen – installationsskript för Mac

echo ""
echo "  ⬡  Kvitto-appen – Installation"
echo "  ─────────────────────────────────"
echo ""

# Kontrollera Python
if ! command -v python3 &>/dev/null; then
    echo "  ✗  Python 3 hittades inte."
    echo "     Installera från https://www.python.org"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✓  Python $PYTHON_VERSION hittad"

# Skapa virtuell miljö
if [ ! -d "venv" ]; then
    echo "  →  Skapar virtuell miljö…"
    python3 -m venv venv
fi

# Aktivera och installera
echo "  →  Installerar beroenden…"
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "  →  Sätter ikon på genvägarna…"
DIR="$(pwd)"
venv/bin/python - "$DIR/assets/icon.png" "$DIR/Installera.command" "$DIR/Starta.command" <<'PYEOF' 2>/dev/null || true
import sys
try:
    from AppKit import NSWorkspace, NSImage
    icon_path, *targets = sys.argv[1:]
    icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
    if icon:
        ws = NSWorkspace.sharedWorkspace()
        for target in targets:
            ws.setIcon_forFile_options_(icon, target, 0)
except Exception:
    pass
PYEOF

echo ""
echo "  ✓  Installation klar!"
echo ""
echo "  Nästa steg:"
echo "  1. Öppna ~/.kvitto-appen/gmail_credentials.json"
echo "     och fyll i dina Google OAuth-uppgifter."
echo ""
echo "  2. Öppna ~/.kvitto-appen/outlook_config.json"
echo "     och fyll i ditt Azure App-ID."
echo ""
echo "  3. Starta appen med: ./start.sh"
echo ""
