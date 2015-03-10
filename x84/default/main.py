""" Main menu script for x/84. """
# std imports
from __future__ import division
import collections
import os
import random, glob


# local
from x84.bbs import (
    syncterm_setfont,
    getterminal,
    getsession,
    LineEditor,
    get_ini,
    gosub,
    echo,
    ini,
)
from common import (
    render_menu_entries,
    display_banner,
    display_prompt,
)
here = os.path.dirname(__file__)

#: MenuItem is a definition class for display, input, and target script.
MenuItem = collections.namedtuple(
    'MenuItem', ['inp_key', 'text', 'script', 'args', 'kwargs'])

#: When set False, menu items are not colorized and render much
#: faster on slower systems (such as raspberry pi).
colored_menu_items = get_ini(
    section='main', key='colored_menu_items', getter='getboolean'
) or True

#: color used for menu key entries
color_highlight = get_ini(
    section='main', key='color_highlight'
) or 'bold_green'

#: color used for prompt
color_backlight = get_ini(
    section='main', key='color_backlight',
) or 'green_reverse'

#: color used for brackets ``[`` and ``]``
color_lowlight = get_ini(
    section='main', key='color_lowlight'
) or 'bold_white'

#: filepath to artfile displayed for this script
#art_file = get_ini(
#    section='main', key='art_file'
#) or 'art/main1.asc'



#: encoding used to display artfile
art_encoding = get_ini(
    section='main', key='art_encoding'
) or 'cp437'  # ascii, actually

#: fontset for SyncTerm emulator
syncterm_font = get_ini(
    section='main', key='syncterm_font'
) or 'topaz'


def get_sesame_menu_items(session):
    # there doesn't exist any documentation on how this works,
    # only the given examples in the generated default.ini file
    menu_items = []
    if ini.CFG.has_section('sesame'):
        for name in filter(lambda _name: '_' not in _name,
                           ini.CFG.options('sesame')):

            sesame_kwargs = {'name': name}

            door_cmd = ini.CFG.get('sesame', name).split(None, 1)[0]
            if door_cmd.lower() == 'no' or not os.path.exists(door_cmd):
                # skip entry if path does not resolve, or set to 'no'
                continue

            inp_key = get_ini(section='sesame', key='{0}_key'.format(name))
            if not inp_key:
                raise ValueError('sesame configuration for "{0}" requires '
                                 'complimenting value "{0}_key" for menu '
                                 'input key.'.format(name))

            if get_ini(section='sesame', key='{0}_sysop_only'.format(name),
                       getter='getboolean') and not session.user.is_sysop:
                continue

            text = get_ini(
                section='sesame', key='{0}_text'.format(name)
            ) or name

            menu_items.append(
                MenuItem(inp_key=inp_key, text=text, script='sesame',
                         args=(), kwargs=sesame_kwargs))

    return menu_items


def get_menu_items(session):
    """ Returns list of MenuItem entries. """
    #: A declaration of menu items and their acting gosub script
    menu_items = [
        # most 'expressive' scripts,
        MenuItem(inp_key=u'irc',
                 text=u'irc chat',
                 script='ircchat',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'who',
                 text=u"who's online",
                 script='online',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'fb',
                 text=u'file browser',
                 script='fbrowse',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'pe',
                 text=u'profile editor',
                 script='profile',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'weather',
                 text=u'weather forecast',
                 script='weather',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'hn',
                 text=u'hacker news',
                 script='hackernews',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'ol',
                 text=u'one-liners',
                 script='ol',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'tetris',
                 text=u'tetris game',
                 script='tetris',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'vote',
                 text=u'voting booth',
                 script='vote',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'lc',
                 text=u'last callers',
                 script='lc',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'user',
                 text=u'user list',
                 script='userlist',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'news',
                 text=u'news reader',
                 script='news',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'si',
                 text=u'system info',
                 script='si',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'key',
                 text=u'keyboard test',
                 script='test_keyboard_keys',
                 args=(), kwargs={}),
        MenuItem(inp_key=u'ac',
                 text=u'adjust charset',
                 script='charset',
                 args=(), kwargs={}),

        MenuItem(inp_key=u'msg',
                 text=u'message area',
                 script='msgarea',
                 args=(), kwargs={}),

        MenuItem(inp_key=u'g',
                 text=u'logoff system',
                 script='logoff',
                 args=(), kwargs={}),

    ]

    # add sysop menu for sysop users, only.
    if session.user.is_sysop:
        menu_items.append(
            MenuItem(inp_key='sysop',
                     text=u'sysop area',
                     script='sysop',
                     args=(), kwargs={}))

    # add sesame doors, if any.
    menu_items.extend(get_sesame_menu_items(session))
    return menu_items


def get_line_editor(term, menu):
    """ Return a line editor suitable for menu entry prompts. """
    # if inp_key's were CJK characters, you should use term.length to measure
    # printable length of double-wide characters ... this is too costly to
    # enable by default.  Just a note for you east-asian folks.
    max_inp_length = max([len(item.inp_key) for item in menu])
    return LineEditor(width=max_inp_length,
                      colors={'highlight': getattr(term, color_backlight)})

def renderscreen(items=['all',], tall=False, wide=False, widgets=['clock',]):
    """ Rendering routine for the current screen. """
    # This is where we depart. We want a clean windowing scheme
    # with a background layer, modular construction and incremental update ability.
    # In theory we should have separate content-generating and screen-rendering subs
    # to provide for fast refreshes without stutters, but that will have to come later.
    from x84.bbs import AnsiWindow, getsession, getterminal, echo, ini
    session, term = getsession(), getterminal()
    #lets start with the bg frame
    background = AnsiWindow(term.height - 2, term.width - 2, 0, 0)
    echo(background.clear() + background.border())
    fillwindow(background, '*', True)
    return True

def fillwindow(window, fillchar='#',bordered=False):
    from x84.bbs import AnsiWindow, getsession, getterminal, echo, ini
    fillstartx, fillstarty = window.xloc, window.yloc
    fillwidth, fillheight = window.width, window.height
    if bordered:
        fillstartx += 1
        fillstarty += 1
        fillwidth -= 2
        fillheight -= 2
    return True

def main():
    """ Main menu entry point. """
    import os, glob, random
    from x84.bbs import showart
    session, term = getsession(), getterminal()

    text, width, height, dirty = u'', -1, -1, 2
    headers = glob.glob(os.path.join(here,"art","YOSBBS*.ANS"))
    menu_items = get_menu_items(session)
    editor = get_line_editor(term, menu_items)
    colors = {}
    menumode = False
    tallmode = False
    widemode = False

    if term.width >= 132:
        widemode = True
    if term.height >= 43:
        tallmode = True

    if colored_menu_items:
        colors['backlight'] = getattr(term, color_backlight)
        colors['highlight'] = getattr(term, color_highlight)
        colors['lowlight'] = getattr(term, color_lowlight)

    while True:
        renderscreen()
        if dirty == 2:
            # set syncterm font, if any
            if syncterm_font and term.kind.startswith('ansi'):
                echo(syncterm_setfont(syncterm_font))
        if dirty:
            ypos = 1
            echo(term.move(1,1))
            session.activity = 'main menu'
	    bannername = "YOSBBS"+str(random.randrange(1,35)).zfill(2)+".ANS"
	    art_file = os.path.join(os.path.dirname(__file__), 'art', bannername)
            for line in showart(art_file, encoding=art_encoding):
                echo(line)
                ypos += 1
            top_margin = term.height - ypos - 4
            echo(u'\r\n')
            if width != term.width or height != term.height:
                width, height = term.width, term.height
                text = render_menu_entries(
                    term, top_margin, menu_items, colors, 4, 1)
            echo(u''.join((text,
                           display_prompt(term, colors),
                           editor.refresh())))
            dirty = 0

        event, data = session.read_events(('input', 'refresh'))

        if event == 'refresh':
            dirty = True
            continue

        elif event == 'input':
            session.buffer_input(data, pushback=True)

            # we must loop over inkey(0), we received a 'data'
            # event, though there may be many keystrokes awaiting for our
            # decoding -- or none at all (multibyte sequence not yet complete).
            inp = term.inkey(0)
            while inp:
                if inp.code == term.KEY_ENTER:
                    # find matching menu item,
                    for item in menu_items:
                        if item.inp_key == editor.content.strip():
                            echo(term.normal + u'\r\n')
                            gosub(item.script, *item.args, **item.kwargs)
                            editor.content = u''
                            dirty = 2
                            break
                    else:
                        if editor.content:
                            # command not found, clear prompt.
                            echo(u''.join((
                                (u'\b' * len(editor.content)),
                                (u' ' * len(editor.content)),
                                (u'\b' * len(editor.content)),)))
                            editor.content = u''
                            echo(editor.refresh())
                elif inp.is_sequence:
                    echo(editor.process_keystroke(inp.code))
                else:
                    echo(editor.process_keystroke(inp))
                inp = term.inkey(0)
