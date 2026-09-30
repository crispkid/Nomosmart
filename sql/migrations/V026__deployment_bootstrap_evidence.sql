CREATE TABLE deployment_bootstrap_evidence (
    release_id varchar(255) PRIMARY KEY,
    contract_version integer NOT NULL CHECK (contract_version > 0),
    check_names jsonb NOT NULL CHECK (jsonb_typeof(check_names) = 'array'),
    completed_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE deployment_bootstrap_evidence IS
    'Secret-free evidence that a deployment release completed the non-HTTP bootstrap contract.';
