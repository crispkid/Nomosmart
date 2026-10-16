# Optional FTPS enterprise CA

FTPS always verifies the certificate chain, validity and hostname. With
`FTPS_CA_CERT_PATH` empty, normal system trust applies.

To add a public enterprise CA, set `FTPS_CA_DIRECTORY` to an operator-controlled
directory and `FTPS_CA_CERT_PATH=/etc/nomosmart/ftps-ca/enterprise-ca.pem` in the
uncommitted deployment configuration. Put the public PEM CA at that filename in
the directory. Compose mounts the directory read-only into backend and worker.
Never put private keys or credentials here or commit enterprise trust material.

For Helm, set `ftpsCa.configMapName` to an existing ConfigMap containing the public
PEM under `ftpsCa.key` (default `ca.crt`). The chart mounts it read-only and sets
the container path. Backend and worker must both receive updated material.

After changing trust, reload the affected application processes and test saved
connections again. Historical successes become stale when their FTPS policy or
trust fingerprint changes. Missing or malformed configured trust fails closed;
there is no option to disable FTPS certificate verification. A 550 reply means
the file cannot be accessed; verify both its path and the remote account's rights.
