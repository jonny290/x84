# -*- coding: utf-8 -*-
"""
New user account script for x/84, https://github.com/jquast/x84
"""
# std imports
from __future__ import division
import collections
import logging
import os
import re

# local
from x84.bbs import getsession, getterminal, echo, LineEditor
from x84.bbs import goto, get_ini, find_user, User, syncterm_setfont
from common import display_banner

log = logging.getLogger(__name__)
here = os.path.dirname(__file__)

#: banner art displayed in main()
art_file = os.path.join(here, 'art', 'nua*.ans')

#: preferred fontset for SyncTerm emulator
syncterm_font = 'topaz'

#: script executed after registration
top_script = get_ini(section='matrix',
                     key='topscript'
                     ) or 'top'

#: which login names trigger new user account script
new_usernames = get_ini(section='matrix',
                        key='newcmds',
                        split=True
                        ) or ['new']

#: maximum length of user handles
username_max_length = get_ini(section='nua',
                              key='max_user',
                              getter='getint'
                              ) or 10

#: minimum length of user handles
username_min_length = get_ini(section='nua',
                              key='min_user',
                              getter='getint',
                              ) or 2

#: which login names trigger new user account script
invalid_usernames = get_ini(section='nua',
                            key='invalid_handles',
                            split=True
                            ) or ['new', 'apply',
                                  'exit', 'logoff', 'bye', 'quit',
                                  'sysop', 'anonymous',]

#: login name validation as a regular expression
username_re_validator = get_ini(section='nua',
                                key='handle_validation',
                                ) or ['^[A-Za-z0-9]{3,11}$']


#: maximum length of user 'location' field
location_max_length = get_ini(section='nua',
                              key='max_location',
                              getter='getint'
                              ) or 25

#: maximum length of email address
email_max_length = get_ini(section='nua',
                           key='max_email',
                           getter='getint'
                           ) or 40

#: maximum length of password
password_max_length = get_ini(section='nua',
                              key='max_pass',
                              getter='getint'
                              ) or 15
password_min_length = get_ini(section='nua',
                              key='min_pass',
                              getter='getint'
                              ) or 4

#: primary color (highlight)
color_primary = 'black_on_magenta'

#: secondary color (lowlight)
color_secondary = 'red'

#: password hidden character
hidden_char = u'\u00f7'

#: structure for prompting input/validation
vfield = collections.namedtuple('input_validation', [
    # field name of user record
    'name',
    # field query displayed to user
    'prompt_key',
    # dictionary of arguments passed to LineEditor
    'kwargs',
    # validation function, None if no validation is required.
    # function receives (user, new_value) and returns tuple
    # of (errmsg, index modifier).
    'validation_function',
    # when resuming input, how to retrieve field value, may
    # return None (for example, the password field)
    'getter',
    # describe the necessity or optionality of the field and
    # its purpose to the user
    'description',
])


#: positions next prompt 40 pixels minus center of screen
def fixate_next(term, newlines):
    return u''.join((
        u'\r\n\r\n' * newlines,
        term.move_x(max(0, (term.width // 2) - 40))))


def prompt_input(term, key, **kwargs):
    """ Prompt for user input. """
    sep_ok = getattr(term, color_secondary)(u'::')
    colors = {'highlight': getattr(term, color_primary)}
    echo(u'{sep} {key:>18}: '.format(sep=sep_ok, key=key))
    entry = LineEditor(colors=colors, **kwargs).read()
    if entry is None:
        log.debug('New User Account canceled at prompt key={0}.'.format(key))
    return entry


def prompt_yesno(question):
    """ yes/no user prompt. """
    term = getterminal()
    sep = getattr(term, color_secondary)(u'**')
    colors = {'highlight': getattr(term, color_secondary)}
    echo(fixate_next(term, newlines=1))
    while True:
        echo(u'{sep} {question} [yn] ?\b\b'.format(sep=sep, question=question))
        yn = LineEditor(colors=colors, width=1).read() or u''
        if yn.lower() in (u'y', u'n'):
            return yn.lower() == u'y'
        echo(term.move_x(0) + term.clear_eol)
        echo(fixate_next(term, newlines=0))


def main(handle=u''):
    """
    Main procedure.
    """

    # set syncterm font, if any
    term = getterminal()
    if term._kind == 'ansi':
        echo(syncterm_setfont(syncterm_font))

    # reset handle to an empty string if it is any
    # of the 'new' user account alias strings
    if handle.lower() in new_usernames:
        handle = u''

    user = User(handle)

    # create new user record for manipulation
    while True:
        display_banner(art_file, encoding='ascii')
        user = do_nua(user)

        # user canceled.
        if user is None:
            return

        # confirm
        if prompt_yesno(question='Create account'):
            assert not find_user(user.handle), (
                # prevent race condition, scenario: `billy' begins new account
                # process, waits at 'Create account [yn] ?' prompt until a
                # second `billy' finishes account creation process, then the
                # first `billy' enters 'y', overwriting the existing account.
                'Security race condition: account already exists')
            user.save()
            goto(top_script, user.handle)


def show_validation_error(errmsg):
    """ Display validation error message. """
    term = getterminal()
    sep_bad = getattr(term, color_secondary)(u'**')
    echo(fixate_next(term, newlines=1))
    for txt in term.wrap(errmsg, width=max(0, min(80, term.width) - 3)):
        echo(fixate_next(term, newlines=0))
        echo(u'{sep} {txt}'.format(sep=sep_bad, txt=txt))
        echo(u'\r\n')


def do_nua(user):
    from common import show_description
    session, term = getsession(), getterminal()
    session.activity = u'Applying for an account'

    #: user record fields prompted by do_nua() loop
    validation_fields = (
        vfield(name='handle',
               prompt_key='Username',
               kwargs={'width': username_max_length},
               validation_function=validate_handle,
               getter=lambda: getattr(user, 'handle', None),
               description=u'Handle or Alias that you will be known '
               u'by on this board.'),
        vfield(name='location',
               prompt_key='Origin (optional)',
               kwargs={'width': location_max_length},
               validation_function=None,
               getter=lambda: getattr(user, 'location', None),
               description=u'Group of affiliation, geographic location, '
               u'or other moniker which other members will '
               u'know as your place or origin.'),
        vfield(name='email',
               prompt_key='E-mail (optional)',
               kwargs={'width': email_max_length},
               validation_function=None,
               getter=lambda: getattr(user, 'email', None),
               description=u'E-mail address is both private and optional, '
               u'allowing the ability to reset your password '
               u'should it ever be forgotten.'),
        vfield(name='password',
               prompt_key='Password',
               kwargs={'width': password_max_length,
                       'hidden': hidden_char},
               validation_function=validate_password,
               getter=lambda: None,
               description=None),
        vfield(name=None,
               prompt_key='Again',
               kwargs={'width': password_max_length,
                       'hidden': hidden_char},
               validation_function=validate_password_again,
               getter=lambda: None,
               description=None),
    )

    idx = 0
    while idx != len(validation_fields):
        field = validation_fields[idx]
        echo(fixate_next(term, newlines=1))
        if field.description:
            show_description(field.description, color=color_secondary)
            echo(fixate_next(term, newlines=1))
        value = prompt_input(term=term,
                             key=field.prompt_key,
                             content=field.getter(),
                             **field.kwargs)

        # user pressed escape, prompt for cancellation
        if value is None:
            if prompt_yesno('Cancel'):
                return None
            # re-prompt for current field
            continue

        value = value.strip()

        # validate using function, `field.validation_function()'
        if field.validation_function:
            errmsg, mod = field.validation_function(user, value)
            if errmsg:
                show_validation_error(errmsg)
                # re-prompt for current field
                idx += mod
                continue

        # set local variable, increment index to next field
        if field.name:
            setattr(user, field.name, value)
        idx += 1

    from x84.bbs.ini import CFG
    if CFG.has_section('ssh'):
        pubkey_val = get_publickey(term=term)
        if pubkey_val:
            user['pubkey'] = pubkey_val
    return user


def get_publickey(term):
    """ Prompt user for an ssh public key. """
    from x84.bbs.editor import ScrollingEditor
    from x84.bbs.userbase import parse_public_key
    from common import show_description

    # explain an ssh key for the newbies, and prompt wether they would
    # like to provide one or not.
    echo(fixate_next(term, newlines=1))
    show_description('An ssh public key allows you to login securely '
                     'and with convenience, bypassing the login matrix.  '
                     'Generate one using ssh-keygen(1), and provide '
                     'your public key.  This may be the contents of '
                     '~/.ssh/id_rsa.pub, for example.  Press escape to '
                     'cancel.', color=color_secondary)
    if not prompt_yesno(question='SSH Public key'):
        return None

    # when providing an ssh key, we use the ScrollingEditor class, but
    # it has the problem that its (y,x) position must be absolute: so
    # we first cause (maybe) scroll at bottom of screen to leave room
    # for the editor window,
    echo(term.move(term.height, 0))

    while True:
        # display our prompt prefix, input_prefix:
        echo(fixate_next(term, newlines=1))
        input_prefix = u'{sep} {key:>18}: '.format(
            sep=getattr(term, color_secondary)(u'::'),
            key='ssh public key')
        echo(input_prefix)

        # cause scroll to make prompt at position (term.height - 3).
        echo(fixate_next(term, newlines=1))

        # and prompt an editor on that row
        xloc = max(0, (term.width // 2) - 40) + term.length(input_prefix)
        editor = ScrollingEditor(xloc=xloc,
                                 yloc=term.height - 4,
                                 width=(term.width - xloc - 2),
                                 colors = {
                                     'highlight': getattr(term, color_primary)
                                 })

        value = editor.read()
        echo(term.normal)
        if value is None:
            return

        # validate key
        try:
            parse_public_key(value.strip())
        except Exception as err:
            show_validation_error('ValueError: {0}\r\n'.format(err))
            continue
        else:
            echo(fixate_next(term, newlines=1))
            echo(getattr(term, color_secondary)(u'**'))
            echo(u' ssh-key public key accepted.')
            return value.strip()


def validate_handle(user, handle):
    errmsg = None
    if find_user(handle):
        errmsg = u'User by this name already exists.'

    elif len(handle) < username_min_length:
        errmsg = (u'Username too short, must be at least {0} characters.'
                  .format(username_min_length))

    elif handle.lower() in invalid_usernames:
        errmsg = u'Username is not legal form: reserved.'

    elif os.path.sep in handle:
        errmsg = u'Username is not legal form: contains OS path separator.'

    elif not re.match(username_re_validator, handle):
        errmsg = (u'Username fails validation of regular expression, '
                  u'{0!r}.'.format(username_re_validator))

    # No validation error
    return errmsg, 0


def validate_password(user, password):
    errmsg = None
    if password == u'':
        errmsg = u'Password is required.'
    elif len(password) < password_min_length:
        errmsg = (u'Password too short, must be at least {0} characters.'
                  .format(password_min_length))

    # No validation error
    return errmsg, 0


def validate_password_again(user, password):
    errmsg = None
    if not user.auth(password):
        errmsg = u'Password does not match, try again!'

    # returns -1 as modifier, to return to password prompt.
    return errmsg, -1
