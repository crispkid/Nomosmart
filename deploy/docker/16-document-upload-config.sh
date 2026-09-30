#!/bin/sh
# Derive an include before nginx envsubst. A child script cannot export to the
# later entrypoint scripts; write only this validated numeric location directive.
set -eu
fail() { printf '%s\n' "Invalid document upload edge configuration: $1" >&2; exit 1; }
integer() {
    case "$2" in ''|0*|*[!0-9]*|??????*) fail "$1" ;; esac
}
if [ "${NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB+x}" = x ]; then
    file_limit=$NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB
elif [ "${MAX_UPLOAD_SIZE_MB+x}" = x ]; then
    file_limit=$MAX_UPLOAD_SIZE_MB
else
    file_limit=100
fi
integer NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB "$file_limit"
[ "$file_limit" -le 10240 ] || fail NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB
minimum=$((file_limit + 1))
if [ "${DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB+x}" = x ]; then
    request_limit=$DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB
else
    request_limit=$minimum
fi
integer DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB "$request_limit"
[ "$request_limit" -ge "$minimum" ] && [ "$request_limit" -le 10241 ] || fail DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB
mkdir -p /etc/nginx/includes
printf 'client_max_body_size %sm;\n' "$request_limit" > /etc/nginx/includes/document-upload-size.conf
