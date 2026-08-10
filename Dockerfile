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

# Headless Chromium for the OWL/Hoot browser suites.
#
# `HttpCase.browser_js` shells out to the first of google-chrome / chromium /
# chromium-browser it finds on PATH (odoo/tests/common.py::_find_executable) and
# *skips* the test when there is none. Ubuntu 24.04's `chromium` package is only
# a stub that tells you to install a snap, which cannot run in a container — so
# we take the browser from Playwright instead. It publishes builds for both
# amd64 (CI) and arm64 (Apple Silicon dev machines), which the Chrome apt repo
# does not.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN /opt/odoo-venv/bin/pip install --no-cache-dir playwright \
    && /opt/odoo-venv/bin/playwright install --with-deps chromium \
    && ln -s "$(find /opt/playwright -type f -path '*chrome-linux*' -name chrome | head -n 1)" \
        /usr/local/bin/chromium \
    && chmod -R a+rX /opt/playwright \
    && rm -rf /var/lib/apt/lists/*

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