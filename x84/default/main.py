""" Main menu script for x/84. """
# std imports
from __future__ import division
import collections
import os
import random, glob
import math
import time


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
) or 'bold_white'

#: color used for prompt
color_backlight = get_ini(
    section='main', key='color_backlight',
) or 'green_reverse'

#: color used for brackets ``[`` and ``]``
color_lowlight = get_ini(
    section='main', key='color_lowlight'
) or 'bold_yellow'

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
) or 'cp437thin'

menutoggle = True
arttoggle = True
bgtoggle = True

walltime = time.time() - 30
art_file = ''
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

        MenuItem(inp_key=u'*',
                 text=u'menu toggle',
                 script='',
                 args=(), kwargs={}),

        MenuItem(inp_key=u'TAB',
                 text=u'refresh',
                 script='',
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

def renderscreen(menudraw=True, artdraw=True, bgdraw=True, tall=False, wide=False, widgets=['clock',]):
    global menutoggle
    global arttoggle
    global bgtoggle
    """ Rendering routine for the current screen. """
    # This is where we depart. We want a clean windowing scheme
    # with a background layer, modular construction and incremental update ability.
    # In theory we should have separate content-generating and screen-rendering subs
    # to provide for fast refreshes without stutters, but that will have to come later.
    from x84.bbs import AnsiWindow, getsession, getterminal, echo, ini, showart
    import os, time, random, glob
    session, term = getsession(), getterminal()
    colors = {}
    colors['border'] = term.green
    #lets start with the bg frame
    headers = glob.glob(os.path.join(here,"art","top","*.*"))
    background = AnsiWindow(term.height - 1, term.width, 0, 0)
    background.init_theme(colors, None, 'double')
    echo(term.clear())
    if time.time() - walltime > 30:
        art_file = headers[random.randrange(0,len(headers))]
    ypos = 1
    for line in showart(art_file, encoding=art_encoding):
	if ypos >= term.height - 3:
	    break
	echo(background.pos(ypos, 2)+line)
	ypos += 1
    echo(background.border())
#	    fillwindow(background,  chr(176).decode('cp437'), True)
  
    #now on to the top art
    if artdraw:
	    toparty = 3
	    topartx = 3
	    topartheight = 9
	    topartwidth = 37
	    topart = AnsiWindow(topartheight, topartwidth, toparty, topartx)
	    topart.init_theme(colors, None, 'block')
	    echo (topart.clear())
	    ypos = 1
	    bannername = "yos.asc"
	    #bannername = "YOSBBS"+str(random.randrange(1,35)).zfill(2)+".ANS"
	    art_file = os.path.join(os.path.dirname(__file__), 'art', bannername)
	    for line in showart(art_file, encoding=art_encoding):
		echo(topart.pos(ypos, 2)+line)
		ypos += 1
            colors['border'] = term.green
            topart.init_theme(colors, None, 'shadow')
            echo(topart.border() + topart.title(str(time.time()))) 
    if menudraw:
	    rendermenuwin()
    return ypos

def rendermenuwin():
    from x84.bbs import AnsiWindow, getsession, getterminal, echo, ini, showart
    import os
    session, term = getsession(), getterminal()

    def decorate_menu_item(menu_item, colors):
        """ Return menu item decorated. """
        key_text = (u'{lb}{inp_key}{rb}'.format(
       	lb=colors['lowlight'](u'['),
	rb=colors['lowlight'](u']'),
	inp_key=colors['highlight'](menu_item.inp_key)))

    # set the inp_key within the key_text if matching
        if menu_item.text.startswith(menu_item.inp_key):
	    return menu_item.text.replace(menu_item.inp_key, key_text, 1)

    # otherwise prefixed with space
        return (u'{key_text} {menu_text}'.format(
  	    key_text=key_text, menu_text=menu_item.text))
    max_cols = 3 
    max_rowsp=2
    top_margin = 0
    menu_items = get_menu_items(session)
    colors = {}
    if colored_menu_items:
       colors['backlight'] = getattr(term, color_backlight)
       colors['highlight'] = getattr(term, color_highlight)
       colors['lowlight'] = getattr(term, color_lowlight)
       colors['border'] = term.green
    if colors is not None:
        measure_width = term.length
    else:
        measure_width = str.__len__

    # render all menu items, highlighting their action 'key'
    rendered_menuitems = [decorate_menu_item(menu_item, colors)
                          for menu_item in menu_items]

    # create a parallel array of their measurable width
    column_widths = map(measure_width, rendered_menuitems)

    # here, we calculate how many vertical sections of menu entries
    # may be displayed in 80 columns or less -- and forat accordingly
    # so that they are left-adjusted in 1 or more tabular columns, with
    # sufficient row spacing to padd out the full vertical height of the
    # window.
    #
    # It's really just a bunch of math to make centered, tabular columns..
    display_width = min(term.width, 80)
    padding = max(column_widths) + 1
    n_columns = min(max(1, int(math.floor(display_width / padding))), max_cols)
#    xpos = max(1, int(math.floor((term.width / 2) - (display_width / 2))))
#    xpos += int(math.floor((display_width - ((n_columns * padding))) / 2))
    xpos = 0
    rows = int(math.ceil(len(rendered_menuitems) / n_columns))
    height = int(math.ceil((term.height - 3) - top_margin))
    row_spacing = min(max(1, min(3, int(math.floor(height / rows)))), max_rowsp)

    column = 1
    row = 1
    output = u''

    menuwin = AnsiWindow(rows + 2, 2+(n_columns * padding), term.height - rows - 5, 8)
    echo(menuwin.clear())

    fillwindow(menuwin,  chr(250).decode('cp437'), True)

    colors['border'] = term.red
    menuwin.init_theme(colors, None, 'shadow')
    for idx, item in enumerate(rendered_menuitems):
        xloc = 1 +(padding * (column - 1))
        padding_left = menuwin.pos(row, xloc)
            # last item, two newlines
        if column == n_columns:
            row += 1
            # newline(s) on last column only
        column = 1 if column == n_columns else column + 1
        echo(u''.join((padding_left, item)))
    echo(menuwin.border()+menuwin.title('COMMAND SET'))
    return 1


def fillwindow(window, fillchar='#',bordered=False):
    from x84.bbs import AnsiWindow, getsession, getterminal, echo, ini
    session, term = getsession(), getterminal()
    fillstarty, fillstartx = 0, 0
    fillwidth, fillheight = window.width, window.height + 1
    if bordered == True:
        fillstarty += 1
        fillstartx += 1
        fillwidth -= 2
        fillheight -= 2
    for i in range (fillstarty, fillheight):
        fillstr = fillchar * fillwidth
        echo(term.bold_black+window.pos(i, fillstartx) + fillstr)
    echo(term.normal)
    return True

def main():
    """ Main menu entry point. """
    import os, glob, random, time
    from x84.bbs import showart
    session, term = getsession(), getterminal()
    global menutoggle
    global arttoggle
    global bgtoggle

    text, width, height, dirty = u'', -1, -1, 2
    headers = glob.glob(os.path.join(here,"art","YOSBBS*.ANS"))
    menu_items = get_menu_items(session)
    colors = {}
    if colored_menu_items:
       colors['backlight'] = getattr(term, color_backlight)
       colors['highlight'] = getattr(term, color_highlight)
       colors['lowlight'] = getattr(term, color_lowlight)
    editor = get_line_editor(term, menu_items)
    menumode = False
    tallmode = False
    widemode = False

    if term.width >= 132:
        widemode = True
    if term.height >= 43:
        tallmode = True

    starttime = time.time()
    while True:
        if dirty  > 1:
            # set syncterm font, if any
            if syncterm_font and term.kind.startswith('ansi'):
                echo(syncterm_setfont(syncterm_font))
        if dirty == 2:
	    menutoggle, arttoggle, bgtoggle = True, True, True
        if dirty:
            session.activity = 'main menu'
	    if width != term.width or height != term.height:
                width, height = term.width, term.height
            top_margin = renderscreen(menutoggle, arttoggle, bgtoggle)
            echo(term.move(term.height, 2))
            echo(u''.join((text,
	    display_prompt(term, colors),
	    editor.refresh()+term.normal)))
            dirty = 0

        event, data = session.read_events(('input', 'refresh'), 1)
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
                if inp == u'*':
                    menutoggle = not menutoggle
                    dirty = True
                    break
                if inp.code == term.KEY_TAB:
                    dirty = True
                    break
                if inp.code == term.KEY_ENTER:
                    # find matching menu item,
                    for item in menu_items:
                        if item.inp_key == editor.content.strip():
                            echo(term.normal + u'\r\n')
                            gosub(item.script, *item.args, **item.kwargs)
                            editor.content = u''
                            dirty = 3
                            break
                    else:
                        if editor.content:
                            # command not found, clear prompt.
                            echo(u''.join((
                                (u'\b' * len(editor.content)),
                                (u' ' * len(editor.content)),
                                (u'\b' * len(editor.content)),)))
                            editor.content = u''
                            echo(editor.refresh()+term.normal)
                elif inp.is_sequence:
                    echo(editor.process_keystroke(inp.code))
                else:
                    echo(editor.process_keystroke(inp))
                inp = term.inkey(0)
        if time.time() - starttime > 1:
            dirty = True
            starttime = time.time()
            continue
 
