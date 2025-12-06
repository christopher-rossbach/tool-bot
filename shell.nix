{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = [
    pkgs.python312
    pkgs.direnv
    pkgs.git
    pkgs.openssl
    pkgs.ffmpeg
  ];
  shellHook = ''
    # Create venv if it doesn't exist
    if [ ! -d ".venv" ]; then
      echo "Creating virtual environment..."
      python -m venv .venv
    fi
    
    # Activate venv
    source .venv/bin/activate
    
    # Upgrade pip and install dependencies
    echo "Syncing dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
    
    echo "Environment ready! Nix shell + venv activated."
    echo "Configure .envrc with your credentials if you haven't already."
  '';
}
