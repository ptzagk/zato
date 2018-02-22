# -*- coding: utf-8 -*-

"""
Copyright (C) 2018, Zato Source s.r.o. https://zato.io

Licensed under LGPLv3, see LICENSE.txt for terms and conditions.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

# stdlib
from uuid import uuid4

# Base32 Crockford
from base32_crockford import encode as crockford_encode

# ipaddress
from ipaddress import ip_network

# Zato
from zato.sso import status_code, ValidationError

# ################################################################################################################################

def _new_id(prefix, _uuid4=uuid4, _crockford_encode=crockford_encode):
    return '%s%s' % (prefix, _crockford_encode(_uuid4().int).lower())

# ################################################################################################################################

def new_confirm_token(_new_id=_new_id):
    return _new_id('zcnt')

# ################################################################################################################################

def new_user_id(_new_id=_new_id):
    return _new_id('zusr')

# ################################################################################################################################

def validate_password(sso_conf, password):
    """ Raises ValidationError if password is invalid, e.g. it is too simple.
    """
    # Password may not be too short
    if len(password) < sso_conf.password.min_length:
        raise ValidationError(status_code.password.too_short, sso_conf.password.inform_if_invalid)

    # Password may not be too long
    if len(password) > sso_conf.password.max_length:
        raise ValidationError(status_code.password.too_long, sso_conf.password.inform_if_invalid)

    # Password's default complexity is checked case-insensitively
    password = password.lower()

    # Password may not contain most commonly used ones
    for elem in sso_conf.password.reject_list:
        if elem in password:
            raise ValidationError(status_code.password.invalid, sso_conf.password.inform_if_invalid)

# ################################################################################################################################

def make_data_secret(data, encrypt_func=None, hash_func=None):
    """ Turns data into a secret by hashing it (stretching) and then encrypting the result.
    """
    # E.g. PBKDF2-SHA512
    if hash_func:
        data = hash_func(data)

    # E.g. Fernet (AES-128)
    if encrypt_func:
        data = encrypt_func(data)

    return data

# ################################################################################################################################

def make_password_secret(password, encrypt_password, encrypt_func=None, hash_func=None):
    """ Encrypts and hashes a user password.
    """
    return make_data_secret(password, encrypt_func if encrypt_password else None, hash_func)

# ################################################################################################################################

def normalize_password_reject_list(sso_conf):
    """ Turns a multi-line string with passwords to be rejected into a set.
    """
    reject = set()
    for line in sso_conf.password.get('reject_list', '').strip().splitlines():
        line = str(line.strip().lower())
        reject.add(line)
    sso_conf.password.reject_list = reject

# ################################################################################################################################

def normalize_sso_config(sso_conf):

    # Lower-case elements that must not be substrings in usernames ..
    reject_username = sso_conf.user_validation.get('reject_username', [])
    reject_username = [elem.strip().lower() for elem in reject_username]
    sso_conf.user_validation.reject_username = reject_username

    # .. and emails too.
    reject_email = sso_conf.user_validation.get('reject_email', [])
    reject_email = [elem.strip().lower() for elem in reject_email]
    sso_conf.user_validation.reject_email = reject_email

    # Construct a set of common passwords to reject out of a multi-line list
    normalize_password_reject_list(sso_conf)

    # Turn all app lists into sets to make lookups faster

    apps_all = sso_conf.apps.all
    apps_signup_allowed = sso_conf.apps.signup_allowed
    apps_login_allowed = sso_conf.apps.login_allowed

    apps_all = apps_all if isinstance(apps_all, list) else [apps_all]
    apps_signup_allowed = apps_signup_allowed if isinstance(apps_signup_allowed, list) else [apps_signup_allowed]
    apps_login_allowed = apps_login_allowed if isinstance(apps_login_allowed, list) else [apps_login_allowed]

    sso_conf.apps.all = set(apps_all)
    sso_conf.apps.signup_allowed = set(apps_signup_allowed)
    sso_conf.apps.login_allowed = set(apps_login_allowed)

    # There may be a single service in a relevant part of configuration
    # so for ease of use we always turn tjem into lists.
    signup_cb_srv = sso_conf.signup.callback_service
    signup_cb_srv = signup_cb_srv if isinstance(signup_cb_srv, list) else [signup_cb_srv]

    usr_valid_srv = sso_conf.user_validation.service
    usr_valid_srv = usr_valid_srv if isinstance(usr_valid_srv, list) else [usr_valid_srv]

    sso_conf.signup.callback_service = signup_cb_srv
    sso_conf.user_validation.service = usr_valid_srv

    # Convert all white/black-listed IP addresses to sets of network objects
    # which will let serviced in run-time efficiently check for membership of an address in that network.

    login_list = sso_conf.login_list
    for username, ip_allowed in login_list.iteritems():
        if ip_allowed:
            ip_allowed = login_list if isinstance(ip_allowed, list) else [ip_allowed]
            ip_allowed = [ip_network(elem.decode('utf8')) for elem in ip_allowed if elem != '*']
        else:
            ip_allowed = []
        login_list[username] = ip_allowed

# ################################################################################################################################
