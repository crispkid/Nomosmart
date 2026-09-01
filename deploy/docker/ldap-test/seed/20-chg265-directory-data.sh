#!/command/with-contenv bash
set -Eeuo pipefail

base_dn="dc=nomosmart,dc=test"
users_dn="ou=users,${base_dn}"
groups_dn="ou=groups,${base_dn}"
admin_dn="cn=admin,${base_dn}"
bind_dn="cn=nomosmart-bind,${base_dn}"
admin_secret_file="/run/secrets/ldap_admin_password"
bind_secret_file="/run/secrets/ldap_bind_password"
ca_file="/run/secrets/ca.crt"
ldap_url="ldaps://nomosmart-openldap:636"

for secret_file in "${admin_secret_file}" "${bind_secret_file}" "${ca_file}"; do
    if [[ ! -s "${secret_file}" ]]; then
        echo "Required LDAP secret file is missing" >&2
        exit 1
    fi
done

entry_file="$(mktemp)"
user_password_file="$(mktemp)"
trap 'rm -f "${entry_file}" "${user_password_file}"' EXIT
printf '%s' 'P@ssw0rd' >"${user_password_file}"
chmod 0600 "${user_password_file}"
user_hash="$(slappasswd -T "${user_password_file}")"

export LDAPTLS_CACERT="${ca_file}"
export LDAPTLS_REQCERT=demand

admin_search() {
    local dn="$1"
    shift
    ldapsearch -x -LLL -o ldif-wrap=no -H "${ldap_url}" \
        -D "${admin_dn}" -y "${admin_secret_file}" -b "${dn}" -s base "$@"
}

entry_exists() {
    admin_search "$1" dn >/dev/null 2>&1
}

attribute_values() {
    local dn="$1"
    local attribute="$2"
    admin_search "${dn}" "${attribute}" 2>/dev/null \
        | sed -n "s/^${attribute}: //p"
}

require_single_value() {
    local dn="$1"
    local attribute="$2"
    local expected="$3"
    local actual
    actual="$(attribute_values "${dn}" "${attribute}")"
    if [[ "${actual}" != "${expected}" ]]; then
        echo "Conflicting LDAP entry attribute: ${dn} ${attribute}" >&2
        exit 1
    fi
}

require_absent_value() {
    local dn="$1"
    local attribute="$2"
    if [[ -n "$(attribute_values "${dn}" "${attribute}")" ]]; then
        echo "Unexpected LDAP entry attribute: ${dn} ${attribute}" >&2
        exit 1
    fi
}

require_object_class() {
    local dn="$1"
    local expected="$2"
    if ! attribute_values "${dn}" objectClass | grep -Fxiq "${expected}"; then
        echo "Conflicting LDAP objectClass: ${dn}" >&2
        exit 1
    fi
}

verify_user() {
    local uid="$1"
    local surname="$2"
    local given_name="$3"
    local common_name="$4"
    local employee_number="$5"
    local department="$6"
    local manager_dn="$7"
    local dn="uid=${uid},${users_dn}"

    require_object_class "${dn}" inetOrgPerson
    require_single_value "${dn}" uid "${uid}"
    require_single_value "${dn}" sn "${surname}"
    require_single_value "${dn}" givenName "${given_name}"
    require_single_value "${dn}" cn "${common_name}"
    require_single_value "${dn}" displayName "${common_name}"
    require_single_value "${dn}" mail "${uid}@nomosmart.test"
    require_single_value "${dn}" employeeNumber "${employee_number}"
    require_single_value "${dn}" departmentNumber "${department}"
    if [[ -n "${manager_dn}" ]]; then
        require_single_value "${dn}" manager "${manager_dn}"
    else
        require_absent_value "${dn}" manager
    fi
    ldapwhoami -x -H "${ldap_url}" -D "${dn}" -y "${user_password_file}" \
        >/dev/null
}

preflight_user() {
    local uid="$1"
    local dn="uid=${uid},${users_dn}"
    shift
    if entry_exists "${dn}"; then
        verify_user "${uid}" "$@"
    fi
}

ensure_user() {
    local uid="$1"
    local surname="$2"
    local given_name="$3"
    local common_name="$4"
    local employee_number="$5"
    local department="$6"
    local manager_dn="$7"
    local dn="uid=${uid},${users_dn}"

    if ! entry_exists "${dn}"; then
        cat >"${entry_file}" <<EOF
dn: ${dn}
objectClass: inetOrgPerson
uid: ${uid}
cn: ${common_name}
sn: ${surname}
givenName: ${given_name}
displayName: ${common_name}
mail: ${uid}@nomosmart.test
employeeNumber: ${employee_number}
departmentNumber: ${department}
EOF
        if [[ -n "${manager_dn}" ]]; then
            printf 'manager: %s\n' "${manager_dn}" >>"${entry_file}"
        fi
        printf 'userPassword: %s\n' "${user_hash}" >>"${entry_file}"
        ldapadd -x -H "${ldap_url}" -D "${admin_dn}" \
            -y "${admin_secret_file}" -f "${entry_file}" >/dev/null
        echo "Created synthetic LDAP user: ${uid}"
    fi
    verify_user "${uid}" "${surname}" "${given_name}" "${common_name}" \
        "${employee_number}" "${department}" "${manager_dn}"
}

verify_group() {
    local group_name="$1"
    shift
    local dn="cn=${group_name},${groups_dn}"
    local actual_members
    local expected_members

    require_object_class "${dn}" groupOfNames
    require_single_value "${dn}" cn "${group_name}"
    actual_members="$(attribute_values "${dn}" member | LC_ALL=C sort)"
    expected_members="$(printf '%s\n' "$@" | LC_ALL=C sort)"
    if [[ "${actual_members}" != "${expected_members}" ]]; then
        echo "Conflicting LDAP group membership: ${dn}" >&2
        exit 1
    fi
}

preflight_group() {
    local group_name="$1"
    local dn="cn=${group_name},${groups_dn}"
    shift
    if entry_exists "${dn}"; then
        verify_group "${group_name}" "$@"
    fi
}

ensure_group() {
    local group_name="$1"
    local description="$2"
    shift 2
    local dn="cn=${group_name},${groups_dn}"

    if ! entry_exists "${dn}"; then
        cat >"${entry_file}" <<EOF
dn: ${dn}
objectClass: groupOfNames
cn: ${group_name}
description: ${description}
EOF
        local member_dn
        for member_dn in "$@"; do
            printf 'member: %s\n' "${member_dn}" >>"${entry_file}"
        done
        ldapadd -x -H "${ldap_url}" -D "${admin_dn}" \
            -y "${admin_secret_file}" -f "${entry_file}" >/dev/null
        echo "Created synthetic LDAP group: ${group_name}"
    fi
    verify_group "${group_name}" "$@"
}

user01_dn="uid=user01,${users_dn}"
user02_dn="uid=user02,${users_dn}"
user03_dn="uid=user03,${users_dn}"
user04_dn="uid=user04,${users_dn}"
user05_dn="uid=user05,${users_dn}"

# Complete the conflict preflight for all nine DNs before the first write.
preflight_user user01 Chu Peter "Peter Chu" Z000000101 HR ""
preflight_user user02 Wu Justin "Justin Wu" Z000000102 HR "${user01_dn}"
preflight_user user03 Lee Jerry "Jerry Lee" Z000000103 IT ""
preflight_user user04 Lu Paggy "Paggy Lu" Z000000104 FIN ""
preflight_user user05 Liu Jam "Jam Liu" Z000000105 IT "${user03_dn}"
preflight_group HR "${user01_dn}" "${user02_dn}"
preflight_group IT "${user03_dn}" "${user05_dn}"
preflight_group FIN "${user04_dn}"
preflight_group nomosmart-admin "${user01_dn}"

ensure_user user01 Chu Peter "Peter Chu" Z000000101 HR ""
ensure_user user02 Wu Justin "Justin Wu" Z000000102 HR "${user01_dn}"
ensure_user user03 Lee Jerry "Jerry Lee" Z000000103 IT ""
ensure_user user04 Lu Paggy "Paggy Lu" Z000000104 FIN ""
ensure_user user05 Liu Jam "Jam Liu" Z000000105 IT "${user03_dn}"

ensure_group HR "Synthetic NomoSmart HR test group" \
    "${user01_dn}" "${user02_dn}"
ensure_group IT "Synthetic NomoSmart IT test group" \
    "${user03_dn}" "${user05_dn}"
ensure_group FIN "Synthetic NomoSmart FIN test group" \
    "${user04_dn}"
ensure_group nomosmart-admin \
    "Synthetic directory group without application role mapping" \
    "${user01_dn}"

ldapsearch -x -LLL -H "${ldap_url}" -D "${bind_dn}" \
    -y "${bind_secret_file}" -b "${base_dn}" \
    '(|(uid=user01)(uid=user02)(uid=user03)(uid=user04)(uid=user05)(cn=HR)(cn=IT)(cn=FIN)(cn=nomosmart-admin))' \
    dn >/dev/null

echo "CHG-265 synthetic LDAP users and groups verified"
