##############################################################################
#
# Copyright (c) 2007 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Widget Framework Implementation

$Id$
"""
__docformat__ = "reStructuredText"

import zope.interface
import zope.component
import zope.location
import zope.schema.interfaces
from zope.pagetemplate.interfaces import IPageTemplate
from z3c.pt import compat as viewpagetemplatefile
from zope.i18n import translate
from zope.schema.fieldproperty import FieldProperty

from z3c.form import interfaces, util, value

PLACEHOLDER = object()

StaticWidgetAttribute = value.StaticValueCreator(
    discriminators = ('context', 'request', 'view', 'field', 'widget')
    )
ComputedWidgetAttribute = value.ComputedValueCreator(
    discriminators = ('context', 'request', 'view', 'field', 'widget')
    )


class Widget(zope.location.Location):
    """Widget base class."""

    zope.interface.implements(interfaces.IWidget)

    # widget specific attributes
    name = FieldProperty(interfaces.IWidget['name'])
    label = FieldProperty(interfaces.IWidget['label'])
    mode = FieldProperty(interfaces.IWidget['mode'])
    required = FieldProperty(interfaces.IWidget['required'])
    error = FieldProperty(interfaces.IWidget['error'])
    value = FieldProperty(interfaces.IWidget['value'])
    template = None
    ignoreRequest = FieldProperty(interfaces.IWidget['ignoreRequest'])

    # The following attributes are for convenience. They are declared in
    # extensions to the simple widget.

    # See ``interfaces.IContextAware``
    context = None
    ignoreContext = False
    # See ``interfaces.IFormAware``
    form = None
    # See ``interfaces.IFieldWidget``
    field = None

    # Internal attributes
    _adapterValueAttributes = ('label', 'name', 'required')

    def __init__(self, request):
        self.request = request

    def update(self):
        """See z3c.form.interfaces.IWidget."""
        # Step 1: Determine the value.
        value = interfaces.NOVALUE
        lookForDefault = False
        # Step 1.1: If possible, get a value from the request
        if not self.ignoreRequest:
            widget_value = self.extract()
            if widget_value is not interfaces.NOVALUE:
                # Once we found the value in the request, it takes precendence
                # over everything and nothing else has to be done.
                self.value = widget_value
                value = PLACEHOLDER
        # Step 1.2: If we have a widget with a field and we have no value yet,
        #           we have some more possible locations to get the value
        if (interfaces.IFieldWidget.providedBy(self) and
            value is interfaces.NOVALUE and
            value is not PLACEHOLDER):
            # Step 1.2.1: If the widget knows about its context and the
            #              context is to be used to extract a value, get
            #              it now via a data manager.
            if (interfaces.IContextAware.providedBy(self) and
                not self.ignoreContext):
                value = zope.component.getMultiAdapter(
                    (self.context, self.field),
                    interfaces.IDataManager).query()
            # Step 1.2.2: If we still do not have a value, we can always use
            #             the default value of the field, id set
            # NOTE: It should check field.default is not missing_value, but
            # that requires fixing zope.schema first
            if ((value is self.field.missing_value or
                 value is interfaces.NOVALUE) and
                self.field.default is not None):
                value = self.field.default
                lookForDefault = True
        # Step 1.3: If we still have not found a value, then we try to get it
        #           from an attribute value
        if value is interfaces.NOVALUE or lookForDefault:
            adapter = zope.component.queryMultiAdapter(
                (self.context, self.request, self.form, self.field, self),
                interfaces.IValue, name='default')
            if adapter:
                value = adapter.get()
        # Step 1.4: Convert the value to one that the widget can understand
        if value not in (interfaces.NOVALUE, PLACEHOLDER):
            converter = interfaces.IDataConverter(self)
            self.value = converter.toWidgetValue(value)
        # Step 2: Update selected attributes
        for attrName in self._adapterValueAttributes:
            value = zope.component.queryMultiAdapter(
                (self.context, self.request, self.form, self.field, self),
                interfaces.IValue, name=attrName)
            if value is not None:
                setattr(self, attrName, value.get())

    def render(self):
        """See z3c.form.interfaces.IWidget."""
        template = self.template
        if template is None:
            template = zope.component.getMultiAdapter(
                (self.context, self.request, self.form, self.field, self),
                IPageTemplate, name=self.mode)
        return template(self)

    def extract(self, default=interfaces.NOVALUE):
        """See z3c.form.interfaces.IWidget."""
        return self.request.get(self.name, default)

    def __repr__(self):
        return '<%s %r>' % (self.__class__.__name__, self.name)


class SequenceWidget(Widget):
    """Term based sequence widget base.

    The sequence widget is used for select items from a sequence. Don't get
    confused, this widget does support to choose one or more values from a
    sequence. The word sequence is not used for the schema field, it's used
    for the values where this widget can choose from.

    This widget base class is used for build single or sequence values based
    on a sequence which is in most use case a collection. e.g.
    IList of IChoice for sequence values or IChoice for single values.

    See also the MultiWidget for build sequence values based on none collection
    based values. e.g. IList of ITextLine
    """

    zope.interface.implements(interfaces.ISequenceWidget)

    value = ()
    terms = None

    noValueToken = '--NOVALUE--'

    @property
    def displayValue(self):
        value = []
        for token in self.value:
            # Ignore no value entries. They are in the request only.
            if token == self.noValueToken:
                continue
            term = self.terms.getTermByToken(token)
            if zope.schema.interfaces.ITitledTokenizedTerm.providedBy(term):
                value.append(translate(
                    term.title, context=self.request, default=term.title))
            else:
                value.append(term.value)
        return value

    def updateTerms(self):
        if self.terms is None:
            self.terms = zope.component.getMultiAdapter(
                (self.context, self.request, self.form, self.field, self),
                interfaces.ITerms)
        return self.terms

    def update(self):
        """See z3c.form.interfaces.IWidget."""
        # Create terms first, since we need them for the generic update.
        self.updateTerms()
        super(SequenceWidget, self).update()

    def extract(self, default=interfaces.NOVALUE):
        """See z3c.form.interfaces.IWidget."""
        if (self.name not in self.request and
            self.name+'-empty-marker' in self.request):
            return []
        value = self.request.get(self.name, default)
        if value != default:
            # do some kind of validation, at least only use existing values
            for token in value:
                if token == self.noValueToken:
                    continue
                try:
                    self.terms.getTermByToken(token)
                except LookupError:
                    return default
        return value


class MultiWidget(Widget):
    """None Term based sequence widget base.

    The multi widget is used for ITuple or IList if no other widget is defined.

    Some IList or ITuple are using another specialized widget if they can
    choose from a collection. e.g. a IList of IChoice. The base class of such
    widget is the ISequenceWidget.

    This widget can handle none collection based sequences and offers add or
    remove values to or from the sequence. Each sequence value get rendered by
    it's own relevant widget. e.g. IList of ITextLine or ITuple of IInt

    Each widget get rendered within a sequence value. This means each internal
    widget will repressent one value from the mutli widget value. Based on the
    nature of this (sub) widget setup the internal widget do not have a real
    context and can't get binded to it. This makes it impossible to use a
    sequence of collection where the collection needs a context. But that
    should not be a problem since sequence of collection will use the
    SequenceWidget as base.
    """

    zope.interface.implements(interfaces.IMultiWidget)

    allowAdding = True
    # you set showLabel to False or use another template for disable (sub)
    # widget labels
    showLabel = True
    widgets = []
    _value = []

    @property
    def counterName(self):
        return '%s.count' % self.name

    @property
    def counterMarker(self):
        # this get called in render from the template and contains always the
        # right amount of widgets we use.
        return '<input type="hidden" name="%s" value="%d" />' % (
            self.counterName, len(self.widgets))

    def getWidget(self, idx):
        """Setup widget based on index id with or without value."""
        id = '%s-%i' % (self.id, idx)
        name = '%s.%i' % (self.name, idx)
        valueType = self.field.value_type
        widget = zope.component.getMultiAdapter((valueType, self.request),
            interfaces.IFieldWidget)
        widget.name = name
        widget.id = id
        widget.update()
        return widget

    def appendAddingWidget(self):
        """Simply append a new empty widget with correct (counter) name."""
        # since we start with idx 0 (zero) we can use the len as next idx
        idx = len(self.widgets)
        widget = self.getWidget(idx)
        self.widgets.append(widget)

    def applyValue(self, widget, value=interfaces.NOVALUE):
        """Validate and apply value to given widget.

        This method get called on any multi widget vaue change and is
        responsible for validate the given value and setup an error message.

        This is internal apply value and validation process is needed because
        nothing outside this mutli widget does know something about our
        internal sub widgets.
        """
        if value is not interfaces.NOVALUE:
            try:
                # convert widget value to field value
                converter = interfaces.IDataConverter(widget)
                value = converter.toFieldValue(value)
                # validate field value
                zope.component.getMultiAdapter(
                    (self.context,
                     self.request,
                     self.form,
                     getattr(widget, 'field', None),
                     widget),
                    interfaces.IValidator).validate(value)
                # convert field value to widget value
                widget.value = converter.toWidgetValue(value)
            except (zope.schema.ValidationError, ValueError), error:
                # on exception, setup the widget error message
                view = zope.component.getMultiAdapter(
                    (error, self.request, widget, widget.field,
                     self.form, self.context), interfaces.IErrorViewSnippet)
                view.update()
                widget.error = view
                # set the wrong value as value
                widget.value = value

    def updateWidgets(self):
        """Setup internal widgets based on the value_type for each value item.
        """
        oldLen = len(self.widgets)
        self.widgets = []
        if self.value:
            for idx, v in enumerate(self.value):
                widget = self.getWidget(idx)
                self.applyValue(widget, v)
                self.widgets.append(widget)
        missing = oldLen - len(self.widgets)
        if missing > 0:
            # add previous existing new added widgtes
            for i in range(missing):
                idx += 1
                widget = self.getWidget(idx)
                self.widgets.append(widget)

    @apply
    def value():
        """This invokes updateWidgets on any value change e.g. update/extract."""
        def get(self):
            return self._value
        def set(self, value):
            self._value = value
            # ensure that we apply our new values to the widgets
            self.updateWidgets()
        return property(get, set)

    def extract(self, default=interfaces.NOVALUE):
        # This method is responsible to get the widgets value based on the
        # request and nothing else.
        # We have to setup the widgets for extract their values, because we
        # don't know how to do this for every field without the right widgets.
        # Later we will setup the widgets based on this values. This is needed
        # because we probably set a new value in the fornm for our multi widget
        # which whould generate a different set of widgets.
        if self.request.get(self.counterName) is None:
            # counter marker not found
            return interfaces.NOVALUE
        counter = int(self.request.get(self.counterName, 0))
        values = []
        append = values.append
        # extract value for existing widgets
        for idx in range(counter):
            widget = self.getWidget(idx)
            append(widget.value)
        if len(values) == 0:
            # no multi value found
            return interfaces.NOVALUE
        return values


def FieldWidget(field, widget):
    """Set the field for the widget."""
    widget.field = field
    if not interfaces.IFieldWidget.providedBy(widget):
        zope.interface.alsoProvides(widget, interfaces.IFieldWidget)
    # Initial values are set. They can be overridden while updating the widget
    # itself later on.
    widget.name = field.__name__
    widget.id = field.__name__.replace('.', '-')
    widget.label = field.title
    widget.required = field.required
    return widget


class WidgetTemplateFactory(object):
    """Widget template factory."""

    def __init__(self, filename, contentType='text/html',
                 context=None, request=None, view=None,
                 field=None, widget=None):
        self.template = viewpagetemplatefile.ViewPageTemplateFile(
            filename, content_type=contentType)
        zope.component.adapter(
            util.getSpecification(context),
            util.getSpecification(request),
            util.getSpecification(view),
            util.getSpecification(field),
            util.getSpecification(widget))(self)
        zope.interface.implementer(IPageTemplate)(self)

    def __call__(self, context, request, view, field, widget):
        return self.template


class WidgetEvent(object):
    zope.interface.implements(interfaces.IWidgetEvent)

    def __init__(self, widget):
        self.widget = widget

    def __repr__(self):
        return '<%s %r>' %(self.__class__.__name__, self.widget)

class AfterWidgetUpdateEvent(WidgetEvent):
    zope.interface.implementsOnly(interfaces.IAfterWidgetUpdateEvent)
