#####################################
#   Borrowed from django-tagging    #
#####################################

import math
import types
from django.db.models.query import QuerySet
from django.utils.encoding import force_unicode
from django.utils.translation import ugettext as _
from django.template.defaultfilters import slugify
from django.template.loader import render_to_string, get_template
from supertagging import settings
# Python 2.3 compatibility
try:
    set
except NameError:
    from sets import Set as set

from operator import itemgetter

def tag_instance_cmp(x, y):
    if isinstance(x, dict) and isinstance(y, dict):
        return cmp(x['offset'],y['offset'])
    return cmp(1, 1)

def parse_tag_input(input):
    """
    Parses tag input, with multiple word input being activated and
    delineated by commas and double quotes. Quotes take precedence, so
    they may contain commas.

    Returns a sorted list of unique tag names.
    """
    if not input:
        return []

    input = force_unicode(input)

    # Special case - if there are no commas or double quotes in the
    # input, we don't *do* a recall... I mean, we know we only need to
    # split on spaces.
    if u',' not in input and u'"' not in input:
        words = list(set(split_strip(input, u' ')))
        words.sort()
        return words

    words = []
    buffer = []
    # Defer splitting of non-quoted sections until we know if there are
    # any unquoted commas.
    to_be_split = []
    saw_loose_comma = False
    open_quote = False
    i = iter(input)
    try:
        while 1:
            c = i.next()
            if c == u'"':
                if buffer:
                    to_be_split.append(u''.join(buffer))
                    buffer = []
                # Find the matching quote
                open_quote = True
                c = i.next()
                while c != u'"':
                    buffer.append(c)
                    c = i.next()
                if buffer:
                    word = u''.join(buffer).strip()
                    if word:
                        words.append(word)
                    buffer = []
                open_quote = False
            else:
                if not saw_loose_comma and c == u',':
                    saw_loose_comma = True
                buffer.append(c)
    except StopIteration:
        # If we were parsing an open quote which was never closed treat
        # the buffer as unquoted.
        if buffer:
            if open_quote and u',' in buffer:
                saw_loose_comma = True
            to_be_split.append(u''.join(buffer))
    if to_be_split:
        if saw_loose_comma:
            delimiter = u','
        else:
            delimiter = u' '
        for chunk in to_be_split:
            words.extend(split_strip(chunk, delimiter))
    words = list(set(words))
    words.sort()
    return words
    
def split_strip(input, delimiter=u','):
    """
    Splits ``input`` on ``delimiter``, stripping each resulting string
    and returning a list of non-empty strings.
    """
    if not input:
        return []

    words = [w.strip() for w in input.split(delimiter)]
    return [w for w in words if w]

def edit_string_for_tags(tags):
    """
    Given list of ``SuperTag`` instances, creates a string representation of
    the list suitable for editing by the user, such that submitting the
    given string representation back without changing it will give the
    same list of tags.

    Tag names which contain commas will be double quoted.

    If any tag name which isn't being quoted contains whitespace, the
    resulting string of tag names will be comma-delimited, otherwise
    it will be space-delimited.
    """
    names = []
    use_commas = False
    for tag in tags:
        name = tag.name
        if u',' in name:
            names.append('"%s"' % name)
            continue
        elif u' ' in name:
            if not use_commas:
                use_commas = True
        names.append(name)
    if use_commas:
        glue = u', '
    else:
        glue = u' '
    return glue.join(names)

def get_queryset_and_model(queryset_or_model):
    """
    Given a ``QuerySet`` or a ``Model``, returns a two-tuple of
    (queryset, model).

    If a ``Model`` is given, the ``QuerySet`` returned will be created
    using its default manager.
    """
    try:
        return queryset_or_model, queryset_or_model.model
    except AttributeError:
        return queryset_or_model._default_manager.all(), queryset_or_model

def get_tag_list(tags):
    """
    Utility function for accepting tag input in a flexible manner.

    If a ``SuperTag`` object is given, it will be returned in a list as
    its single occupant.

    If given, the tag names in the following will be used to create a
    ``SuperTag`` ``QuerySet``:

       * A string, which may contain multiple tag names.
       * A list or tuple of strings corresponding to tag names.
       * A list or tuple of integers corresponding to tag ids.

    If given, the following will be returned as-is:

       * A list or tuple of ``SuperTag`` objects.
       * A ``SuperTag`` ``QuerySet``.

    """
    from supertagging.models import SuperTag
    if isinstance(tags, SuperTag):
        return [tags]
    elif isinstance(tags, QuerySet) and tags.model is SuperTag:
        return tags
    elif isinstance(tags, types.StringTypes):
        return SuperTag.objects.filter(name__in=parse_tag_input(tags))\
                |SuperTag.objects.filter(slug__in=parse_tag_input(tags))
    elif isinstance(tags, (types.ListType, types.TupleType)):
        if len(tags) == 0:
            return tags
        contents = set()
        for item in tags:
            if isinstance(item, types.StringTypes):
                contents.add('string')
            elif isinstance(item, Tag):
                contents.add('tag')
            elif isinstance(item, (types.IntType, types.LongType)):
                contents.add('int')
        if len(contents) == 1:
            if 'string' in contents:
                return SuperTag.objects.filter(name__in=[force_unicode(tag) for tag in tags])\
                        |SuperTag.objects.filter(slug__in=[force_unicode(tag) for tag in tags])
            elif 'tag' in contents:
                return tags
            elif 'int' in contents:
                return SuperTag.objects.filter(id__in=tags)
        else:
            raise ValueError(_('If a list or tuple of tags is provided, they must all be tag names, SuperTag objects or Tag ids.'))
    else:
        raise ValueError(_('The tag input given was invalid.'))

def get_tag(tag):
    """
    Utility function for accepting single tag input in a flexible
    manner.

    If a ``Tag`` object is given it will be returned as-is; if a
    string or integer are given, they will be used to lookup the
    appropriate ``Tag``.

    If no matching tag can be found, ``None`` will be returned.
    """
    from supertagging.models import SuperTag
    if isinstance(tag, SuperTag):
        return tag

    try:
        if isinstance(tag, types.StringTypes):
            return SuperTag.objects.get(name=tag)
        elif isinstance(tag, (types.IntType, types.LongType)):
            return SuperTag.objects.get(id=tag)
    except SuperTag.DoesNotExist:
        pass

    return None

# Font size distribution algorithms
LOGARITHMIC, LINEAR = 1, 2

def _calculate_thresholds(min_weight, max_weight, steps):
    delta = (max_weight - min_weight) / float(steps)
    return [min_weight + i * delta for i in range(1, steps + 1)]

def _calculate_tag_weight(weight, max_weight, distribution):
    """
    Logarithmic tag weight calculation is based on code from the
    `Tag Cloud`_ plugin for Mephisto, by Sven Fuchs.

    .. _`Tag Cloud`: http://www.artweb-design.de/projects/mephisto-plugin-tag-cloud
    """
    if distribution == LINEAR or max_weight == 1:
        return weight
    elif distribution == LOGARITHMIC:
        return math.log(weight) * max_weight / math.log(max_weight)
    raise ValueError(_('Invalid distribution algorithm specified: %s.') % distribution)

def calculate_cloud(tags, steps=4, distribution=LOGARITHMIC):
    """
    Add a ``font_size`` attribute to each tag according to the
    frequency of its use, as indicated by its ``count``
    attribute.

    ``steps`` defines the range of font sizes - ``font_size`` will
    be an integer between 1 and ``steps`` (inclusive).

    ``distribution`` defines the type of font size distribution
    algorithm which will be used - logarithmic or linear. It must be
    one of ``tagging.utils.LOGARITHMIC`` or ``tagging.utils.LINEAR``.
    """
    if len(tags) > 0:
        counts = [tag.count for tag in tags]
        min_weight = float(min(counts))
        max_weight = float(max(counts))
        thresholds = _calculate_thresholds(min_weight, max_weight, steps)
        for tag in tags:
            font_set = False
            tag_weight = _calculate_tag_weight(tag.count, max_weight, distribution)
            for i in range(steps):
                if not font_set and tag_weight <= thresholds[i]:
                    tag.font_size = i + 1
                    font_set = True
    return tags
    
###########################
# Freebase Util Functions #
###########################

try:
    import freebase
except ImportError:
    freebase = None

# The key from freebase that will have the topic description
FREEBASE_DESC_KEY = "/common/topic/article"

def fix_name_for_freebase(value):
    """
    Takes a name and replaces spaces with underscores, removes periods
    and capitalizes each word
    """
    words = []
    for word in value.split():
        word = word.replace(".", "")
        words.append(word.title())
    return "_".join(words)
    
def retrieve_freebase_name(name, stype):
    if not freebase:
        return name
    
    search_key = fix_name_for_freebase(name)
    fb_type = settings.FREEBASE_TYPE_MAPPINGS.get(stype, None)
    value = None
    try:
        # Try to get the exact match
        value = freebase.mqlread(
            {"name": None, "type":fb_type or [], 
             "key": {"value": search_key}})
    except:
        try:
            # Try to get a results has a generator and return its top result
            values = freebase.mqlreaditer(
                {"name": None, "type":fb_type or [], 
                 "key": {"value": search_key}})
            value = values.next()
        except Exception, e:
            # Only print error as freebase is only optional
            if settings.ST_DEBUG: print "Error using `freebase`: %s" % e
            
    if value:
        return value["name"]
    return name
    
def retrieve_freebase_desc(name, stype):
    if not freebase:
        return ""
        
    print "Retrieving the description for %s" % name
    
    fb_type = settings.FREEBASE_TYPE_MAPPINGS.get(stype, None)
    value, data = None, ""
    try:
        value = freebase.mqlread(
            {"name": name, "type": fb_type or [],
             FREEBASE_DESC_KEY: [{"id": None}]})
    except:
        try:
            values = freebase.mqlreaditer(
                {"name": name, "type": fb_type or [],
                 FREEBASE_DESC_KEY: [{"id": None}]})
            value = values.next()
        except Exception, e:
            # Only print error as freebase is only optional
            if settings.ST_DEBUG: print "Error using `freebase`: %s" % e
            
    if value and FREEBASE_DESC_KEY in value and value[FREEBASE_DESC_KEY]:
        guid = value[FREEBASE_DESC_KEY][0].get("id", None)
        if not guid:
            return data
        try:
            import urllib
            desc_url = "%s%s" % (settings.FREEBASE_DESCRIPTION_URL, guid)
            sock = urllib.urlopen(desc_url)
            data = sock.read()                            
            sock.close()
        except Exception, e:
            if settings.ST_DEBUG: print "Error getting description from freebase for tag \"%s\" - %s" % (name, e)
        
    return data
    
################
# Render Utils #
################

def render_item(item, stype, template, suffix, template_path='supertagging/render', context={}):
    """
    Use to render tags, relations, tagged items and tagger relations.
    """
    t, model, app, = None, "", ""
    
    if item:
        model = item.content_type.model.lower()
        app = item.content_type.app_label.lower()
    
    tp = "%s/%s" % (template_path, (stype or ""))
    
    try:
        # Retreive the template passed in
        t = get_template(template)
    except:
        if suffix:
            try:
                # Retrieve the template based off of type and the content object with a suffix
                t = get_template('%s/%s__%s__%s.html' % (
                    tp, app, model, suffix.lower()))
            except:
                pass
        else:
            try:
                # Retrieve the template based off of type and the content object
                t = get_template('%s/%s__%s.html' % (
                    tp, app, model))
            except:
                pass
        if not t:
            if suffix:
                try:
                    # Retrieve the template without the app/model with suffix
                    t = get_template('%s/default__%s.html' % (tp, suffix))
                except:
                    pass
            else:
                try:
                    # Retrieve the template without the app/model
                    t = get_template('%s/default.html' % tp)
                except:
                    try:
                        # Retreive the default template using just the starting template path
                        t = get_template('%s/default.html' % template_path)
                    except:
                        pass
    
    if not t: return None
    
    # Render the template
    ret = render_to_string(t.name, context)

    return ret


"""
Provides compatibility with Django 1.1

Copied from django.contrib.admin.util
"""
from django.db import models
from django.utils.encoding import force_unicode, smart_unicode, smart_str

def lookup_field(name, obj, model_admin=None):
    opts = obj._meta
    try:
        f = opts.get_field(name)
    except models.FieldDoesNotExist:
        # For non-field values, the value is either a method, property or
        # returned via a callable.
        if callable(name):
            attr = name
            value = attr(obj)
        elif (model_admin is not None and hasattr(model_admin, name) and
          not name == '__str__' and not name == '__unicode__'):
            attr = getattr(model_admin, name)
            value = attr(obj)
        else:
            attr = getattr(obj, name)
            if callable(attr):
                value = attr()
            else:
                value = attr
        f = None
    else:
        attr = None
        value = getattr(obj, name)
    return f, attr, value


def label_for_field(name, model, model_admin=None, return_attr=False):
    """
    Returns a sensible label for a field name. The name can be a callable or the
    name of an object attributes, as well as a genuine fields. If return_attr is
    True, the resolved attribute (which could be a callable) is also returned.
    This will be None if (and only if) the name refers to a field.
    """
    attr = None
    try:
        field = model._meta.get_field_by_name(name)[0]
        if isinstance(field, RelatedObject):
            label = field.opts.verbose_name
        else:
            label = field.verbose_name
    except models.FieldDoesNotExist:
        if name == "__unicode__":
            label = force_unicode(model._meta.verbose_name)
            attr = unicode
        elif name == "__str__":
            label = smart_str(model._meta.verbose_name)
            attr = str
        else:
            if callable(name):
                attr = name
            elif model_admin is not None and hasattr(model_admin, name):
                attr = getattr(model_admin, name)
            elif hasattr(model, name):
                attr = getattr(model, name)
            else:
                message = "Unable to lookup '%s' on %s" % (name, model._meta.object_name)
                if model_admin:
                    message += " or %s" % (model_admin.__class__.__name__,)
                raise AttributeError(message)

            if hasattr(attr, "short_description"):
                label = attr.short_description
            elif callable(attr):
                if attr.__name__ == "<lambda>":
                    label = "--"
                else:
                    label = pretty_name(attr.__name__)
            else:
                label = pretty_name(name)
    if return_attr:
        return (label, attr)
    else:
        return label

def display_for_field(value, field):
    from django.contrib.admin.templatetags.admin_list import _boolean_icon
    from django.contrib.admin.views.main import EMPTY_CHANGELIST_VALUE
    
    if field.flatchoices:
        return dict(field.flatchoices).get(value, EMPTY_CHANGELIST_VALUE)
    # NullBooleanField needs special-case null-handling, so it comes
    # before the general null test.
    elif isinstance(field, models.BooleanField) or isinstance(field, models.NullBooleanField):
        return _boolean_icon(value)
    elif value is None:
        return EMPTY_CHANGELIST_VALUE
    elif isinstance(field, models.DateField) or isinstance(field, models.TimeField):
        return formats.localize(value)
    elif isinstance(field, models.DecimalField):
        return formats.number_format(value, field.decimal_places)
    elif isinstance(field, models.FloatField):
        return formats.number_format(value)
    else:
        return smart_unicode(value)
