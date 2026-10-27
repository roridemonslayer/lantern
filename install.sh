#!/bin/sh
# Put a `lantern` command on your PATH that runs this copy of lantern.py.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.local/bin"
mkdir -p "$bin"
chmod +x "$here/lantern.py"
ln -sf "$here/lantern.py" "$bin/lantern"
echo "installed: $bin/lantern"
case ":$PATH:" in
  *":$bin:"*) ;;
  *) echo "add this to your ~/.zshrc:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
