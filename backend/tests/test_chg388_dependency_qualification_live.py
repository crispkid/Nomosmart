"""Real fixed decoder and one read-only TLS bind; no clock/LDAP adapters."""
from importlib.metadata import version
import pytest
from pyasn1.codec.ber import decoder as ber
from pyasn1.codec.cer import decoder as cer
from pyasn1.codec.der import decoder as der
from pyasn1.type import univ
from pyasn1.error import PyAsn1Error


def _length(size):
    if size < 128:
        return bytes([size])
    encoded=size.to_bytes((size.bit_length()+7)//8,"big")
    return bytes([0x80|len(encoded)])+encoded


@pytest.mark.parametrize("kind", ["ber", "cer", "der-schema", "der-primitive"])
def test_real_fixed_decoder_preserves_bitstring_bytes(kind):
    assert version("pyasn1")=="0.6.5"
    if kind=="cer":
        octets=b"\xa5"*999
        fragment=b"\x03"+_length(len(octets)+1)+b"\x00"+octets
        payload=b"\x23\x80"+fragment*32+b"\x00\x00"
        expected=octets*32
        value,remainder=cer.decode(payload)
    elif kind=="der-primitive":
        expected=b"\xa5"
        value,remainder=der.decode(b"\x03\x02\x00\xa5")
        with pytest.raises(PyAsn1Error):
            der.decode(b"\x23\x04\x03\x02\x00\xa5")
    else:
        count=4096 if kind=="ber" else 128
        body=b"\x03\x02\x00\xa5"*count
        payload=b"\x23"+_length(len(body))+body
        expected=b"\xa5"*count
        value,remainder=(ber.decode(payload) if kind=="ber"
                         else der.decode(payload,asn1Spec=univ.BitString()))
    assert not remainder and len(value)==len(expected)*8
    assert value.asOctets()==expected


def test_fixed_pyasn1_with_real_readonly_ldaps_bind_and_base_read():
    assert version("pyasn1")=="0.6.5" and version("ldap3")=="2.9.1"
    from current_live_support import load_current_context,_read_current_service_secret
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.security.auth_configuration import configuration,current_setting
    from app.integrations.ldap_directory import LdapDirectory
    from ldap3 import BASE
    import os
    load_current_context()
    with get_session_factory()() as database:
        config=configuration(current_setting(database)).directory
    password=_read_current_service_secret(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"],"directory-bind.txt")
    client=LdapDirectory(get_settings(),config,password)
    try:
        with client.connection() as connection:
            assert connection.bound and connection.read_only
            assert connection.server.ssl or connection.tls_started
            assert connection.search(config.users_dn,"(objectClass=*)",search_scope=BASE,attributes=["objectClass"])
            assert connection.result["result"]==0 and len(connection.entries)==1
    finally:
        password=""
