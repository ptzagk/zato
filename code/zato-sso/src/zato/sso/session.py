# -*- coding: utf-8 -*-

"""
Copyright (C) 2018, Zato Source s.r.o. https://zato.io

Licensed under LGPLv3, see LICENSE.txt for terms and conditions.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

# stdlib
from contextlib import closing
from datetime import datetime, timedelta

# Zato
from zato.sso.api import const, status_code, ValidationError
from zato.sso.util import validate_password
from zato.sso.odb.query import get_user_by_username

# ################################################################################################################################

class LoginAPI(object):
    """ Logs a user in, provided that all authentication and authorization checks succeed.
    """
    def __init__(self, decrypt_func, verify_hash_func, odb_session_func):
        self.decrypt_func = decrypt_func
        self.verify_hash_func = self.verify_hash_func
        self.odb_session_func = odb_session_func

# ################################################################################################################################

    def _check_credentials(self, ctx, user):
        password_decrypted = self.decrypt_func(user.password)
        return self.verify_hash_func(ctx.input['password'], password_decrypted)

# ################################################################################################################################

    def _check_login_to_app_allowed(self, ctx):
        if ctx.input['current_app'] not in ctx.sso_conf.apps.login_allowed:
            if ctx.sso_conf.main.inform_if_app_invalid:
                self.response.payload.sub_status.append(status_code.app_list.invalid)
        else:
            return True

# ################################################################################################################################

    def _check_remote_ip_allowed(self, ctx, user, _invalid=object()):

        ip_allowed = ctx.sso_conf.login_list.get('my-admin', _invalid)

        # Shortcut in the simplest case
        if ip_allowed == '*':
            return True

        # Do not continue if user is not whitelisted but is required to
        if ip_allowed is _invalid:
            if ctx.sso_conf.login.reject_if_not_listed:
                return

        # User was found in configuration so now we need to check IPs allowed ..
        else:

            # .. but if there are no IPs configured for user, it means the person may not log in
            # regardless of reject_if_not_whitelisted, which is why it is checked separately.
            if not ip_allowed:
                return

            # There is at least one address or pattern to check again ..
            else:
                # .. but if no remote address was sent, we cannot continue.
                if not ctx.remote_addr:
                    return False
                else:
                    for _remote_addr in ctx.remote_addr:
                        for _ip_allowed in ip_allowed:
                            if _remote_addr in _ip_allowed:
                                return True # OK, there was at least that one match so we report success

                    # If we get here, it means that none of remote addresses from input matched
                    # so we can return False to be explicit.
                    return False

# ################################################################################################################################

    def _check_user_not_locked(self, ctx, user):
        if user.is_locked:
            if ctx.sso_conf.login.inform_if_locked:
                self.response.payload.sub_status.append(status_code.auth.locked)
        else:
            return True

# ################################################################################################################################

    def _check_signup_status(self, ctx, user):
        if user.sign_up_status != const.signup_status.final:
            if ctx.sso_conf.login.inform_if_not_confirmed:
                self.response.payload.sub_status.append(status_code.auth.invalid_signup_status)
        else:
            return True

# ################################################################################################################################

    def _check_is_approved(self, ctx, user):
        if not user.is_approved != const.signup_status.final:
            if ctx.sso_conf.login.inform_if_not_confirmed:
                self.response.payload.sub_status.append(status_code.auth.invalid_signup_status)
        else:
            return True

# ################################################################################################################################

    def _check_password_expired(self, ctx, user, _now=datetime.utcnow):
        if _now() > user.password_expiry:
            if ctx.sso_conf.password.inform_if_expired:
                self.response.payload.sub_status.append(status_code.password.expired)
        else:
            return True

# ################################################################################################################################

    def _check_password_about_to_expire(self, ctx, user, _now=datetime.utcnow, _timedelta=timedelta):

        # Find time after which the password is considered to be about to expire
        threshold_time = user.password_expiry - _timedelta(days=ctx.sso_conf.password.about_to_expire_threshold)

        # .. check if current time is already past that threshold ..
        if _now() > threshold_time:

            # .. if it is, we may either return a warning and continue ..
            if ctx.sso_conf.password.inform_if_about_to_expire:
                self.response.payload.status = status_code.warning
                self.response.payload.sub_status.append(status_code.password.w_about_to_exp)
                return status_code.warning

            # .. or it can considered an error, which rejects the request.
            else:
                self.response.payload.status = status_code.error
                self.response.payload.sub_status.append(status_code.password.e_about_to_exp)
                return status_code.error

        # No approaching expiry, we may continue
        else:
            return True

# ################################################################################################################################

    def _check_must_send_new_password(self, ctx, user):
        if user.password_must_change and not ctx.input.get('new_password'):
            if ctx.sso_conf.password.inform_if_must_be_changed:
                self.response.payload.sub_status.append(status_code.password.must_send_new)
        else:
            return True

# ################################################################################################################################

    def login(self, ctx, _ok=status_code.ok):

        # Look up user and return if not found by username
        with closing(self.odb_session_func()) as session:
            user = get_user_by_username(session, ctx.input['username'])
            if not user:
                return

        # Check credentials first to make sure that attackers do not learn about any sort
        # of metadata (e.g. is the account locked) if they do not know username and password.
        #if not self._check_credentials(ctx, user):
        #    return

        # It must be possible to log into the application requested (CRM above)
        if not self._check_login_to_app_allowed(ctx):
            return

        # If applicable, requests must originate in a white-listed IP address
        if not self._check_remote_ip_allowed(ctx, user):
            return

        # User must not have been locked out of the auth system
        if not self._check_user_not_locked(ctx, user):
            return

        # If applicable, user must be fully signed up, including account creation's confirmation
        if not self._check_signup_status(ctx, user):
            return

        # If applicable, user must be approved by a super-user
        if not self._check_is_approved(ctx, user):
            return

        # Password must not have expired
        if not self._check_password_expired(ctx, user):
            return

        # If applicable, password may not be about to expire (this must be after checking that it has not already).
        # Note that it may return a specific status to return (warning or error)
        _about_status = self._check_password_about_to_expire(ctx, user)
        if _about_status is not True:
            self.response.payload.status = _about_status
            return

        # If password is marked as as requiring a change upon next login but a new one was not sent, reject the request.
        if not self._check_must_send_new_password(ctx, user):
            return

        # If new password is required, we need to validate and save it before session can be created.
        # Note that at this point we already know that the old password was correct so it is safe to set the new one
        # if it is confirmed to be valid. Passwords are rarely changed to it is OK to open a new SQL session here
        # in addition to the one above instead of re-using it.
        try:
            validate_password(ctx.sso_conf, ctx.input['new_password'])
        except ValidationError as e:
            if e.return_status:
                self.response.payload.status = e.status
                self.response.payload.sub_status = e.sub_status
        else:
            # TODO: Create user here
            pass

        # All checks done, session is created, we can signal OK now
        self.response.payload.status = status_code.ok

# ################################################################################################################################
