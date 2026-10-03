# Docker Desktop installation validation

[繁體中文](README.zh-TW.md)

Use the `v0.1.2` source or a verified `nomosmart-0.1.2` installation package. This directory contains local PV, Helm configuration and ingress preparation helpers. Keep operator configuration and secrets outside the immutable package. Production installation retains its package verification and onboarding requirements.

Run one method at a time. Compose follows root README Method 1; native development follows Method 4. The steps below provide the local Kubernetes path for Methods 2 and 3. All services are real. The ingress simulation uses an official controller, HTTPS and actual routes. No application login, model requests or product workflow is needed for installation validation.

## Local target and images

Check the context, node names, taints, existing resources, and free ports before creating anything:

```bash
kubectl config current-context
kubectl --context docker-desktop get nodes -o wide
kubectl --context docker-desktop get namespace,pv,storageclass,ingressclass
docker info
docker ps --format '{{.Names}}'
lsof -nP -iTCP:80 -iTCP:443 -sTCP:LISTEN
```

Use the `docker-desktop` context explicitly. The validated environment had three kind nodes sharing one Docker Desktop VM with 8 CPUs and about 32 GB RAM. Count this VM once when comparing workload requests, other running Pods, and the chart's capacity reserve. The Redis topology requires three distinct nodes; only Redis explicitly tolerates the control-plane taint. Put PostgreSQL, RustFS, OpenSearch and Neo4j on untainted workers. Local PVs are for disposable development data and do not provide storage HA.

Build Frontend and Backend from the reviewed checkout using Method 1's generated Compose configuration, without starting Compose services. Select distinct local image tags and record their immutable digests. The helper requires `repository:tag@sha256:<digest>` for both application images. Make those exact references available to **every** Docker Desktop node, either through a reachable registry or the node runtime's image import. `kind load docker-image ... --name desktop` was used in this kind-based environment. Importing a tag alone may be insufficient: the CRI can normalize the reference to `docker.io/<repository>@sha256:<digest>`; verify the exact digest reference in each node before proceeding. Do not replace official dependency images.

From the source root, set unique names and a new private input directory:

```bash
export NOMOSMART_NAMESPACE=nms-install-bundled
export NOMOSMART_CONTROLLER_NAMESPACE=nms-install-bundled-ingress
export NOMOSMART_RELEASE=nomosmart-local
export NOMOSMART_LOCAL="$(mktemp -d "${TMPDIR:-/tmp}/nomosmart-local.XXXXXX")"
chmod 0700 "$NOMOSMART_LOCAL"
export NOMOSMART_FRONTEND_IMAGE='<reviewed-frontend-repository>:<tag>@sha256:<digest>'
export NOMOSMART_BACKEND_IMAGE='<reviewed-backend-repository>:<tag>@sha256:<digest>'
```

The hostname `nomosmart.local` must resolve to loopback. This validation used an existing mapping and did not change `/etc/hosts` or the host trust store. Replace the image placeholders before running the following commands. Create only new, dedicated namespaces; leave OpenLDAP and existing cluster objects untouched.

```bash
kubectl --context docker-desktop create namespace "$NOMOSMART_NAMESPACE"
kubectl --context docker-desktop create namespace "$NOMOSMART_CONTROLLER_NAMESPACE"
./deploy/package/nomosmart-package init \
  --target helm --profile factory_acceptance --app-env development \
  --random-initial-credentials --postgresql-standalone \
  --helm-release "$NOMOSMART_RELEASE" --helm-fullname "$NOMOSMART_RELEASE" \
  --helm-namespace "$NOMOSMART_NAMESPACE" --public-host nomosmart.local \
  --output-dir "$NOMOSMART_LOCAL/package" --no-display
python3 deploy/local/prepare-helm.py \
  --package-dir "$NOMOSMART_LOCAL/package" \
  --namespace "$NOMOSMART_NAMESPACE" --release "$NOMOSMART_RELEASE" \
  --storage-class "$NOMOSMART_NAMESPACE" \
  --ingress-class "$NOMOSMART_CONTROLLER_NAMESPACE" \
  --ingress-namespace "$NOMOSMART_CONTROLLER_NAMESPACE" \
  --frontend-image "$NOMOSMART_FRONTEND_IMAGE" \
  --backend-image "$NOMOSMART_BACKEND_IMAGE" \
  --admin-cidr '127.0.0.1/32,10.244.0.0/16' \
  --output-dir "$NOMOSMART_LOCAL/inputs"
```

Set the admin CIDR to the real proxy source addresses in your environment; never use an unrestricted CIDR. The helper creates private `secrets.json` and non-sensitive `values.json`; it does not apply either. Generated credentials remain in protected files. The local profile uses `APP_ENV=development`, `factory_acceptance`, separate PostgreSQL admin/migration/application/Keycloak identities and random initial credentials. It leaves production defaults unchanged. `dnsOverTcp` uses real TCP DNS for this isolated profile; it resolved observed UDP DNS timeouts without modifying CoreDNS.

## Method 2: explicit static PVs

Render the actual topology and extract its capacity plan:

```bash
helm template "$NOMOSMART_RELEASE" deploy/helm/nomosmart \
  --kube-context docker-desktop --namespace "$NOMOSMART_NAMESPACE" \
  -f deploy/helm/nomosmart/values-docker-desktop.yaml \
  -f "$NOMOSMART_LOCAL/inputs/values.json" \
  > "$NOMOSMART_LOCAL/rendered.yaml"
python3 - "$NOMOSMART_LOCAL" <<'PY'
from pathlib import Path
import json, sys
sys.path.insert(0, 'deploy/installer')
from nomosmart_installer.capacity import rendered_capacity_plan
root = Path(sys.argv[1])
(root / 'capacity-plan.json').write_text(json.dumps(
    rendered_capacity_plan((root / 'rendered.yaml').read_text()), indent=2))
PY
```

Create `placement.json` in that private directory with one explicit entry for every claim in the capacity plan. This local topology needs seven claims: PostgreSQL `5Gi`, Redis `2Gi` × 3, RustFS `10Gi`, OpenSearch `10Gi`, Neo4j `5Gi`. Each entry has `name` (unique PV name), `node` (actual Kubernetes hostname) and `path` (new absolute directory on that node). For example, one entry is:

```json
{
  "data-nomosmart-local-postgresql-0": {
    "name": "nms-install-bundled-postgresql-0",
    "node": "desktop-worker2",
    "path": "/var/local/nomosmart-local/nms-install-bundled/postgresql-0"
  }
}
```

This single-entry example is incomplete by design: add all six remaining claims from `capacity-plan.json` before using it. Assign Redis to three different nodes. Prepare only the dedicated node directories with the service UID/GID: PostgreSQL/Redis `999`, RustFS `10001`, OpenSearch `1000`, Neo4j `7474`; use mode `0700`. Inspect the actual node/container mapping first. These directories live inside the Kubernetes node, not an arbitrary macOS host directory. The manifest helper never creates directories or changes their ownership.

```bash
python3 deploy/local/prepare-static-pvs.py \
  --capacity-plan "$NOMOSMART_LOCAL/capacity-plan.json" \
  --placement "$NOMOSMART_LOCAL/placement.json" \
  --namespace "$NOMOSMART_NAMESPACE" --storage-class "$NOMOSMART_NAMESPACE" \
  --output "$NOMOSMART_LOCAL/pvs.json"
```

Create an operator-owned StorageClass with `provisioner: kubernetes.io/no-provisioner`, `volumeBindingMode: WaitForFirstConsumer` and `reclaimPolicy: Retain`. Its name must match `NOMOSMART_NAMESPACE`. Review and apply that class and `pvs.json`. Every PV must have the exact `claimRef`, capacity, `ReadWriteOnce`, `Filesystem`, `Retain`, local path and hostname affinity. Review free disk capacity with the storage reserve. Do not rely on the cluster's default dynamic class or install a storage product.

The typed installer configuration selects `platform_profile = "docker-desktop"`, `storage_mode = "static-pv"`, this StorageClass, and `static_pv_manifest_file = "/absolute/path/to/pvs.json"`. This file is part of the configuration digest. Production static PVs use the same binding contract with production capacity and availability requirements; storage product selection remains an operator decision.

## Actual local ingress

```bash
python3 deploy/local/prepare-ingress.py \
  --namespace "$NOMOSMART_CONTROLLER_NAMESPACE" \
  --watch-namespace "$NOMOSMART_NAMESPACE" \
  --class-name "$NOMOSMART_CONTROLLER_NAMESPACE" \
  --output "$NOMOSMART_LOCAL/ingress.json"
kubectl --context docker-desktop apply --server-side \
  --field-manager=nomosmart-local -f "$NOMOSMART_LOCAL/ingress.json"
kubectl --context docker-desktop -n "$NOMOSMART_CONTROLLER_NAMESPACE" \
  rollout status "deployment/$NOMOSMART_CONTROLLER_NAMESPACE"
```

The pinned official Traefik controller handles the chart's NGINX-compatible annotations and watches only the dedicated application namespace/class. It installs no CRDs and grants no cluster-wide Secret access. See [Traefik provider documentation](https://doc.traefik.io/traefik/reference/install-configuration/providers/kubernetes/kubernetes-ingress-nginx/). The retired community ingress-nginx controller is not a new installation prerequisite.

Keep this command running in a separate terminal:

```bash
kubectl --context docker-desktop -n "$NOMOSMART_CONTROLLER_NAMESPACE" \
  port-forward "service/$NOMOSMART_CONTROLLER_NAMESPACE" \
  --address 127.0.0.1 18080:80 18443:443
```

For the existing `https://nomosmart.local` issuer, expose ports 80/443 on loopback. When macOS does not permit direct low-port forwarding, the following disposable official TCP forwarder uses the lock file's `debug_proxy` image. TLS still terminates at the actual controller:

```bash
export NOMOSMART_PROXY_IMAGE="$(python3 -c 'import json; print(json.load(open("deploy/release/external-dependencies.lock.json"))["images"]["debug_proxy"]["reference"])')"
docker run -d --name "$NOMOSMART_NAMESPACE-forward" \
  --label "nomosmart.io/local-owner=$NOMOSMART_NAMESPACE" \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  -p 127.0.0.1:80:8080 -p 127.0.0.1:443:8443 \
  --entrypoint /bin/sh "$NOMOSMART_PROXY_IMAGE" -ec \
  'socat TCP-LISTEN:8080,fork,reuseaddr TCP:host.docker.internal:18080 & exec socat TCP-LISTEN:8443,fork,reuseaddr TCP:host.docker.internal:18443'
```

## Install and check

```bash
kubectl --context docker-desktop apply --server-side \
  --field-manager=nomosmart-local -f "$NOMOSMART_LOCAL/inputs/secrets.json"
helm install "$NOMOSMART_RELEASE" deploy/helm/nomosmart \
  --kube-context docker-desktop --namespace "$NOMOSMART_NAMESPACE" \
  -f deploy/helm/nomosmart/values-docker-desktop.yaml \
  -f "$NOMOSMART_LOCAL/inputs/values.json" \
  --set installer.deploymentStage=foundation
kubectl --context docker-desktop -n "$NOMOSMART_NAMESPACE" get pods,pvc
```

Wait until **all** required dependency workloads are Ready and all seven PVCs are Bound. Resolve a Pending claim, wrong path ownership, tainted placement or TLS mismatch before starting application setup. Then:

```bash
helm upgrade "$NOMOSMART_RELEASE" deploy/helm/nomosmart \
  --kube-context docker-desktop --namespace "$NOMOSMART_NAMESPACE" \
  -f deploy/helm/nomosmart/values-docker-desktop.yaml \
  -f "$NOMOSMART_LOCAL/inputs/values.json" \
  --set installer.deploymentStage=application
kubectl --context docker-desktop -n "$NOMOSMART_NAMESPACE" get jobs,pods,pvc
curl --fail --silent --show-error \
  --cacert "$NOMOSMART_LOCAL/package/current/tls/active/edge-ca.crt" \
  https://nomosmart.local/
curl --fail --silent --show-error \
  --cacert "$NOMOSMART_LOCAL/package/current/tls/active/edge-ca.crt" \
  https://nomosmart.local/api/backend/ready
```

Migration and bootstrap must complete successfully, all four application workloads must be Ready, and readiness must return `ready`. A fresh database uses `B051`; a repeated migration is a no-op. Verify PV persistence by writing a disposable marker to a mounted data volume, recreating only its test Pod, reading the same marker and removing it. Do not delete a PVC to perform this check.

## Method 3: external services

Start with a new application namespace and new ingress identities after removing Method 2. The six dependency services must already exist and be reachable using real TLS endpoints. This validation prepared fresh, disposable dependencies in a separate namespace with static PVs, so it did not reuse another installation or OpenLDAP. Dependency preparation, credentials, backups and lifetime belong to their operator.

Use the same real ingress procedure. Prepare a private values file using `values-docker-desktop.yaml` first and `values-external-services.example.yaml` plus your overrides after it. Select `deploymentProfile: external-services`, all six component `mode: external`, `storageValidation.mode: external`, no PostgreSQL operator/backup and the correct Redis topology. An app-only external installation creates **zero PVCs**. The typed configuration uses `storage_mode = "external"` and `storage_class = ""`, with no static PV manifest.

Create the runtime Secret with matching service credentials, the migration account and strict TLS URLs. For standalone Redis use `rediss://` URLs with `ssl_cert_reqs=required`, `ssl_check_hostname=true` and the mounted CA path for all three Redis/Celery connections. PostgreSQL uses `sslmode=verify-full`; S3 and OpenSearch use HTTPS with verification enabled; Neo4j uses `neo4j+s://` with a CA. For private Keycloak HTTPS set `keycloak.external.caSecretName/caKey` to an operator CA **bundle** containing all required roots. The chart exports `SSL_CERT_FILE` and `NODE_EXTRA_CA_CERTS` and mounts the bundle for Backend and Frontend. Keep public-CA defaults when no private bundle is needed.

CA files are mounted read-only by `subPath`, preserving the regular-file requirement. **Recreate affected Pods after CA rotation**; `subPath` mounts do not auto-refresh. Use server-side apply for large CA bundles; client-side apply's annotation can exceed Kubernetes' size limit.

For operator-preconfigured Keycloak use `bootstrap.keycloakMode: verify` after the operator has prepared the real realm/clients. Run the migration/bootstrap application stage and wait for all four application workloads. Verify `/api/backend/ready`, frontend HTTPS, and discovery at the **configured external issuer** with its CA. The issuer may be private cluster DNS: check it from a real Backend Pod; do not assume the application ingress serves `/identity`. Installation validation does not perform a login.

## Remove each disposable round

Record the exact created names, UIDs, labels, image digests, PV/node paths and process IDs before removal. Stop only this round's native processes and port-forward terminal. Verify namespace/PV ownership before these commands:

```bash
helm uninstall "$NOMOSMART_RELEASE" --kube-context docker-desktop \
  --namespace "$NOMOSMART_NAMESPACE"
kubectl --context docker-desktop delete namespace \
  "$NOMOSMART_NAMESPACE" "$NOMOSMART_CONTROLLER_NAMESPACE"
kubectl --context docker-desktop delete -f "$NOMOSMART_LOCAL/pvs.json"
kubectl --context docker-desktop delete storageclass "$NOMOSMART_NAMESPACE"
kubectl --context docker-desktop delete ingressclass,clusterrole,clusterrolebinding \
  "$NOMOSMART_CONTROLLER_NAMESPACE"
docker rm -f "$NOMOSMART_NAMESPACE-forward"
```

For Method 3, delete only the dedicated app/controller objects; no app PV/class exists. Remove separately created test dependencies, their PVs/class and data only when this round owns them. `Retain` does not erase data: explicitly remove the seven dedicated node directories after Pods and PVCs are gone when permanent test-data deletion is intended. Preserve any shared external service. For Compose use the exact test project with `down --volumes --remove-orphans`. Remove only this run's application images/cache aliases and private generated credential files. Never use global Docker prune, broad namespace patterns, or remove shared StorageClasses/CRDs. Check absence and compare the protected inventory before starting the next method.
