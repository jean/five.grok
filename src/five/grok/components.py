import sys, os

import martian
from zope import interface
from zope import component
from zope.annotation.interfaces import IAttributeAnnotatable
from zope.app.pagetemplate.engine import TrustedAppPT
from zope.pagetemplate import pagetemplate, pagetemplatefile
from zope.publisher.publish import mapply

import Acquisition
from OFS.SimpleItem import SimpleItem
from five.grok import interfaces

from zope.app.container.contained import Contained
import persistent

import zope.publisher.browser
class BrowserPage(zope.publisher.browser.BrowserPage, Acquisition.Implicit):
    """Browser page with implicit Acquisition."""

# XXX Should probably be a SimpleItem.
class Model(Contained, persistent.Persistent):
    # XXX Inheritance order is important here. If we reverse this,
    # then containers can't be models anymore because no unambigous MRO
    # can be established.
    interface.implements(IAttributeAnnotatable, interfaces.IContext)
    
class View(BrowserPage):
    interface.implements(interfaces.IGrokView)

    def __init__(self, context, request):
        super(View, self).__init__(context, request)
        self.__name__ = self.__view_name__
        self.static = component.queryAdapter(
            self.request,
            interface.Interface,
            name=self.module_info.package_dotted_name
            )

    @property
    def response(self):
        return self.request.response

    def __call__(self):
        mapply(self.update, (), self.request)
        if self.request.response.getStatus() in (302, 303):
            # A redirect was triggered somewhere in update().  Don't
            # continue rendering the template or doing anything else.
            return

        template = getattr(self, 'template', None)
        if template is not None:
            return self._render_template()
        return mapply(self.render, (), self.request)

    def _render_template(self):
        return self.template.render(self)

    def default_namespace(self):
        namespace = {}
        namespace['context'] = self.context
        namespace['request'] = self.request
        namespace['static'] = self.static
        namespace['view'] = self
        return namespace

    def namespace(self):
        return {}

    def __getitem__(self, key):
        # This is BBB code for Zope page templates only:
        if not isinstance(self.template, PageTemplate):
            raise AttributeError("View has no item %s" % key)

        value = self.template._template.macros[key]
        # When this deprecation is done with, this whole __getitem__ can
        # be removed.
        warnings.warn("Calling macros directly on the view is deprecated. "
                      "Please use context/@@viewname/macros/macroname\n"
                      "View %r, macro %s" % (self, key),
                      DeprecationWarning, 1)
        return value


    def url(self, obj=None, name=None, data=None):
        """Return string for the URL based on the obj and name. The data
        argument is used to form a CGI query string.
        """
        if isinstance(obj, basestring):
            if name is not None:
                raise TypeError(
                    'url() takes either obj argument, obj, string arguments, '
                    'or string argument')
            name = obj
            obj = None

        if name is None and obj is None:
            # create URL to view itself
            obj = self
        elif name is not None and obj is None:
            # create URL to view on context
            obj = self.context

        if data is None:
            data = {}
        else:
            if not isinstance(data, dict):
                raise TypeError('url() data argument must be a dict.')

        return util.url(self.request, obj, name, data=data)

    def application_url(self, name=None):
        obj = self.context
        while obj is not None:
            if isinstance(obj, Application):
                return self.url(obj, name)
            obj = obj.__parent__
        raise ValueError("No application found.")

    def redirect(self, url):
        return self.request.response.redirect(url)

    def update(self):
        pass

    def flash(self, message, type='message'):
        source = component.getUtility(
            z3c.flashmessage.interfaces.IMessageSource, name='session')
        source.send(message, type)
    
    
class BaseTemplate(object):
    """Any sort of page template"""

    interface.implements(interfaces.ITemplate)

    __grok_name__ = ''
    __grok_location__ = ''

    def __repr__(self):
        return '<%s template in %s>' % (self.__grok_name__,
                                        self.__grok_location__)

    def _annotateGrokInfo(self, name, location):
        self.__grok_name__ = name
        self.__grok_location__ = location

    def _initFactory(self, factory):
        pass

class GrokTemplate(BaseTemplate):
    """A slightly more advanced page template

    This provides most of what a page template needs and is a good base for
    writing your own page template"""

    def __init__(self, string=None, filename=None, _prefix=None):

        # __grok_module__ is needed to make defined_locally() return True for
        # inline templates
        # XXX unfortunately using caller_module means that care must be taken
        # when GrokTemplate is subclassed. You can not do a super().__init__
        # for example.
        self.__grok_module__ = martian.util.caller_module()

        if not (string is None) ^ (filename is None):
            raise AssertionError(
                "You must pass in template or filename, but not both.")

        if string:
            self.setFromString(string)
        else:
            if _prefix is None:
                module = sys.modules[self.__grok_module__]
                _prefix = os.path.dirname(module.__file__)
            self.setFromFilename(filename, _prefix)

    def __repr__(self):
        return '<%s template in %s>' % (self.__grok_name__,
                                        self.__grok_location__)

    def _annotateGrokInfo(self, name, location):
        self.__grok_name__ = name
        self.__grok_location__ = location

    def _initFactory(self, factory):
        pass

    def namespace(self, view):
        # By default use the namespaces that are defined as the
        # default by the view implementation.
        return view.default_namespace()

    def getNamespace(self, view):
        namespace = self.namespace(view)
        namespace.update(view.namespace())
        return namespace

class TrustedPageTemplate(TrustedAppPT, pagetemplate.PageTemplate):
    pass

class TrustedFilePageTemplate(TrustedAppPT, pagetemplatefile.PageTemplateFile):
    pass

class PageTemplate(GrokTemplate):

    def setFromString(self, string):
        zpt = TrustedPageTemplate()
        if martian.util.not_unicode_or_ascii(string):
            raise ValueError("Invalid page template. Page templates must be "
                             "unicode or ASCII.")
        zpt.write(string)
        self._template = zpt

    def setFromFilename(self, filename, _prefix=None):
        self._template = TrustedFilePageTemplate(filename, _prefix)

    def _initFactory(self, factory):
        factory.macros = self._template.macros

    def render(self, view):
        namespace = self.getNamespace(view)
        template = self._template
        namespace.update(template.pt_getContext())
        return template.pt_render(namespace)
