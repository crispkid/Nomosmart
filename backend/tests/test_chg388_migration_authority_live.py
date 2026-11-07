"""Real authority inputs; malformed requests cannot grant current DB scope."""
import os
from pathlib import Path
import pytest
from current_migration_support import load_context
from current_migration_authority import verify_context

@pytest.mark.parametrize('invalid',['operation','purpose','database'])
def test_current_migration_authority_rejects_unapproved_input(invalid):
    current=dict(load_context());current['databases']=dict(current['databases'])
    if invalid=='operation':current['operation_uuid']='00000000-0000-4000-8000-000000000001'
    elif invalid=='purpose':current['purpose']='unapproved'
    else:current['databases']['ready']='nomosmart'
    path=Path(os.environ['NOMOSMART_CURRENT_MIGRATION_CONTEXT'])
    with pytest.raises(AssertionError):verify_context(current,path,Path(__file__).resolve().parents[2])
