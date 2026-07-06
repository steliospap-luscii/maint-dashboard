#!/usr/bin/env bash
# Installs a `maintdash` launcher into ~/.local/bin (same pattern as devhub).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
mkdir -p "$BIN"

# First-time setup: seed config.json from the example so new users have
# something to edit.
if [ ! -f "$DIR/config.json" ]; then
  cp "$DIR/config.example.json" "$DIR/config.json"
  echo "→ created config.json from example — edit it to point at your project"
fi
cat > "$BIN/maintdash" <<EOF
#!/usr/bin/env bash
exec python3 "$DIR/maintdash.py" "\$@"
EOF
chmod +x "$BIN/maintdash" "$DIR/maintdash.py"
echo "✓ installed: $BIN/maintdash -> $DIR/maintdash.py"
case ":$PATH:" in
  *":$BIN:"*) echo "✓ $BIN is on your PATH" ;;
  *) echo "! add $BIN to your PATH:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
