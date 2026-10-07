#!/usr/bin/env bash
set -eu
d=$(dirname "$0"); [ -f "$d/install.py" ] || { d=$(mktemp -d); curl -fsSL https://raw.githubusercontent.com/nowherewashere/study-digest/master/install.py -o "$d/install.py"; }
python3 "$d/install.py"
