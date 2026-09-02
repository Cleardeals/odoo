# Start from the official Odoo 19 base image
FROM odoo:19.0

# Switch to root user to install dependencies
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
RUN python3 -m venv --system-site-packages /opt/odoo-venv
ENV PATH="/opt/odoo-venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/odoo-venv"

# Upgrade pip
RUN /opt/odoo-venv/bin/pip install --upgrade pip

# Install additional Python dependencies for Odoo
COPY ./requirements.txt /tmp/requirements.txt
RUN /opt/odoo-venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# ── Bake the application code INTO the image ──────────────────────────────────
#
# custom_addons used to reach the container as a bind mount from the VM's git
# checkout. That made an image tag meaningless: two containers running the same
# image SHA could be running different application code, depending on what the
# VM had checked out. It also made rollback a fiction — re-pinning the previous
# image left the new addons sitting on disk, still mounted.
#
# Baking them in is what makes ":$SHORT_SHA" an honest answer to "what is in
# production", and what makes the deploy script's rollback actually roll back.
# NOT under /mnt/extra-addons. The odoo:19.0 base image declares
#   VOLUME ["/mnt/extra-addons", "/var/lib/odoo"]
# so at runtime Docker mounts an ANONYMOUS EMPTY VOLUME over that path and
# silently hides anything baked beneath it. That took production down: the
# addons vanished, the leads module never loaded, and the UI failed with
# KeyNotFoundError on a view controller while crons died on KeyError 'leads.new'.
#
# Nothing here is wrong with COPY — the path was. /opt is not a declared volume,
# so the baked code survives.
COPY --chown=odoo:odoo ./custom_addons /opt/cleardeals-addons

# Copy and set permissions for the custom entrypoint
COPY ./entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Set correct ownership for the venv
RUN chown -R odoo:odoo /opt/odoo-venv

# Switch back to the non-root 'odoo' user
USER odoo

# Set the entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["odoo"]