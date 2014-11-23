""" Last Callers script for x/84, http://github.com/jquast/x84 """
# std
import collections
import datetime
import time
import os

# local
from x84.bbs import getsession, getterminal, get_ini, echo
from x84.bbs import DBProxy, timeago, syncterm_setfont
from common import prompt_pager, display_banner

#: filepath to folder containing this script
here = os.path.dirname(__file__)

#: filepath to artfile displayed for this script
art_file = os.path.join(here, 'art', 'callers*.ans')

#: encoding used to display artfile
art_encoding = 'cp437_art'

#: fontset for SyncTerm emulator
syncterm_font = 'topaz'

#: maximum length of user handles
username_max_length = get_ini(section='nua',
                              key='max_user',
                              getter='getint'
                              ) or 10

#: maximum length of user handles
location_max_length = get_ini(section='nua',
                              key='max_location',
                              getter='getint'
                              ) or 15

#: maximum length of column for number of calls
numcalls_max_length = len('# calls')

#: last caller record structure
call_record = collections.namedtuple(
    'lc', ['timeago', 'num_calls', 'location', 'handle'])


def get_lastcallers(last):
    last_callers = list()
    for handle, (last_called, num_calls, location) in (
            DBProxy('lastcalls').items()):
        try:
            timeago = (datetime.datetime.now() - last_called).total_seconds()
        except TypeError:
            # XXX handle Legacy format: simple Epoch as float
            timeago = time.time() - last_called
        last_callers.append(call_record(timeago=timeago,
                                        num_calls=num_calls,
                                        location=location,
                                        handle=handle.decode('utf8')))
    last_callers.sort()
    return last_callers[:last]


def main(last=10):
    """
    Script entry point.

    :param last: Number of last callers to display
    :type last: int
    """
    session, term = getsession(), getterminal()
    session.activity = u'Viewing last callers'

    colors = [term.green, term.bright_blue, term.bold,
              term.cyan, term.bold_black]

    # set syncterm font, if any
    if syncterm_font and term._kind.startswith('ansi'):
        echo(syncterm_setfont(syncterm_font))

    # display banner
    line_no = display_banner(filepattern=art_file, encoding=art_encoding)

    # get last callers
    last_callers = get_lastcallers(last=last)
    echo(u'\r\n\r\n')

    # format callers, header:
    callers_txt = [
        '{handle} {location} {num_calls} {timeago}'
        .format(
            handle=term.bold_underline(
                term.ljust('handle', username_max_length + 1)),
            location=term.underline(
                term.ljust('location', location_max_length)),
            num_calls=term.bold_underline(
                term.ljust('# calls', numcalls_max_length)),
            timeago=term.underline('time ago'))
    ]
    # content:
    callers_txt.extend([
        u'{handle} {location} {num_calls} {timeago}'
        .format(handle=lc.handle.ljust(username_max_length + 1),
                location=term.ljust(colors[idx % len(colors)](
                    lc.location or '-' * location_max_length),
                    location_max_length),
                num_calls='{0}'.format(
                    lc.num_calls).rjust(numcalls_max_length),
                timeago=colors[idx % len(colors)](
                    timeago(lc.timeago))
                ) for idx, lc in enumerate(last_callers)
    ])

    # display file contents, decoded, using a command-prompt pager.
    prompt_pager(content=callers_txt,
                 line_no=line_no + 2,
                 colors={'highlight': term.bright_green,
                         'lowlight': term.cyan, },
                 width=max(term.length(txt) for txt in callers_txt),
                 breaker=None)

