# Start from the official Odoo 18 base image
FROM odoo:18.0

# Switch to root user
USER root

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    python3-venv \
    python3-full \
    libsasl2-dev \
    libldap2-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment with access to system packages
# This is the key change to solve the ModuleNotFoundError
RUN python3 -m venv --system-site-packages /opt/odoo-venv
ENV PATH="/opt/odoo-venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/odoo-venv"

# Upgrade pip
RUN /opt/odoo-venv/bin/pip install --upgrade pip

# Install additional Python dependencies for Odoo
COPY ./requirements.txt /tmp/requirements.txt
RUN /opt/odoo-venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# Copy and set permissions for the custom entrypoint
COPY ./entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Set correct ownership for all files
RUN chown -R odoo:odoo /opt/odoo-venv

# Switch back to the non-root 'odoo' user
USER odoo

# Set the entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["odoo"]
