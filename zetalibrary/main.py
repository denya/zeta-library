import optparse
import os.path
import re
import sys
import urllib2

from scss.parser import Stylecheet


BASEDIR = os.path.realpath(os.path.dirname(__file__))
ZETALIBDIR = os.path.join(BASEDIR, 'zetalib')

CSS_PARAMS = dict(
    import_parser = re.compile(r'^\s*@import +url\(\s*["\']?([^\)\'\"]+)["\']?\s*\)\s*;?\s*$', re.MULTILINE),
    comment_parser = re.compile(r'/\*(?:[^*]|\*+[^*/])*\*+/'),
    comment_template = '/* %s */\n',
    link_parser = re.compile(r'url\(\s*["\']?([^\)\'\"]+)["\']?\)'),
    link_template = "url(%s)",
    link_ignore = ('data:image', 'http://', 'https://'),
)

SCSS_PARAMS = dict(CSS_PARAMS)
SCSS_PARAMS['parser'] = Stylecheet

JS_PARAMS = dict(
    import_parser = re.compile(r'^require\(\s*[\'\"]([^\'\"]+)[\'\"]\)\s*;?\s*$', re.MULTILINE),
    comment_parser = re.compile(r'/\*(?:[^*]|\*+[^*/])*\*+/'),
    comment_template = '// %s\n',
)

FORMATS = dict(css=CSS_PARAMS, scss=SCSS_PARAMS, js=JS_PARAMS)


class LinkerError( Exception ):
    """Linker error.
    """
    def __init__( self, message, parent=None ):
        if parent:
            message = "%s: %s" % (parent, message)
        super( LinkerError, self ).__init__( message )


class Linker( object ):
    """ Link js and css files in to one.
    """
    def __init__(self, path, **kwargs):
        self.path = path
        self.no_comments = kwargs.get('no_comments')
        self.prefix = kwargs.get('prefix', '_')
        self.format = kwargs.get('format')

        self.imported = set()
        self.tree = list()
        self.basedir = os.path.relpath( os.path.dirname( path ))
        self.curfile = self.params = None

    def link( self ):
        """ Parse and save file.
        """
        self.out("Packing '%s'." % self.path)
        self.parse_tree(self.path)
        out = ''
        for item in self.tree:
            src = item['src'].strip()
            parse = FORMATS[item['format']].get('parser')
            if parse:
                if isinstance(parse, type):
                    FORMATS[item['format']]['parser'] = parse = parse()
                src = parse.parse(src)
            if not src:
                continue
            out += "".join([
                self.params['comment_template'] % ("=" * 30),
                self.params['comment_template'] % "Zeta import: '%s'" % item['current'],
                self.params['comment_template'] % "From: '%s'" % item['parent'],
                src,
                "\n\n\n",
            ])

        pack_name = self.prefix + os.path.basename(self.path)
        pack_path = os.path.join(self.basedir, pack_name)

        try:
            open(pack_path, 'w').write(out)
            self.out("Linked file saved as: '%s'." % pack_path)
        except IOError, ex:
            raise LinkerError(ex)

    def parse_tree( self, path, parent=None ):
        """ Parse import structure.
        """
        path = path.strip()
        filetype = os.path.splitext(path)[1][1:] or ''
        try:
            f = self.format or filetype
            self.params = FORMATS[f]
        except KeyError:
            raise LinkerError("Unknow format file: '%s'" % path)

        try:
            src = self.open_path(path).read()
        except IOError, ex:
            raise LinkerError(ex, parent)

        curdir = os.path.relpath(os.path.dirname(path))

        def children(obj):
            child_path = obj.group(1)
            child_path = self.parse_path(child_path, curdir)
            if child_path in self.imported:
                # self.out("%s: %s already imported." % (path, child_path))
                return ''
            self.imported.add(child_path)
            try:
                self.parse_tree(child_path, path)
                return ''
            except (OSError, LinkerError):
                self.out("%s: import file '%s' does not exist." % (path, child_path), error=True)

        def links(obj):
            link_path = obj.group(1)
            if self.params.get('link_ignore'):
                for ignore in self.params['link_ignore']:
                    if link_path.startswith(ignore):
                        return self.params['link_template'] % link_path
            try:
                return self.params['link_template'] % os.path.relpath(os.path.join(curdir, link_path), self.basedir)
            except OSError:
                self.out('Url error: [%s] -- %s' % (curdir, path), error=True)

        # Parse src
        import_parser = self.params['import_parser']
        src = import_parser.sub(children, src)

        if self.params.has_key('link_parser'):
            link_parser = self.params['link_parser']
            src = link_parser.sub(links, src)

        if self.no_comments and self.params.has_key('comment_parser'):
            comment_parser = self.params['comment_parser']
            src = comment_parser.sub('', src)

        self.tree.append(dict(src=src, parent=parent, current=path, format=f))

    def parse_path(self, path, curdir):
        """ Parse path.
        """
        if path.startswith('http://'):
            return path

        elif path.startswith('/'):
            return os.path.relpath(os.path.normpath(os.path.join(self.basedir, path)))

        elif path.startswith('zeta://'):
            path = path[7:]
            return os.path.relpath(os.path.normpath(os.path.join(ZETALIBDIR, path)))

        return os.path.relpath(os.path.normpath(os.path.join(curdir, path)))

    def link_parse(self, src, curdir):
        """ Parse links.
        """
        def parse( obj ):
            """ Regexp search.
            """
            link = obj.group(0)
            path = obj.group(1)
            if self.params.get('link_ignore'):
                for ignore in self.params['link_ignore']:
                    if path.startswith(ignore):
                        return link
            try:
                return link.replace(path, os.path.relpath(os.path.join(curdir, path), self.basedir))
            except OSError:
                self.out('Url error: [%s] -- %s' % (curdir, path), error=True)

        return self.params['link_parse'].sub(parse, src)

    def open_path(self, path):
        """ Read source.
        """
        if path.startswith('http://'):
            name = os.path.basename(path)
            import_path = os.path.join(self.basedir, name)
            if not os.path.exists(import_path):
                src = urllib2.urlopen(path).read()
                open(import_path, 'w').write(src)

            path = import_path
        return open(path, 'r')

    @staticmethod
    def out( message, error=False ):
        """ Out messages.
        """
        pipe = sys.stdout if not error else sys.stderr
        pipe.write("\n  * %s\n" % message)


def route( path, prefix='_' ):
    """ Route files.
    """
    def test_file( filepath ):
        """ Test file is static and not parsed.
        """
        name, ext = os.path.splitext(os.path.basename(filepath))
        filetype = ext[1:]
        return os.path.isfile(filepath) and not name.startswith(prefix) and filetype in FORMATS.keys()

    if os.path.isdir( path ):
        for name in os.listdir(path):
            filepath = os.path.join(path, name)
            if test_file(filepath):
                yield filepath

    elif test_file(path):
        yield path


def main():
    """ Parse arguments.
    """
    p = optparse.OptionParser(
        usage="%prog [--prefix PREFIX] FILENAME or DIRNAME",
        description="Parse file or dir, import css, js code and save with prefix.")

    p.add_option(
        '-p', '--prefix', default='_', dest='prefix',
        help="Save result with prefix. Default is '_'.")

    p.add_option(
        '-f', '--format', dest='format',
        help="Force use this format.")

    p.add_option(
        '-n', '--no-comments', action='store_true', dest='no_comments',
        help="Clear comments.")

    options, args = p.parse_args()
    if len(args) != 1:
        p.print_help(sys.stdout)
        return

    path = args[0]
    try:
        assert os.path.exists(path)
    except AssertionError:
        p.error("'%s' does not exist." % args[0])

    for path in route(path, options.prefix):
        try:
            linker = Linker(path, prefix=options.prefix, no_comments=options.no_comments, format=options.format)
            linker.link()
        except LinkerError, ex:
            p.error(ex)
