"""Actual capability rules using an isolated copy of a genuine configured model."""
from copy import deepcopy
import json
import pytest
from app.core.errors import AppError
from app.domain.ocr_capabilities import normalize_native_capabilities
from scripts.chg413_runtime import Scope

@pytest.fixture(scope='module')
def genuine_native_configuration():
 s=Scope();db='nms413_00621cbd_current';owner=s.owner(db)
 assert owner['comment']=='CHG-413 '+s.op
 value=json.loads(s.sql("SELECT config FROM ai_models WHERE id='6585498e-63e5-4698-ac59-c3fea9e69d7e' AND model_type='OCR' AND is_active;",database=db))
 assert normalize_native_capabilities(value)['supports_pdf'] is True
 return value

@pytest.mark.parametrize(('field','invalid'),[
 ('max_input_bytes',True),('max_input_bytes','1024'),('max_input_bytes',1.5),
 ('max_input_bytes',0),('max_input_bytes',-1),('max_input_bytes',2**63),
 ('protocol','page_images'),('supports_pdf',False),('count_input_tokens',False),
 ('mime_types',[]),('mime_types',[123,'application/pdf']),('supports_temperature','false'),
])
def test_native_capability_rejects_wrong_type_or_capacity(genuine_native_configuration,field,invalid):
 config=deepcopy(genuine_native_configuration);config['native_pdf'][field]=invalid
 with pytest.raises(AppError) as error:normalize_native_capabilities(config)
 assert error.value.code=='ocr_native_capability_invalid'

@pytest.mark.parametrize('change',['missing_profile','missing_limit','min_above_max','max_equals_context'])
def test_native_capability_rejects_missing_or_conflicting_limits(genuine_native_configuration,change):
 config=deepcopy(genuine_native_configuration);p=config['native_pdf']
 if change=='missing_profile':del config['native_pdf']
 elif change=='missing_limit':del p['max_request_bytes']
 elif change=='min_above_max':p['min_output_tokens']=p['max_output_tokens']+1
 else:p['max_output_tokens']=p['context_window']
 with pytest.raises(AppError) as error:normalize_native_capabilities(config)
 assert error.value.code in {'ocr_native_capability_required','ocr_native_capability_invalid'}
