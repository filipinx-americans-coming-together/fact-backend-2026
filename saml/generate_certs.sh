#!/bin/bash
# Generate self-signed SP certificates for SAML request signing.
#
# These are NOT your HTTPS/TLS certificates. They are used by the
# Service Provider to sign and encrypt SAML messages exchanged with
# the UIUC Identity Provider.
#
# Usage:
#   ./saml/generate_certs.sh [hostname]
#
# Example:
#   ./saml/generate_certs.sh fact.psauiuc.org
#
# The generated files (sp-key.pem, sp-cert.pem) are in .gitignore
# and should never be committed to version control.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOSTNAME="${1:-localhost}"

echo "Generating SP certificates for hostname: ${HOSTNAME}"
echo "Output directory: ${SCRIPT_DIR}"

openssl req -x509 -nodes \
    -newkey rsa:2048 \
    -keyout "${SCRIPT_DIR}/sp-key.pem" \
    -out "${SCRIPT_DIR}/sp-cert.pem" \
    -days 7300 \
    -subj "/CN=${HOSTNAME}/O=FACT Conference/C=US"

echo ""
echo "✅ Generated successfully:"
echo "   ${SCRIPT_DIR}/sp-key.pem  (private key — keep secret)"
echo "   ${SCRIPT_DIR}/sp-cert.pem (certificate — share with iTrust)"
echo ""
echo "Next step: Register your SP at http://go.illinois.edu/itrust"
echo "           using the metadata from: http://${HOSTNAME}:8000/saml/metadata/"
