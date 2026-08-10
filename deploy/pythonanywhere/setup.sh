#!/usr/bin/env bash
# Clone and set up School Management on PythonAnywhere.
# Run in a PythonAnywhere Bash console:
#   bash deploy/pythonanywhere/setup.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/FRANCIS72351/SCHOOL_MANAGEMENT.git}"
USERNAME="$(whoami)"
PROJECT_DIR="/home/${USERNAME}/SCHOOL_MANAGEMENT"
PYTHON_VERSION="${PYTHON_VERSION:-3.10}"

echo "==> PythonAnywhere setup for user: ${USERNAME}"
echo "==> Project directory: ${PROJECT_DIR}"

if [[ -d "${PROJECT_DIR}/.git" ]]; then
  echo "Repository already cloned. Updating..."
  cd "${PROJECT_DIR}"
  git pull origin main
else
  git clone "${REPO_URL}" "${PROJECT_DIR}"
  cd "${PROJECT_DIR}"
fi

if ! command -v mkvirtualenv >/dev/null 2>&1; then
  echo "mkvirtualenv not found. Enable a Python version on the Web tab first, then retry."
  exit 1
fi

if [[ ! -d "${HOME}/.virtualenvs/schoolmgmt" ]]; then
  mkvirtualenv --python="/usr/bin/python${PYTHON_VERSION}" schoolmgmt
fi

# shellcheck disable=SC1091
source "${HOME}/.virtualenvs/schoolmgmt/bin/activate"

pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp deploy/pythonanywhere/env.example .env
  SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s/change_this_to_a_long_random_string/${SECRET}/" .env
  sed -i "s/YOUR_USERNAME/${USERNAME}/g" .env 2>/dev/null || true
  echo ""
  echo "Created .env — edit ADMIN_PASSWORD before continuing:"
  echo "  nano ${PROJECT_DIR}/.env"
  echo ""
fi

bash deploy/pythonanywhere/init-database.sh "${PROJECT_DIR}"

echo ""
echo "==> Code setup complete."
echo ""
echo "Next steps (PythonAnywhere Web tab):"
echo "  1. Add a new Web app → Manual configuration → Python ${PYTHON_VERSION}"
echo "  2. Source code: ${PROJECT_DIR}"
echo "  3. Virtualenv:   /home/${USERNAME}/.virtualenvs/schoolmgmt"
echo "  4. WSGI file:    copy deploy/pythonanywhere/wsgi.py content"
echo "                   (replace YOUR_USERNAME with ${USERNAME})"
echo "  5. Static files: URL /static/  →  ${PROJECT_DIR}/static/"
echo "  6. Click Reload, then open https://${USERNAME}.pythonanywhere.com"
echo ""
echo "Full guide: PYTHONANYWHERE.md"
