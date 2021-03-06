"""This module provides the means for tagging servers.

Server tags are simple strings that are used to referencing the server's
configuration. For example, a tag is used to identify the game the server
is played (e.g. 'tf2' or 'csgo') and the game mode of the map.
"""

import venusian


class TaggerError(Exception):
    """Base exception for all tag-related errors."""


class DependancyError(TaggerError):
    """Raised when there's an issue with a tag's depedencies."""


class CyclicDependancyError(DependancyError):
    """Raised when there are cyclical dependencies between tags."""


class TaggerImplementation:
    """Wraps a callable that implements a tag."""

    def __init__(self, tag_name, implementation, dependancies):
        self.tag = tag_name
        self._implementation = implementation
        self._named_dependancies = frozenset(dependancies)
        self._dependancies = None

    @property
    def dependancies(self):
        """Get the dependencies as :class:`TaggerImplementation`s.

        :raises AttributeError: if accessed without making a prior call to
            :meth:`find_dependancies`.
        """
        if self._dependancies is None:
            raise AttributeError("Dependancies haven't been resolved yet.")
        return self._dependancies

    def find_dependancies(self, taggers):
        """Get the tag implementations for all dependencies.

        :param taggers: an iterable for :class:`TaggerImplementation`s.

        :raises DependancyError: if a dependency doesn't exist in the given
            ``taggers``.
        """
        tags = {tagger.tag: tagger for tagger in taggers}
        dependancies = []
        for dep in self._named_dependancies:
            if dep not in tags:
                raise DependancyError(
                    "Cannot resolve dependancy on {dep!r} for {tag!r} as "
                    "{dep!r} does not exist".format(dep=dep,
                                                    tag=tags[dep].tag))
            dependancies.append(tags[dep])
        self._dependancies = tuple(dependancies)

    def __repr__(self):
        return ("<Tag {tag!r} implmented by "
                "{_implementation}>".format(**vars(self)))

    def __call__(self, info, players, rules, tags):
        return self._implementation(info, players, rules, tags)


class Tagger:
    """Tag evaluator.

    Instances of this class are used to determine the tags that apply to
    a server configuration. It will resolve the tag dependancies so that
    tag functions are called in the correct order.

    This class should never be instantiated directly. Use :meth:`scan`
    instead.
    """

    def __init__(self, *taggers):
        """Initialise the tag evaluator.

        This takes any number of taggers and resolves their dependancies.
        If there are two implementations for the same tag name then
        :exc:`TaggerError` is raised.

        :param taggers: zero or more :class:`TaggerImplementation` objects.
        """
        tags = {}
        for tagger in taggers:
            if tagger.tag in tags:
                raise TaggerError(
                    "Duplicate implementations of the {tag!r} tag; {0!r} "
                    "{1!r}".format(
                        tags[tagger.tag],
                        tagger,
                        tag=tagger.tag))
            tags[tagger.tag] = tagger
        self.taggers = self._resolve_dependancies(tags.values())

    @staticmethod
    def _resolve_dependancies(taggers):
        """Order tag implementations based on their dependancies.

        Given an iterable of taggers this will return them sorted into a list
        so that the depended upon taggers come before those which are
        dependant on them.

        :raises CyclicDependancyError: should there be any cyclic dependacies
            within the given taggers.
        :returns: a topologically sorted list of taggers.
        """
        for tagger in taggers:
            tagger.find_dependancies(taggers)
        ordered = []
        marked = set()
        temp_marked = set()

        def visit(tagger):  # pylint: disable=missing-docstring
            if tagger.tag in temp_marked:
                raise CyclicDependancyError(
                    "{tag!r} has cyclical dependancies".format(tag=tagger.tag))
            if tagger.tag not in marked:
                temp_marked.add(tagger.tag)
                for dep in tagger.dependancies:
                    visit(dep)
                marked.add(tagger.tag)
                temp_marked.remove(tagger.tag)
                ordered.append(tagger)

        for tagger in taggers:
            if tagger.tag not in marked:
                visit(tagger)
        return ordered

    @classmethod
    def scan(cls, package):
        """Scan a package for tags.

        :param str package: the name of the package to scan.

        :return: a new :class:`Tagger` containing all the tags that were
            found.
        """
        scanner = venusian.Scanner(taggers=[])
        scanner.scan(__import__(package), categories=["serverstf.taggers"])
        return cls(*scanner.taggers)  # pylint: disable=no-member

    def evaluate(self, info, players, rules):
        """Evaluate a server's status to determine which tags apply.

        The three arguments correspond to the server info, players and rules
        as returned by a :class:`valve.source.a2s.ServerQuerier`. Each tag
        implementation is called with these parameters being being passed
        through with an additional fourth argument which is a frozenset of
        all currently applied tags.

        If a tag implementation returns ``True`` then tag applies to the
        server identified by the its info, players and rules.

        :return: a set of all the tags (as strings) that apply to the
            current server status.
        """
        tags = set()
        for tagger in self.taggers:
            if tagger(info, players, rules, frozenset(tags)):
                tags.add(tagger.tag)
        return tags


def tag(name, dependancies=()):
    """A decorator for defining tags.

    Functions marked with this decorator will be picked up by
    :meth:`Tagger.scan` and included for tag evaluation.

    The wrapped function should take four arguments: the server info, player
    list, cvars/rules list and a set of currently applied tags. If the return
    value is truthy then the named `tag` is applied otherwise it is not.

    Tags may have a dependancy on other tags. This will mean that the
    :class:`Tagger` instance running them will only invoke the wrapped function
    after all of its dependancies have been tested. Its these dependancies
    which are used to populate the fourth argument.

    .. note::

        Marking as tag as a dependancy doesn't mean it's guaranteed to be
        present in set of tags passed as the fourth argument. Checking its
        existing within the set is the responsiblity of the wrapped function.

    Care must be taken to avoid creating circular dependancies between tags.

    :param str name: The name of the tag.
    :param dependancies: A sequence off tag names that must be evaluated
        before this *this* one.
    """

    def callback(scanner, _, obj):  # pylint: disable=missing-docstring
        scanner.taggers.append(
            TaggerImplementation(name, obj, dependancies))

    def decorator(function):  # pylint: disable=missing-docstring
        venusian.attach(function, callback, category="serverstf.taggers")
        return function

    return decorator
