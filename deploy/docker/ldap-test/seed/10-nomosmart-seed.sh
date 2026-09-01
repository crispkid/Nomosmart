#!/command/with-contenv bash
set -Eeuo pipefail

base_dn="dc=nomosmart,dc=test"
admin_dn="cn=admin,${base_dn}"
bind_dn="cn=nomosmart-bind,${base_dn}"
admin_secret_file="/run/secrets/ldap_admin_password"
config_secret_file="/run/secrets/ldap_config_password"
bind_secret_file="/run/secrets/ldap_bind_password"
ca_file="/run/secrets/ca.crt"
ldap_url="ldaps://nomosmart-openldap:636"

for secret_file in "${admin_secret_file}" "${config_secret_file}" \
    "${bind_secret_file}" "${ca_file}"; do
    if [[ ! -s "${secret_file}" ]]; then
        echo "Required LDAP secret file is missing" >&2
        exit 1
    fi
done

seed_file="$(mktemp)"
acl_file="$(mktemp)"
trap 'rm -f "${seed_file}" "${acl_file}"' EXIT

admin_hash="$(slappasswd -T "${admin_secret_file}")"
bind_hash="$(slappasswd -T "${bind_secret_file}")"
user_hash="$(slappasswd -s 'P@ssw0rd')"

cat >"${seed_file}" <<EOF
dn: ${base_dn}
objectClass: top
objectClass: dcObject
objectClass: organization
dc: nomosmart
o: NomoSmart Local Test
description: Synthetic local-development directory only

dn: ${admin_dn}
objectClass: simpleSecurityObject
objectClass: organizationalRole
cn: admin
description: Local synthetic directory administrator
userPassword: ${admin_hash}

dn: ${bind_dn}
objectClass: simpleSecurityObject
objectClass: organizationalRole
cn: nomosmart-bind
description: NomoSmart read-only directory bind account
userPassword: ${bind_hash}

dn: ou=users,${base_dn}
objectClass: organizationalUnit
ou: users
description: Synthetic NomoSmart test users

dn: ou=groups,${base_dn}
objectClass: organizationalUnit
ou: groups
description: Synthetic NomoSmart test groups

dn: uid=ldap.alice,ou=users,${base_dn}
objectClass: inetOrgPerson
uid: ldap.alice
cn: Alice LDAP Tester
sn: Tester
givenName: Alice
displayName: Alice LDAP Tester
mail: ldap.alice@nomosmart.test
employeeNumber: Z000000001
departmentNumber: Quality Assurance
title: Directory Test Analyst
manager: uid=ldap.bob,ou=users,${base_dn}
userPassword: ${user_hash}

dn: uid=ldap.bob,ou=users,${base_dn}
objectClass: inetOrgPerson
uid: ldap.bob
cn: Bob LDAP Manager
sn: Manager
givenName: Bob
displayName: Bob LDAP Manager
mail: ldap.bob@nomosmart.test
employeeNumber: Z000000002
departmentNumber: Quality Assurance
title: Directory Test Manager
userPassword: ${user_hash}

dn: cn=nomosmart-testers,ou=groups,${base_dn}
objectClass: groupOfNames
cn: nomosmart-testers
description: Synthetic users for NomoSmart directory tests
member: uid=ldap.alice,ou=users,${base_dn}
member: uid=ldap.bob,ou=users,${base_dn}

dn: cn=nomosmart-reviewers,ou=groups,${base_dn}
objectClass: groupOfNames
cn: nomosmart-reviewers
description: Synthetic review group without application role mapping
member: uid=ldap.alice,ou=users,${base_dn}
EOF

export LDAPTLS_CACERT="${ca_file}"
export LDAPTLS_REQCERT=demand

if ! ldapsearch -x -LLL -H "${ldap_url}" -D "${admin_dn}" \
    -y "${admin_secret_file}" -b "${base_dn}" -s base dn >/dev/null 2>&1; then
    ldapadd -x -H "${ldap_url}" -D "${admin_dn}" -y "${admin_secret_file}" \
        -f "${seed_file}"
fi

cat >"${acl_file}" <<EOF
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcAccess
olcAccess: {0}to attrs=userPassword,shadowLastChange by self =xw by dn.exact="${admin_dn}" manage by anonymous auth by * none
olcAccess: {1}to dn.subtree="${base_dn}" by dn.exact="${admin_dn}" manage by dn.exact="${bind_dn}" read by self read by users read by * none
EOF

ldapmodify -x -H "${ldap_url}" -D cn=config -y "${config_secret_file}" \
    -f "${acl_file}"

ldapsearch -x -LLL -H "${ldap_url}" -D "${bind_dn}" \
    -y "${bind_secret_file}" -b "${base_dn}" -s base dn >/dev/null

if ldapsearch -x -LLL -H "${ldap_url}" -b "${base_dn}" -s base dn \
    >/dev/null 2>&1; then
    echo "Anonymous LDAP search unexpectedly succeeded" >&2
    exit 1
fi

echo "NomoSmart synthetic LDAP directory initialized"
