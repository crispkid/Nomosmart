"""Exact approved current counterparts. Unimplemented predicates fail collection/execution.

Only actual files/archives/policy functions are used. Historical outcomes are never
relabelled; each selector retains its original source and assertion identities.
"""
from datetime import UTC,datetime
from hashlib import sha256
import importlib,json,os
from pathlib import Path
import pytest
from scripts.public_source_inventory import PublicSourceInventory

ROOT=Path(__file__).resolve().parents[2]
PROPOSAL_SHA='f5a9a6d888a6cc1e795b831578b82000cfa669586bf779ead2317f58bcc221d3'
PLAN_SHA='80478eeb9dccfa23b97b00a42d2abbe3163e3d45415825d37ab99d893dd94325'
OPERATION='24c50237-b9ef-4dc7-b732-13e60933c5cf'
raw=(ROOT/'docs/CHG-388-CASE-PROPOSAL.json').read_bytes()
assert sha256(raw).hexdigest()==PROPOSAL_SHA
CASES={r['proposal_id'].removeprefix('C388-'):r for r in json.loads(raw)['cases']if'test_chg388_current_delivery_evidence_live.py'in(r.get('planned_target')or'')}
assert len(CASES)==122



def _current400_context(path, owner):
    assert owner['change_id']=='CHG-400'and owner['kind']=='CHG400_REAL_FILE_ONLY_DELIVERY'
    assert owner['operation_uuid']==OPERATION and owner['closed']is False
    private=Path('/private/tmp/nomosmart-chg388-24c50237/triad399/closure400')
    assert path.parent==Path(owner['root'])and path.parent.is_relative_to(private)
    assert owner['source_root']==str(ROOT)
    created,deadline=[datetime.fromisoformat(owner[k])for k in ['created_at','deadline']]
    assert (deadline-created).total_seconds()==7200 and created<=datetime.now(UTC)<deadline
    approval=json.loads((ROOT/'docs/CHG-400-APPROVAL.json').read_bytes())
    assert approval['gate_4']=='APPROVED'and approval['approved_by']=='Peter'and approval['operation_uuid']==OPERATION
    assert owner['plan_sha256']==approval['approved_plan_sha256']==sha256((ROOT/'docs/CHG-400-INTEGRATED-CLOSURE-PLAN.md').read_bytes()).hexdigest()
    for name,digest in approval['approved_proposals'].items():
        assert sha256((ROOT/'docs'/name).read_bytes()).hexdigest()==digest
    assert owner['case_proposal_sha256']==PROPOSAL_SHA
    inventory=PublicSourceInventory.load(ROOT,path.parent/'source-inventory.json',expected_sha256=owner['source_inventory_sha256'])
    return owner,inventory


def _context():
    path=Path(os.environ['NOMOSMART_CURRENT_DELIVERY_SCOPE']);assert path.is_absolute()and not path.is_symlink()and path.resolve()==path and path.stat().st_uid==os.getuid()and path.stat().st_mode&0o077==0;owner=json.loads(path.read_bytes());
    if owner.get('kind')=='CHG400_REAL_FILE_ONLY_DELIVERY':return _current400_context(path,owner)
    assert owner['kind']=='CHG388_REAL_FILE_ONLY_DELIVERY'and owner['operation_uuid']==OPERATION and owner['closed']is False;assert datetime.now(UTC)<datetime.fromisoformat(owner['deadline'])and Path(owner['source_root'])==ROOT and path.parent==Path(owner['root']);assert owner['plan_sha256']==PLAN_SHA and owner['case_proposal_sha256']==PROPOSAL_SHA;assert sha256((ROOT/'docs/CHG-388-INTEGRATED-PLAN.md').read_bytes()).hexdigest()==PLAN_SHA;approval=json.loads((ROOT/'docs/CHG-388-APPROVAL.json').read_bytes());assert approval['plan_sha256']==PLAN_SHA and approval['gate_4']=='APPROVED';inventory=PublicSourceInventory.load(ROOT,path.parent/'source-inventory.json',expected_sha256=owner['source_inventory_sha256']);return owner,inventory


@pytest.mark.parametrize('obligation',sorted(CASES))
def test_current_delivery_obligation(obligation,tmp_path):
    owner,inventory=_context();case=CASES[obligation];assert sha256((ROOT/case['case'].split('::')[0]).read_bytes()).hexdigest()==case['source_module_sha256'];relative='backend/tests/current_delivery_predicates/case_'+obligation+'.py'
    # A missing implementation is an actual failure, never a skip or a waived case.
    data,_=inventory.read(relative);predicate=importlib.import_module('current_delivery_predicates.case_'+obligation);assert Path(predicate.__file__).resolve()==ROOT/relative
    result=predicate.verify({'root':ROOT,'private_root':Path(owner['root']),'inventory':inventory,'materials':owner.get('materials',{})},tmp_path)
    evidence={'operation_uuid':OPERATION,'at':datetime.now(UTC).isoformat(),'proposal_id':'C388-'+obligation,'original_case':case['case'],'original_case_body_sha256':case['case_body_sha256'],'original_module_sha256':case['source_module_sha256'],'current_predicate_source_sha256':sha256(data).hexdigest(),'current_dispatcher_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'source_inventory_sha256':owner['source_inventory_sha256'],'result':result,'actual_current_predicate_completed':True,'original_historical_method_counted_as_PASS':False,'full_suite_or_release_PASS':False};out=Path(owner['root'])/'receipts'/('C388-'+obligation+'.json');assert not out.exists();out.write_text(json.dumps(evidence,indent=2,default=str));out.chmod(0o600)
