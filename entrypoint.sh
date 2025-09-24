#!/bin/bash
set -e

# Activate the virtual environment
export VIRTUAL_ENV="/opt/odoo-venv"
export PATH="/opt/odoo-venv/bin:$PATH"

# Debug output
echo "Using Python: $(which python3)"
echo "Testing BigQuery import..."
python3 -c "from google.cloud import bigquery; print('BigQuery import successful!')"
echo "Testing Odoo import..."
python3 -c "import odoo; print('Odoo import successful!')"


# --- THE FIX IS HERE ---
# Check if the first argument is 'odoo'. This is the default command.
if [ "$1" = 'odoo' ]; then
  # Remove 'odoo' from the arguments list.
  shift
  # Prepend the full command to run Odoo using the venv's python.
  # This preserves any other arguments passed to the container.
  set -- python3 /usr/bin/odoo "$@"
fi

# Execute the final command.
# This will now be either `python3 /usr/bin/odoo ...` or another command like `bash`.
exec "$@"

